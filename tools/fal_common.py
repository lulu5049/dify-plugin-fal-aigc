"""Fal queue + media helpers shared by the Dify tools.

No Fal key is logged. Requests use queue.fal.run, not the synchronous endpoint.
"""
import base64
import ipaddress
import json
import mimetypes
import re
import time
from urllib.parse import urlsplit

import requests

BASE = 'https://queue.fal.run'
MODELS = {
    't2v': 'minimax/h3-max/text-to-video',
    'i2v': 'minimax/h3-max/image-to-video',
    'merge': 'fal-ai/ffmpeg-api/merge-videos',
    'zimage': 'fal-ai/z-image/turbo',
}
MAX_MEDIA_MB = 55
MAX_WAIT_SECONDS = 840


class FalError(ValueError):
    pass


def _required_key(credentials):
    key = str(credentials.get('api_key') or '').strip()
    if not key:
        raise FalError('Please configure Fal API Key in the plugin credentials.')
    return key


def _body(response):
    try:
        obj = response.json()
    except ValueError as exc:
        raise FalError(f'Fal returned invalid JSON (HTTP {response.status_code}).') from exc
    if response.status_code >= 400:
        detail = obj.get('detail', obj.get('message', obj)) if isinstance(obj, dict) else obj
        raise FalError(f'Fal HTTP {response.status_code}: {str(detail)[:500]}')
    if not isinstance(obj, dict):
        raise FalError('Unexpected Fal response (expected object).')
    return obj


def _queue_url(path):
    if not isinstance(path, str) or not path.startswith(BASE + '/'):
        raise FalError('Unexpected Fal queue URL: only https://queue.fal.run is accepted.')
    return path


class FalQueue:
    def __init__(self, credentials, session=None):
        self.session = session or requests.Session()
        self.headers = {'Authorization': f'Key {_required_key(credentials)}',
                        'Content-Type': 'application/json'}

    def submit(self, model, payload):
        if model not in MODELS.values():
            raise FalError('Unsupported Fal model.')
        response = self.session.post(f'{BASE}/{model}', json=payload,
                                     headers=self.headers, timeout=45)
        data = _body(response)
        request_id = data.get('request_id')
        if not request_id:
            raise FalError('Fal did not return a request_id.')
        return {'request_id': str(request_id), 'model': model,
                'status_url': _queue_url(data.get('status_url') or f'{BASE}/{model}/requests/{request_id}/status'),
                'response_url': _queue_url(data.get('response_url') or f'{BASE}/{model}/requests/{request_id}')}

    @staticmethod
    def task(model, request_id):
        if model not in MODELS.values():
            raise FalError('Unsupported model for status lookup.')
        request_id = str(request_id or '').strip()
        if not request_id or '/' in request_id or '?' in request_id or '#' in request_id:
            raise FalError('Invalid request_id.')
        return {'model': model, 'request_id': request_id,
                'status_url': f'{BASE}/{model}/requests/{request_id}/status',
                'response_url': f'{BASE}/{model}/requests/{request_id}'}

    def status(self, task):
        response = self.session.get(_queue_url(task['status_url']), headers=self.headers,
                                    params={'logs': '1'}, timeout=25)
        return _body(response)

    def result(self, task):
        response = self.session.get(_queue_url(task['response_url']), headers=self.headers,
                                    timeout=45)
        return _body(response)

    def events(self, task, wait_seconds=540, poll_interval=3):
        """Generate Fal queue events; return a result only for a terminal success.

        If the job has not finished by the deadline, raise an error instead of
        signalling a successful Dify node with an incomplete media response.
        """
        try:
            seconds = float(wait_seconds)
        except (ValueError, TypeError) as exc:
            raise FalError('wait_seconds must be numeric.') from exc
        if seconds <= 0 or seconds > MAX_WAIT_SECONDS:
            raise FalError(f'wait_seconds must be 1..{MAX_WAIT_SECONDS}.')
        deadline = time.monotonic() + seconds
        last_report = None
        last_emit = 0.0
        history = []
        while True:
            response = self.status(task)
            status = str(response.get('status') or 'UNKNOWN').upper()
            if status not in ('IN_QUEUE', 'IN_PROGRESS', 'COMPLETED', 'FAILED', 'CANCELLED'):
                raise FalError(f"Fal returned an unexpected job status {status!r}; request_id={task['request_id']}")
            queue_position = response.get('queue_position') if status == 'IN_QUEUE' else None
            logs = response.get('logs') or []
            last_log = next((str(x.get('message'))[:160] for x in reversed(logs)
                             if isinstance(x, dict) and x.get('message')), '')
            signature = (status, queue_position, last_log)
            now = time.monotonic()
            if status != last_report or signature != last_emit or now - getattr(self, '_last_heartbeat', 0) >= 15:
                event = {'status': status, 'queue_position': queue_position,
                         'last_log': last_log}
                if not history or history[-1] != event:
                    history.append(event)
                    history = history[-60:]
                yield {'kind': 'status', 'event': event}
                last_report = status
                last_emit = signature
                self._last_heartbeat = now
            if status == 'COMPLETED':
                yield {'kind': 'result', 'result': self.result(task), 'history': history}
                return
            if status in ('FAILED', 'CANCELLED'):
                error = response.get('error') or response.get('detail') or response.get('message') or status
                raise FalError(f"Fal task {status}: {str(error)[:450]}; request_id={task['request_id']}")
            if time.monotonic() >= deadline:
                raise FalError(f"Fal task is still {status} after {seconds:g}s; request_id={task['request_id']}; "
                               "the task may still be running on Fal. Check it by ID to avoid paying for a duplicate.")
            time.sleep(min(float(poll_interval), max(0, deadline - time.monotonic())))

    def wait(self, task, wait_seconds=540):
        # Compatibility for check_job: returns only a completed result, never a
        # positive return status from a timed-out generation node.
        for event in self.events(task, wait_seconds):
            if event['kind'] == 'result':
                return 'COMPLETED', event['result']
        raise FalError('Unexpected incomplete task.')


def _is_public_https_url(value):
    parts = urlsplit(value)
    if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password:
        return False
    if parts.port not in (None, 443):
        return False
    host = parts.hostname.lower().rstrip('.')
    if host == 'localhost' or host.endswith(('.local', '.internal')):
        return False
    try:
        ipaddress.ip_address(host)
        return False  # Block direct IPs; media URLs should use public DNS.
    except ValueError:
        return True


def media_bytes(url, max_mb=MAX_MEDIA_MB):
    """Fetch completed Fal output for Dify blob; protect RAM and reject local URLs."""
    if not isinstance(url, str) or not _is_public_https_url(url):
        raise FalError('Invalid or non-public HTTPS media URL.')
    limit = max_mb * 1024 * 1024
    # Disable HTTP redirects to avoid redirected local-service fetching.
    with requests.get(url, timeout=(15, 90), stream=True, allow_redirects=False) as response:
        if not (200 <= response.status_code < 300):
            raise FalError(f'Media download failed: HTTP {response.status_code}')
        length = int(response.headers.get('Content-Length') or 0)
        if length > limit:
            raise FalError(f'Media exceeds the {max_mb} MB plugin file limit (URL is still available).')
        chunks, size = [], 0
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            size += len(chunk)
            if size > limit:
                raise FalError(f'Media exceeds the {max_mb} MB plugin file limit (URL is still available).')
            chunks.append(chunk)
        return b''.join(chunks)


def to_image_url(file_obj, url=''):
    """Convert a Dify uploaded file to Fal's accepted data URI (no public Dify URL needed)."""
    if file_obj is not None:
        data = getattr(file_obj, 'blob', None)
        if callable(data):
            data = data()
        if data:
            if len(data) > 15 * 1024 * 1024:
                raise FalError('Uploaded image is over 15 MB; use an HTTPS image URL.')
            mime = str(getattr(file_obj, 'mime_type', '') or 'image/png').split(';')[0]
            if mime not in ('image/jpeg', 'image/png', 'image/webp'):
                mime = 'image/png'
            return f'data:{mime};base64,{base64.b64encode(data).decode("ascii")}'
        maybe_url = str(getattr(file_obj, 'url', '') or '')
        if maybe_url and _is_public_https_url(maybe_url):
            return maybe_url
        raise FalError('Could not access uploaded image content; provide a public HTTPS image URL.')
    url = str(url or '').strip()
    if url and (_is_public_https_url(url) or url.startswith('data:image/')):
        return url
    return ''


def parse_video_urls(value):
    """Accept URLs, JSON, copied Dify output, or newline/comma-delimited links.

    Never require users to construct an array string in the workflow editor.
    Extracting URLs from invalid copied JSON is intentional, but each extracted
    address is still checked for public HTTPS before submission to Fal.
    """
    if value is None or value == '':
        return []
    if isinstance(value, dict):
        for field in ('video_urls', 'video_url', 'url', 'text', 'json'):
            if value.get(field):
                return parse_video_urls(value[field])
        raise FalError('No video URL found in the supplied object.')
    if isinstance(value, (list, tuple)):
        urls = []
        for item in value:
            urls.extend(parse_video_urls(item))
        return urls
    value = str(value).strip()
    if not value:
        return []
    # Dify sometimes renders colon escapes, Markdown, or JSON as plain text.
    value = value.replace('\\:', ':').replace('\\/', '/')
    if value.startswith(('[', '{')):
        try:
            parsed = json.loads(value)
            if parsed != value:
                return parse_video_urls(parsed)
        except (json.JSONDecodeError, ValueError):
            pass  # Be forgiving of missing quotes in pasted URL arrays.
    # Extract full HTTPS URLs from multiline strings, copied JSON, and even
    # malformed arrays like ["https://a.mp4,"https://b.mp4"].
    matches = re.findall(r"https?://[^\s\"'<>\[\]{}]+", value)
    urls = []
    for match in matches:
        # Commas separating adjacent URLs must not become part of the URL.
        for part in re.split(r'[,;](?=\s*https?://)', match):
            part = part.strip().rstrip(',;')
            if part:
                urls.append(part)
    if not urls:
        raise FalError('No video HTTPS URL found. Choose an upstream video_url variable or paste one URL per line.')
    if not all(_is_public_https_url(u) for u in urls):
        raise FalError('All video URLs must be public HTTPS addresses accessible by Fal.')
    return urls


def collect_merge_video_urls(parameters):
    """Merge two required upstream video URLs, three optional URLs and extras.

    Each direct Dify field accepts exactly one URL; the optional list can have
    any number of additional URLs and is appended after the first five slots.
    """
    urls = []
    for i in range(1, 6):
        value = parameters.get(f'video_url_{i}')
        if i <= 2 and not value:
            raise FalError(
                f'Video {i} URL is required. Select the upstream video_url '
                f'output from a previous video generation node.'
            )
        if not value:
            continue
        parsed = parse_video_urls(value)
        if len(parsed) != 1:
            raise FalError(
                f'Video {i} URL must contain exactly one HTTPS video URL. '
                f'Use More Video URLs for additional clips.'
            )
        urls.append(parsed[0])
    if parameters.get('video_urls'):
        urls.extend(parse_video_urls(parameters['video_urls']))
    return urls

def output_messages(tool, model, task, result, include_file=True, history=None):
    """Yield structured JSON + text URL + optional Dify native file/image."""
    if not result:
        raise FalError(f"Fal returned no completed result; request_id={task['request_id']}")
    data = result.get('data', result)  # supports SDK-style wrappers, normal Fal REST body
    if not isinstance(data, dict):
        raise FalError('Fal result is not a JSON object.')
    is_image = model == MODELS['zimage']
    media = data.get('images', []) if is_image else [data.get('video', {})]
    if not isinstance(media, list) or not media:
        raise FalError('Fal completed without a media file.')
    urls = [m.get('url') for m in media if isinstance(m, dict) and m.get('url')]
    if not urls:
        raise FalError('Fal completed without a media URL.')
    overview = {'request_id': task['request_id'], 'model': model, 'status': 'COMPLETED',
                'image_url': urls[0] if is_image else '',
                'image_urls': urls if is_image else [],
                'status_history': history or [{'status': 'COMPLETED'}],
                'video_url': '' if is_image else urls[0]}
    yield tool.create_json_message(overview)
    for url in urls:
        yield tool.create_text_message(url)
        if is_image:
            if include_file:
                yield tool.create_image_message(url)
        elif include_file:
            try:
                blob = media_bytes(url)
                # Dify SDK >=0.9 accepts only (blob, meta), not save_as.
                # The filename is advisory metadata; the MP4 URL is the
                # canonical output even when the Dify frontend cannot preview it.
                yield tool.create_blob_message(
                    blob, meta={'mime_type': 'video/mp4', 'filename': 'fal_video.mp4'}
                )
            except Exception as exc:
                # A completed, paid Fal video must never be marked failed just
                # because the optional Dify file attachment cannot be emitted.
                yield tool.create_text_message(
                    f'Video generated successfully at {url}; '
                    f'optional Dify MP4 attachment unavailable ({type(exc).__name__}: {exc}).'
                )
    # Explicit tool output variables make workflow node chaining possible:
    # text-to-video.video_url -> merge_videos.video_url_1, and so on.
    yield tool.create_variable_message('request_id', task['request_id'])
    yield tool.create_variable_message('status', 'COMPLETED')
    yield tool.create_variable_message('media_url', urls[0])
    if is_image:
        yield tool.create_variable_message('image_url', urls[0])
        yield tool.create_variable_message('image_urls', urls)
    else:
        yield tool.create_variable_message('video_url', urls[0])


def completed_generation(tool, model, payload, wait_seconds=540, include_file=True):
    """Dify ToolInvokeMessage generator; never returns success before media.

    Status text messages are emitted while polling. Whether Dify displays them
    live is version-dependent, but they are retained as node tool text output.
    """
    client = FalQueue(tool.runtime.credentials)
    task = client.submit(model, payload)
    yield tool.create_text_message(f"Fal task submitted: request_id={task['request_id']}")
    for event in client.events(task, wait_seconds=wait_seconds):
        if event['kind'] == 'status':
            state = event['event']
            msg = f"Fal status: {state['status']} | request_id={task['request_id']}"
            if state['queue_position'] is not None:
                msg += f" | queue_position={state['queue_position']}"
            if state['last_log']:
                msg += f" | {state['last_log']}"
            yield tool.create_text_message(msg)
        else:
            yield from output_messages(tool, model, task, event['result'],
                                       include_file=include_file,
                                       history=event['history'])
