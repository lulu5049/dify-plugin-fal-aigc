from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]

def test_source_structure():
    manifest = yaml.safe_load((ROOT/'manifest.yaml').read_text())
    provider = yaml.safe_load((ROOT/'provider/fal_aigc.yaml').read_text())
    assert manifest['type'] == 'plugin'
    assert manifest['name'] == provider['identity']['name']
    assert manifest['author'] == provider['identity']['author']
    assert manifest['resource']['permission']['tool']['enabled'] is True
    assert not any((ROOT / k).exists() for k in ('.env', 'fal_key.txt'))

def test_no_unsupported_show_on_in_tool_parameters():
    """Keep compatibility with Dify installations without conditional controls."""
    manifest = yaml.safe_load((ROOT / 'manifest.yaml').read_text())
    assert manifest['meta']['version'] == '0.0.5'
    provider = yaml.safe_load((ROOT / 'provider/fal_aigc.yaml').read_text())
    for rel in provider['tools']:
        tool = yaml.safe_load((ROOT / rel).read_text())
        for param in tool.get('parameters', []):
            assert 'show_on' not in param, f'unsupported show_on: {rel}'
            assert 'select_on' not in param, f'unsupported select_on: {rel}'
            if param.get('type') == 'select':
                assert param.get('default') in [opt['value'] for opt in param.get('options', [])] or param.get('default') is None
