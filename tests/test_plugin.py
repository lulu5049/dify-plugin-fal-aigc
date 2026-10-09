import importlib
import json
import sys
import types
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Dify SDK is not available in this offline test environment. Stub just the
# public base class and message factory to test tool behavior.
if 'dify_plugin' not in sys.modules:
    fake = types.ModuleType('dify_plugin')
    class Tool:
        def create_json_message(self, data): return ('json', data)
        def create_text_message(self, data): return ('text', data)
        def create_image_message(self, data): return ('image', data)
        def create_blob_message(self, blob, meta=None):
            return ('blob', blob, meta)
    fake.Tool = Tool
    sys.modules['dify_plugin'] = fake
    fake_ent = types.ModuleType('dify_plugin.entities')
    fake_tool = types.ModuleType('dify_plugin.entities.tool')
    fake_tool.ToolInvokeMessage = object
    sys.modules['dify_plugin.entities'] = fake_ent
    sys.modules['dify_plugin.entities.tool'] = fake_tool

from tools import fal_common

class Response:
    status_code = 200
    def __init__(self, jsondata, status=200):
        self._data = jsondata
        self.status_code = status
    def json(self): return self._data

class Session:
    def __init__(self):
        self.posts = []
        self.gets = []
    def post(self, url, **kw):
        self.posts.append((url, kw))
        return Response({'request_id': 'job-123',
                         'status_url': 'https://queue.fal.run/minimax/h3-max/text-to-video/requests/job-123/status',
                         'response_url': 'https://queue.fal.run/minimax/h3-max/text-to-video/requests/job-123'})
    def get(self, url, **kw):
        self.gets.append((url, kw))
        if url.endswith('/status'):
            return Response({'status': 'COMPLETED'})
        return Response({'video': {'url': 'https://v3.fal.media/files/a.mp4'}})

class Creds:
    credentials = {'api_key': 'TEST_EXAMPLE_SECRET'}


def test_queue_submit_and_result():
    s = Session()
    f = fal_common.FalQueue(Creds.credentials, s)
    task = f.submit(fal_common.MODELS['t2v'], {'prompt': 'demo', 'duration': 5})
    status, body = f.wait(task, 1)
    assert status == 'COMPLETED'
    assert body['video']['url'].endswith('.mp4')
    assert s.posts[0][0] == 'https://queue.fal.run/minimax/h3-max/text-to-video'
    assert s.posts[0][1]['headers']['Authorization'] == 'Key TEST_EXAMPLE_SECRET'


def test_json_array_video_urls():
    urls = ['https://a.example/a.mp4', 'https://b.example/b.mp4', 'https://c.example/c.mp4']
    assert fal_common.parse_video_urls(json.dumps(urls)) == urls
    assert fal_common.parse_video_urls('\n'.join(urls)) == urls
    with pytest.raises(fal_common.FalError):
        fal_common.parse_video_urls('https://only.one/a.mp4')


def test_refuse_nonpublic_urls():
    with pytest.raises(fal_common.FalError):
        fal_common.parse_video_urls('["http://localhost/x.mp4","https://foo.com/y.mp4"]')
    with pytest.raises(fal_common.FalError):
        fal_common.FalQueue.task('unknown/path', 'abc')


def test_uploaded_image_to_data_uri():
    obj = types.SimpleNamespace(blob=b'abc', mime_type='image/png')
    assert fal_common.to_image_url(obj).startswith('data:image/png;base64,YWJj')


def test_video_emits_mp4_blob(monkeypatch):
    monkeypatch.setattr(fal_common, 'media_bytes', lambda url: b'FAKE_MP4')
    tool = sys.modules['dify_plugin'].Tool()
    task = {'request_id': 'job-1'}
    msgs = list(fal_common.output_messages(tool, fal_common.MODELS['t2v'], task,
                     {'video': {'url': 'https://v3.fal.media/files/demo.mp4'}}, True))
    assert msgs[0][1]['video_url'].endswith('demo.mp4')
    assert msgs[2][0] == 'blob'
    assert msgs[2][1] == b'FAKE_MP4'
    assert msgs[2][2]['mime_type'] == 'video/mp4'
    assert msgs[2][2]['filename'] == 'fal_video.mp4'


def test_model_specific_payloads(monkeypatch):
    jobs = []
    def fake_generated(tool, model, payload, wait_seconds=540, include_file=True):
        jobs.append((model, payload, wait_seconds))
        yield tool.create_text_message('Fal status: IN_QUEUE')
        yield tool.create_text_message('Fal status: IN_PROGRESS')
        yield tool.create_json_message({'status': 'COMPLETED', 'image_url': 'https://x.test/out.jpg'})
    monkeypatch.setattr(fal_common, 'completed_generation', fake_generated)
    # Import symbols inside individual modules (from-import binds early).
    from tools import text_to_video, image_to_video, generate_image, merge_videos
    for mod in (text_to_video, image_to_video, generate_image, merge_videos):
        monkeypatch.setattr(mod, 'completed_generation', fake_generated)
    for cls, args in [
        (text_to_video.TextToVideoTool, {'prompt': 'move'}),
        (image_to_video.ImageToVideoTool, {'prompt': 'move', 'image_url': 'https://example.com/a.png'}),
        (generate_image.GenerateImageTool, {'prompt': 'picture'}),
        (merge_videos.MergeVideosTool, {'video_urls': '["https://example.com/1.mp4","https://example.com/2.mp4"]'}),
    ]:
        inst = cls()
        inst.runtime = Creds()
        messages = list(inst._invoke(args))
        assert [m[0] for m in messages] == ['text', 'text', 'json']
        assert messages[-1][1]['status'] == 'COMPLETED'
    assert jobs[0][1]['duration'] == 5
    assert jobs[0][1]['resolution'] == '480P'
    assert jobs[0][1]['prompt_expansion_mode'] == 'disabled'
    assert jobs[1][1]['image_url'] == 'https://example.com/a.png'
    assert jobs[2][0] == fal_common.MODELS['zimage']
    assert jobs[2][1]['image_size'] == 'landscape_16_9'
    assert jobs[2][1]['num_inference_steps'] == 8
    assert jobs[2][1]['enable_prompt_expansion'] is False
    assert jobs[3][1]['video_urls'] == ['https://example.com/1.mp4','https://example.com/2.mp4']
    assert 'resolution' not in jobs[3][1]
    assert len(fal_common.MODELS) == 4  # only the user-selected image model


def test_status_transitions_and_only_terminal_result(monkeypatch):
    s = Session()
    queue = fal_common.FalQueue(Creds.credentials, s)
    polls = iter([{'status':'IN_QUEUE', 'queue_position':3},
                  {'status':'IN_QUEUE', 'queue_position':1},
                  {'status':'IN_PROGRESS', 'logs':[{'message':'Generating'}]},
                  {'status':'COMPLETED'}])
    monkeypatch.setattr(queue, 'status', lambda task: next(polls))
    monkeypatch.setattr(queue, 'result', lambda task: {'images':[{'url':'https://some.example/image.jpg'}]})
    monkeypatch.setattr(fal_common.time, 'sleep', lambda _: None)
    events = list(queue.events(queue.task(fal_common.MODELS['zimage'], 'job-xyz'), 90))
    assert [e['event']['status'] for e in events if e['kind']=='status'] == [
        'IN_QUEUE','IN_QUEUE','IN_PROGRESS','COMPLETED']
    assert events[-1]['kind'] == 'result'
    assert [e['status'] for e in events[-1]['history']] == [
        'IN_QUEUE', 'IN_QUEUE', 'IN_PROGRESS', 'COMPLETED']
    assert events[-1]['history'][0]['queue_position'] == 3


def test_failed_job_is_node_error(monkeypatch):
    queue = fal_common.FalQueue(Creds.credentials, Session())
    monkeypatch.setattr(queue, 'status', lambda task: {'status':'FAILED', 'error':'Fal GPU exception'})
    with pytest.raises(fal_common.FalError, match='job-fail'):
        list(queue.events(queue.task(fal_common.MODELS['t2v'], 'job-fail'), 30))


def test_timeout_never_reports_success(monkeypatch):
    queue = fal_common.FalQueue(Creds.credentials, Session())
    monkeypatch.setattr(queue, 'status', lambda task: {'status':'IN_QUEUE','queue_position':9})
    times = iter([1.,1.,100.])
    monkeypatch.setattr(fal_common.time, 'monotonic', lambda: next(times,100.))
    with pytest.raises(fal_common.FalError, match='job-timeout'):
        list(queue.events(queue.task(fal_common.MODELS['t2v'], 'job-timeout'), 2))


def test_any_length_merge_list():
    urls = [f'https://videos.example/{n}.mp4' for n in range(25)]
    assert fal_common.parse_video_urls(json.dumps(urls)) == urls


def test_yaml_and_resources():
    manifest = yaml.safe_load((ROOT / 'manifest.yaml').read_text())
    provider = yaml.safe_load((ROOT / 'provider/fal_aigc.yaml').read_text())
    assert manifest['plugins']['tools'] == ['provider/fal_aigc.yaml']
    assert len(provider['tools']) == 5
    assert manifest['meta']['runner']['version'] == '3.12'
    for path in provider['tools']:
        doc = yaml.safe_load((ROOT / path).read_text())
        assert (ROOT / doc['extra']['python']['source']).is_file()
        assert doc['identity']['name'] == Path(path).stem
        for p in doc['parameters']:
            assert p['type'] in ('string','number','boolean','select','file')
            if p['type'] == 'select':
                assert p['options']
    assert (ROOT / '_assets/icon.svg').is_file()

def test_optional_mp4_attachment_error_preserves_completed_result(monkeypatch):
    """A paid, completed Fal job cannot fail because Dify rejects the optional blob."""
    monkeypatch.setattr(fal_common, 'media_bytes', lambda url: b'FAKE_MP4')
    class ToolWithoutBlob(sys.modules['dify_plugin'].Tool):
        def create_blob_message(self, blob, meta=None):
            raise TypeError('Dify file output unavailable')
    msgs = list(fal_common.output_messages(
        ToolWithoutBlob(), fal_common.MODELS['t2v'],
        {'request_id': 'done-job'},
        {'video': {'url': 'https://v3.fal.media/files/done.mp4'}}, True))
    assert msgs[0][0] == 'json'
    assert msgs[0][1]['status'] == 'COMPLETED'
    assert msgs[0][1]['video_url'].endswith('done.mp4')
    assert msgs[1] == ('text', 'https://v3.fal.media/files/done.mp4')
    assert 'attachment unavailable' in msgs[2][1]
