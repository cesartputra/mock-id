import hashlib
import json
from app.config import ROOT, WEIGHTS


def verify_assets():
    manifest = json.loads((ROOT / 'model-manifest.json').read_text())
    missing = []
    for entry in manifest:
        path = WEIGHTS / entry['file']
        if not path.is_file():
            missing.append(entry['file'])
        elif hashlib.sha256(path.read_bytes()).hexdigest() != entry['sha256']:
            missing.append(entry['file']+' (checksum tidak cocok)')
    return missing
