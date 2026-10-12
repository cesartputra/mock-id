"""Compare Swin PAD CPU/CoreML on public fixtures, including executed EPs."""
import json
import platform
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import cv2
import numpy as np
import onnxruntime as ort
from app.config import WEIGHTS
from app.services.antispoof import PAD_FILE, face_tensor, options, softmax
from app.services.face import FaceService
from app.services.inference import coreml_options
from app.services.assets import verify_assets


def main():
    if platform.system() != 'Darwin' or platform.machine() != 'arm64' or 'CoreMLExecutionProvider' not in ort.get_available_providers():
        raise RuntimeError('Benchmark CoreML membutuhkan Mac Apple Silicon dan CoreML EP.')
    if verify_assets():
        raise RuntimeError('Bobot belum lengkap/valid. Jalankan npm run setup.')
    directory = ROOT / '.cache' / 'coreml-benchmark'
    directory.mkdir(parents=True, exist_ok=True)
    image = cv2.imread(str(ROOT / 'tests' / 'fixtures' / 'astronaut.png'))
    face = FaceService().one(image)
    tensors = [face_tensor(frame, face) for frame in [image, cv2.GaussianBlur(image, (7, 7), 2), cv2.convertScaleAbs(image, alpha=.8)]]
    sessions, timings, traces, outputs = {}, {}, {}, {}
    for name, providers in [('cpu', ['CPUExecutionProvider']), ('coreml', [('CoreMLExecutionProvider', coreml_options(WEIGHTS / PAD_FILE)), 'CPUExecutionProvider'])]:
        opt = options()
        opt.enable_profiling = True
        opt.profile_file_prefix = str(directory / name)
        started = time.perf_counter()
        session = ort.InferenceSession(str(WEIGHTS / PAD_FILE), opt, providers=providers)
        initialized = time.perf_counter() - started
        input_name = session.get_inputs()[0].name
        outputs[name] = [session.run(None, {input_name: tensor})[0] for tensor in tensors]
        durations = []
        for _ in range(7):
            started = time.perf_counter()
            session.run(None, {input_name: tensors[0]})
            durations.append(time.perf_counter() - started)
        timings[name] = {'initialization_seconds': round(initialized, 4),
                         'median_seconds': round(statistics.median(durations), 4),
                         'runs_seconds': [round(v, 4) for v in durations]}
        trace = Path(session.end_profiling())
        counts = {}
        for event in json.loads(trace.read_text()):
            provider = event.get('args', {}).get('provider')
            if provider:
                counts[provider] = counts.get(provider, 0) + 1
        traces[name] = counts
        sessions[name] = session.get_providers()
        del session
    error = max(float(np.max(np.abs(a-b))) for a, b in zip(outputs['cpu'], outputs['coreml']))
    probability_error = max(float(np.max(np.abs(softmax(a)-softmax(b)))) for a, b in zip(outputs['cpu'], outputs['coreml']))
    executed = traces['coreml'].get('CoreMLExecutionProvider', 0) > 0
    passed = executed and error < .001 and probability_error < .001
    report = {'platform': platform.system(), 'architecture': platform.machine(), 'onnxruntime': ort.__version__,
              'provider_options': {k: v for k, v in coreml_options(WEIGHTS / PAD_FILE).items() if k != 'ModelCacheDirectory'},
              'registered_providers': sessions, 'executed_provider_events': traces, 'timings': timings,
              'max_absolute_logits_error': error, 'max_absolute_probability_error': probability_error,
              'validation_passed': passed,
              'scope': 'Three public astronaut variants; seven warmed calls, profiling enabled. Hybrid provider execution, not physical GPU/ANE attribution, camera FPS or KYC accuracy.'}
    target = directory / 'report.json'
    target.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    print('Report:', target)
    if not passed:
        raise RuntimeError('CoreML tidak mengeksekusi operasi atau parity melampaui toleransi.')


if __name__ == '__main__':
    main()
