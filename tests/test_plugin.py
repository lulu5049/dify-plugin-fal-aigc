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
        def create_variable_message(self, name, value): return ('variable', name, value)
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
    assert fal_common.parse_video_urls('https://only.one/a.mp4') == ['https://only.one/a.mp4']
    with pytest.raises(fal_common.FalError, match='Video 2 URL is required'):
        fal_common.collect_merge_video_urls({'video_url_1':'https://only.one/a.mp4'})


def test_refuse_nonpublic_urls():
    with pytest.raises(fal_common.FalError):
        fal_common.parse_video_urls('["http://localhost/x.mp4","https://foo.com/y.mp4"]')
    with pytest.raises(fal_common.FalError):
        fal_common.FalQueue.task('unknown/path', 'abc')


def test_uploaded_image_to_data_uri():
    obj = types.SimpleNamespace(blob=b'abc', mime_type='image/png')
    assert fal_common.to_image_url(obj).startswith('data:image/png;base64,YWJj')


def test_video_output_is_url_only_and_does_not_download(monkeypatch):
    def refuse_download(*args, **kwargs):
        raise AssertionError('MP4 download must never occur')
    monkeypatch.setattr(fal_common.requests, 'get', refuse_download)
    tool = sys.modules['dify_plugin'].Tool()
    for model in (fal_common.MODELS['t2v'], fal_common.MODELS['i2v'],
                  fal_common.MODELS['merge']):
        url = 'https://v3.fal.media/files/demo.mp4'
        msgs = list(fal_common.output_messages(
            tool, model, {'request_id':'job-1'}, {'video':{'url':url}}))
        assert [m[0] for m in msgs] == ['json', 'variable']
        assert msgs[0][1]['video_url'] == url
        assert msgs[0][1]['status'] == 'COMPLETED'
        assert msgs[1] == ('variable','video_url',url)


def test_model_specific_payloads(monkeypatch):
    jobs = []
    def fake_generated(tool, model, payload, wait_seconds=540, include_image_preview=True):
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
        (merge_videos.MergeVideosTool, {'video_url_1': 'https://example.com/1.mp4',
                                      'video_url_2': 'https://example.com/2.mp4'}),
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

def test_merge_from_individual_node_output_variables():
    clip1 = 'https://v3b.fal.media/files/b/0aada9b3/clip1.mp4'
    clip2 = 'https://v3b.fal.media/files/b/0aada9b3/clip2.mp4'
    clip3 = 'https://v3b.fal.media/files/b/0aada9b3/clip3.mp4'
    p = {'video_url_1':clip1, 'video_url_2':clip2,
         'video_url_3':'', 'video_url_4':clip3}
    assert fal_common.collect_merge_video_urls(p) == [clip1, clip2, clip3]


def test_merge_malformed_escaped_paste():
    clip = 'https://v3b.fal.media/files/b/0aada9b3/JmJXpr-6MF1hQUY5SsSEh_minimax-h3.mp4'
    # Matches the kind of pasted string users get when quotes are missing
    # and URL scheme is escaped as https\:.
    pasted = '["https\\://' + clip[8:] + ',"https\\://' + clip[8:] + '"]'
    assert fal_common.parse_video_urls(pasted) == [clip, clip]
    assert fal_common.collect_merge_video_urls({
        'video_url_1': clip, 'video_url_2': clip, 'video_urls': pasted
    }) == [clip, clip, clip, clip]


def test_merge_json_and_multiline_and_dify_variable_output():
    urls = ['https://v3.fal.media/a.mp4','https://v3.fal.media/b.mp4']
    assert fal_common.parse_video_urls('\n'.join(urls)) == urls
    assert fal_common.parse_video_urls(json.dumps(urls)) == urls
    assert fal_common.parse_video_urls([{'video_url':urls[0]},{'video_url':urls[1]}]) == urls
    assert fal_common.collect_merge_video_urls({
        'video_url_1': urls[0], 'video_url_2': urls[1]
    }) == urls
    assert fal_common.collect_merge_video_urls({
        'video_url_1': urls[0], 'video_url_2': urls[1],
        'video_urls': '\n'.join(urls)
    }) == urls + urls


def test_image_preview_still_exists():
    tool = sys.modules['dify_plugin'].Tool()
    url='https://v3.fal.media/picture.jpg'
    msgs = list(fal_common.output_messages(
        tool, fal_common.MODELS['zimage'], {'request_id':'img-1'},
        {'images':[{'url':url}]}))
    assert [m[0] for m in msgs] == ['json','image','variable']
    assert msgs[0][1]['image_url'] == url
    assert msgs[2] == ('variable','image_url',url)


def test_check_job_has_one_generic_url_output_on_completion():
    tool = sys.modules['dify_plugin'].Tool()
    msgs = list(fal_common.output_messages(
        tool, fal_common.MODELS['t2v'], {'request_id':'job-done'},
        {'video': {'url':'https://v3.fal.media/video.mp4'}},
        url_variable='url'))
    assert [m[0] for m in msgs] == ['json', 'variable']
    assert msgs[1] == ('variable','url','https://v3.fal.media/video.mp4')


def test_normal_success_has_no_redundant_text_even_when_no_file():
    tool = sys.modules['dify_plugin'].Tool()
    msgs = list(fal_common.output_messages(
        tool, fal_common.MODELS['t2v'], {'request_id':'job-done'},
        {'video': {'url':'https://v3.fal.media/video.mp4'}},
        include_image_preview=False))
    assert [m[0] for m in msgs] == ['json', 'variable']


def test_output_schema_declares_one_url_variable_per_tool():
    from pathlib import Path
    import yaml
    root = Path(__file__).resolve().parents[1]
    tool_urls = {
        'text_to_video':'video_url', 'image_to_video':'video_url',
        'generate_image':'image_url', 'merge_videos':'video_url',
        'check_job':'url'
    }
    for tool, expected_url in tool_urls.items():
        config=yaml.safe_load((root/'tools'/f'{tool}.yaml').read_text())
        props=config['output_schema']['properties']
        assert list(props) == [expected_url]
        assert props[expected_url]['type'] == 'string'
        assert 'select_on' not in str(config)
        assert 'show_on' not in str(config)
    merge=yaml.safe_load((root/'tools/merge_videos.yaml').read_text())
    p={x['name']:x for x in merge['parameters']}
    assert all(f'video_url_{i}' in p for i in range(1,6))
    assert not any(f'video_url_{i}' in p for i in range(6,9))
    assert p['video_url_1']['required'] is True
    assert p['video_url_2']['required'] is True
    assert all(p[f'video_url_{i}']['required'] is False for i in (3,4,5))
    assert p['video_urls']['required'] is False


def test_merge_requires_both_first_two_urls_even_with_extras():
    url = 'https://v3.fal.media/video.mp4'
    with pytest.raises(fal_common.FalError, match='Video 1 URL is required'):
        fal_common.collect_merge_video_urls({
            'video_url_2': url, 'video_urls': url + '\n' + url
        })
    with pytest.raises(fal_common.FalError, match='Video 2 URL is required'):
        fal_common.collect_merge_video_urls({
            'video_url_1': url, 'video_urls': url + '\n' + url
        })


def test_merge_five_fields_followed_by_unlimited_extra_urls():
    entries = [f'https://v3.fal.media/clip{n}.mp4' for n in range(1, 10)]
    params = {f'video_url_{n}':entries[n - 1] for n in range(1, 6)}
    params['video_urls'] = '\n'.join(entries[5:])
    assert fal_common.collect_merge_video_urls(params) == entries


def test_single_direct_slot_rejects_accidental_multiple_urls():
    with pytest.raises(fal_common.FalError, match='exactly one'):
        fal_common.collect_merge_video_urls({
            'video_url_1':'https://v3.fal.media/1.mp4\nhttps://v3.fal.media/2.mp4',
            'video_url_2':'https://v3.fal.media/3.mp4',
        })


def test_no_video_file_controls_or_downloader():
    from pathlib import Path
    import yaml
    root=Path(__file__).resolve().parents[1]
    for name in ('text_to_video','image_to_video','merge_videos','check_job'):
        doc=yaml.safe_load((root/'tools'/f'{name}.yaml').read_text())
        assert 'return_file' not in [p['name'] for p in doc['parameters']]
        impl=(root/'tools'/f'{name}.py').read_text()
        assert 'return_file' not in impl and 'create_blob_message' not in impl
    common=(root/'tools/fal_common.py').read_text()
    for obsolete in ('media_bytes','create_blob_message','MAX_MEDIA_MB'):
        assert obsolete not in common
