"""Download pinned inference weights and verify SHA-256; no uploaded data is sent."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import ssl
import sys
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault('MPLCONFIGDIR', str(ROOT / '.cache' / 'matplotlib'))
import certifi
from app.config import WEIGHTS


def digest(path):
    hasher = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024*1024), b''):
            hasher.update(block)
    return hasher.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--warmup', action='store_true')
    args = parser.parse_args()
    manifest = json.loads((ROOT / 'model-manifest.json').read_text())
    context = ssl.create_default_context(cafile=certifi.where())
    for item in manifest:
        target = WEIGHTS / item['file']
        if target.is_file() and digest(target) == item['sha256']:
            print('OK', item['file'], flush=True)
            continue
        if args.check:
            raise SystemExit('Model hilang/berubah: '+item['file']+'. Jalankan setup_models.py tanpa --check.')
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix+'.part')
        print(f'Download {item["file"]} ({item["bytes"]/1024/1024:.1f} MB)', flush=True)
        try:
            req = urllib.request.Request(item['url'], headers={'User-Agent': 'mock-id-model-setup/2.0'})
            with urllib.request.urlopen(req, context=context, timeout=120) as response, temporary.open('wb') as output:
                for block in iter(lambda: response.read(1024*1024), b''):
                    output.write(block)
            if digest(temporary) != item['sha256']:
                raise RuntimeError('Checksum gagal: '+item['file'])
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
    print('Semua bobot model terverifikasi.', flush=True)
    if args.warmup:
        import cv2
        import numpy as np
        from app.model.repository import Repository
        from app.services.pipeline import VerificationService
        service = VerificationService(Repository())
        service.load()
        image = np.full((500, 850, 3), 255, np.uint8)
        cv2.putText(image, 'NIK: 1234567890123456', (40, 100), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0,0,0), 2)
        result = service.ocr.read(image)
        if result['fields']['nik'] != '1234567890123456':
            raise SystemExit('Smoke test OCR gagal: NIK test tidak terbaca.')
        print('Warmup real inference dan smoke test OCR berhasil.', flush=True)


if __name__ == '__main__':
    main()
