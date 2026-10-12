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
    if requested not in {'auto', 'coreml', 'cpu', 'cuda'}:
        raise ValueError('MOCK_ID_PAD_PROVIDER harus auto, coreml, cuda, atau cpu.')
    available = ort.get_available_providers()
    mac = platform.system() == 'Darwin' and platform.machine() == 'arm64'
    linux = platform.system() == 'Linux'
    selected = 'cpu'
    if requested in ['auto','coreml'] and mac and 'CoreMLExecutionProvider' in available: selected = 'coreml'
    elif requested in ['auto','cuda'] and linux and 'CUDAExecutionProvider' in available: selected = 'cuda'
    reason = None
    if selected == 'cpu' and requested in ['coreml','cuda']:
        reason = 'Provider/perangkat yang diminta tidak tersedia; PAD memakai CPU.'
    elif selected == 'cpu' and requested == 'auto':
        reason = 'Akselerator CoreML/CUDA kompatibel tidak tersedia; PAD memakai CPU.'
    return {'requested': requested, 'selected': selected, 'fallback_reason': reason,
            'runtime': {'cpu':'ONNX / CPU','coreml':'ONNX / CoreML + CPU','cuda':'ONNX / CUDA + CPU'}[selected]}



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
        if self.status['selected'] in ['coreml','cuda']:
            try:
                provider = 'CoreMLExecutionProvider' if self.status['selected']=='coreml' else 'CUDAExecutionProvider'
                config = coreml_options(path) if self.status['selected']=='coreml' else {'device_id':int(os.getenv('MOCK_ID_CUDA_DEVICE','0'))}
                self.session = ort.InferenceSession(self.path, options, providers=[(provider,config),'CPUExecutionProvider'])
                if provider not in self.session.get_providers(): raise RuntimeError('Provider tidak terdaftar pada session.')
            except Exception:
                self._cpu('Inisialisasi '+self.status['selected'].upper()+' gagal; PAD berjalan melalui CPU.')
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
            if self.status['selected'] == 'cpu':
                raise
            self._cpu('Eksekusi '+self.status['selected'].upper()+' gagal; PAD diperiksa ulang melalui CPU.')
            return self.session.run(outputs, inputs)
