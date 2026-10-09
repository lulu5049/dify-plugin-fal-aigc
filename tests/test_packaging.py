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
