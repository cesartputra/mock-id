"""Maintainer export only. Runtime needs ONNX Runtime, not PyTorch/CUDA."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--checkpoint', type=Path, required=True)
    parser.add_argument('--checkpoint-sha256', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    if sha256(args.checkpoint) != args.checkpoint_sha256:
        raise SystemExit('Checkpoint checksum mismatch.')
    import cv2
    import numpy as np
    import onnx
    import onnxruntime as ort
    import torch
    from app.services.antispoof import face_tensor, options, PAD_REVISION, PAD_MODEL
    from app.services.face import FaceService
    from app.services.vendor.cvpr2024_swin.model import swin_v2_b
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    # Restricted unpickler; never execute arbitrary checkpoint pickle code.
    checkpoint = torch.load(args.checkpoint, map_location='cpu', weights_only=True, mmap=True)
    state = checkpoint.get('state_dict', checkpoint)
    state = {key.removeprefix('module.'): value for key, value in state.items()}
    model = swin_v2_b(num_classes=2, fp16=False)
    model.load_state_dict(state, strict=True)
    model.eval()
    class Logits(torch.nn.Module):
        def __init__(self, model):
            super().__init__();self.model = model
        def forward(self, value):
            return self.model(value)[1]
    wrapper = Logits(model).eval()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    print('Exporting official Swin V2-B weights to ONNX FP32...', flush=True)
    torch.onnx.export(wrapper, torch.zeros(1, 3, 224, 224), str(args.output),
                      opset_version=17, input_names=['face_rgb'], output_names=['logits'],
                      do_constant_folding=True, dynamo=False)
    onnx.checker.check_model(str(args.output))
    session = ort.InferenceSession(str(args.output), options(), providers=['CPUExecutionProvider'])
    detector = FaceService()
    image = cv2.imread(str(ROOT/'tests/fixtures/astronaut.png'))
    samples = [image, cv2.GaussianBlur(image, (25, 25), 0), cv2.flip(image, 1)]
    evidence = []
    for index, sample in enumerate(samples):
        tensor = face_tensor(sample, detector.one(sample))
        with torch.inference_mode():
            reference = wrapper(torch.from_numpy(tensor)).numpy()
        started = time.perf_counter()
        exported = session.run(None, {'face_rgb': tensor})[0]
        elapsed = time.perf_counter()-started
        error = float(np.max(np.abs(exported-reference)))
        np.testing.assert_allclose(exported, reference, rtol=1e-4, atol=1e-4)
        evidence.append({'fixture': ['public_astronaut', 'public_astronaut_blur', 'public_astronaut_mirror'][index],
                         'max_logit_absolute_error': error, 'onnx_cpu_seconds': round(elapsed, 4)})
    report = {'model': PAD_MODEL, 'source_revision': PAD_REVISION,
              'checkpoint_sha256': args.checkpoint_sha256,
              'onnx_sha256': sha256(args.output), 'onnx_bytes': args.output.stat().st_size,
              'classes': {'0': 'live', '1': 'spoof'}, 'input': [1, 3, 224, 224],
              'export': {'torch': torch.__version__, 'onnx': onnx.__version__, 'opset': 17, 'precision': 'fp32'},
              'parity': evidence, 'scope': 'Numerical export parity on public fixtures; not a KYC accuracy benchmark.'}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    main()
