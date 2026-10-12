"""Validated hybrid CoreML policy for the fixed-shape Swin PAD model."""
import hashlib
import logging
import os
import platform

import onnxruntime as ort
from app.config import ROOT

log = logging.getLogger(__name__)
COREML_OPTIONS = {'ModelFormat': 'NeuralNetwork', 'MLComputeUnits': 'ALL',
                  'RequireStaticInputShapes': '1', 'EnableOnSubgraphs': '0'}


def pad_policy():
    requested = os.getenv('MOCK_ID_PAD_PROVIDER', 'auto').lower()
    if requested not in {'auto', 'coreml', 'cpu'}:
        raise ValueError('MOCK_ID_PAD_PROVIDER harus auto, coreml, atau cpu.')
    compatible = platform.system() == 'Darwin' and platform.machine() == 'arm64'
    available = 'CoreMLExecutionProvider' in ort.get_available_providers()
    selected = 'coreml' if requested != 'cpu' and compatible and available else 'cpu'
    reason = None
    if requested != 'cpu' and selected == 'cpu':
        reason = 'CoreML membutuhkan Apple Silicon dan ONNX Runtime dengan CoreML EP.'
    return {'requested': requested, 'selected': selected, 'fallback_reason': reason,
            'runtime': 'ONNX / CoreML + CPU' if selected == 'coreml' else 'ONNX / CPU'}


def coreml_options(path):
    # A replaced model must never reuse an old compiled graph under the same name.
    digest = hashlib.sha256()
    with open(path, 'rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    cache = ROOT / '.cache' / 'coreml' / ort.__version__ / digest.hexdigest() / 'nn-all-static-v1'
    cache.mkdir(parents=True, exist_ok=True)
    return {**COREML_OPTIONS, 'ModelCacheDirectory': str(cache)}


class PadSession:
    def __init__(self, path, options):
        self.path, self.options = str(path), options
        self.status = {**pad_policy(), 'loaded': False, 'providers': []}
        if self.status['selected'] == 'coreml':
            try:
                self.session = ort.InferenceSession(self.path, options,
                    providers=[('CoreMLExecutionProvider', coreml_options(path)), 'CPUExecutionProvider'])
                if 'CoreMLExecutionProvider' not in self.session.get_providers():
                    raise RuntimeError('CoreML provider tidak terdaftar pada session.')
            except Exception:
                self._cpu('Inisialisasi CoreML gagal; PAD berjalan melalui CPU.')
        else:
            self.session = ort.InferenceSession(self.path, options, providers=['CPUExecutionProvider'])
        self.status.update(loaded=True, providers=self.session.get_providers())

    def _cpu(self, reason):
        log.warning(reason)
        self.session = ort.InferenceSession(self.path, self.options, providers=['CPUExecutionProvider'])
        self.status.update(selected='cpu', runtime='ONNX / CPU', fallback_reason=reason,
                           providers=self.session.get_providers())

    def get_inputs(self):
        return self.session.get_inputs()

    def get_outputs(self):
        return self.session.get_outputs()

    def get_providers(self):
        return self.session.get_providers()

    def run(self, outputs, inputs):
        try:
            return self.session.run(outputs, inputs)
        except Exception:
            if self.status['selected'] != 'coreml':
                raise
            self._cpu('Eksekusi CoreML gagal; PAD diperiksa ulang melalui CPU.')
            return self.session.run(outputs, inputs)
