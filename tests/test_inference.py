"""Provider selection, cache invalidation and observable CPU fallback."""
from types import SimpleNamespace
import numpy as np
import pytest
from app.services import inference


def mac(monkeypatch):
    monkeypatch.setattr(inference.platform, 'system', lambda: 'Darwin')
    monkeypatch.setattr(inference.platform, 'machine', lambda: 'arm64')
    monkeypatch.setattr(inference.ort, 'get_available_providers', lambda: ['CoreMLExecutionProvider', 'CPUExecutionProvider'])
    monkeypatch.setenv('MOCK_ID_PAD_PROVIDER', 'auto')


def test_policy_selects_mac_and_honors_cpu_override(monkeypatch):
    mac(monkeypatch)
    assert inference.pad_policy()['selected'] == 'coreml'
    monkeypatch.setenv('MOCK_ID_PAD_PROVIDER', 'cpu')
    assert inference.pad_policy()['selected'] == 'cpu'
    monkeypatch.setenv('MOCK_ID_PAD_PROVIDER', 'coreml')
    monkeypatch.setattr(inference.platform, 'machine', lambda: 'x86_64')
    assert inference.pad_policy()['selected'] == 'cpu'
    assert inference.pad_policy()['fallback_reason']
    monkeypatch.setenv('MOCK_ID_PAD_PROVIDER', 'invalid')
    with pytest.raises(ValueError): inference.pad_policy()


def test_missing_ep_uses_cpu(monkeypatch):
    mac(monkeypatch)
    monkeypatch.setattr(inference.ort, 'get_available_providers', lambda: ['CPUExecutionProvider'])
    assert inference.pad_policy()['selected'] == 'cpu'


def test_compiled_cache_changes_with_weights_and_ort(monkeypatch, tmp_path):
    monkeypatch.setattr(inference, 'ROOT', tmp_path)
    model = tmp_path / 'model.onnx'
    model.write_bytes(b'first model')
    first = inference.coreml_options(model)
    model.write_bytes(b'replacement')
    second = inference.coreml_options(model)
    assert first['ModelCacheDirectory'] != second['ModelCacheDirectory']
    monkeypatch.setattr(inference.ort, '__version__', 'future-version')
    assert second['ModelCacheDirectory'] != inference.coreml_options(model)['ModelCacheDirectory']
    assert second['ModelFormat'] == 'NeuralNetwork'
    assert second['MLComputeUnits'] == 'ALL'


@pytest.mark.parametrize('failure', ['initialize', 'run', 'registration'])
def test_coreml_failure_is_recomputed_on_cpu_and_reported(monkeypatch, tmp_path, failure):
    mac(monkeypatch)
    monkeypatch.setattr(inference, 'ROOT', tmp_path)
    model = tmp_path / 'model.onnx'
    model.write_bytes(b'model')
    calls = []
    class Session:
        def __init__(self, provider): self.provider = provider
        def get_providers(self): return ['CPUExecutionProvider'] if failure == 'registration' else [self.provider]
        def get_inputs(self): return [SimpleNamespace(name='input')]
        def get_outputs(self): return [SimpleNamespace(name='output')]
        def run(self, outputs, inputs):
            if self.provider == 'CoreMLExecutionProvider': raise RuntimeError('device failed')
            return [inputs['input'] + 1]
    def create(path, options, providers):
        provider = providers[0][0] if isinstance(providers[0], tuple) else providers[0]
        calls.append(provider)
        if provider == 'CoreMLExecutionProvider' and failure == 'initialize': raise RuntimeError('compile failed')
        return Session(provider)
    monkeypatch.setattr(inference.ort, 'InferenceSession', create)
    managed = inference.PadSession(model, None)
    np.testing.assert_array_equal(managed.run(None, {'input': np.array([2.])})[0], [3.])
    assert calls == ['CoreMLExecutionProvider', 'CPUExecutionProvider']
    assert managed.status['requested'] == 'auto'
    assert managed.status['loaded'] and managed.status['selected'] == 'cpu'
    assert managed.status['fallback_reason'] and managed.status['runtime'] == 'ONNX / CPU'
    assert managed.get_inputs()[0].name == 'input'
    assert managed.get_outputs()[0].name == 'output'


def test_cpu_failure_is_not_hidden(monkeypatch):
    monkeypatch.setenv('MOCK_ID_PAD_PROVIDER', 'cpu')
    def unavailable(*_args, **_kwargs): raise RuntimeError('model broken')
    monkeypatch.setattr(inference.ort, 'InferenceSession', unavailable)
    with pytest.raises(RuntimeError, match='model broken'): inference.PadSession('model.onnx', None)


def test_linux_cuda_selection_and_no_cuda_on_mac(monkeypatch):
    monkeypatch.setenv('MOCK_ID_PAD_PROVIDER','cuda')
    monkeypatch.setattr(inference.platform,'system',lambda:'Linux')
    monkeypatch.setattr(inference.platform,'machine',lambda:'x86_64')
    monkeypatch.setattr(inference.ort,'get_available_providers',lambda:['CUDAExecutionProvider','CPUExecutionProvider'])
    assert inference.pad_policy()['selected']=='cuda'
    monkeypatch.setenv('MOCK_ID_PAD_PROVIDER','auto')
    assert inference.pad_policy()['runtime']=='ONNX / CUDA + CPU'
    monkeypatch.setattr(inference.platform,'system',lambda:'Darwin')
    monkeypatch.setattr(inference.platform,'machine',lambda:'arm64')
    assert inference.pad_policy()['selected']=='cpu'


def test_cuda_constructor_failure_is_reported_as_cpu(monkeypatch):
    monkeypatch.setenv('MOCK_ID_PAD_PROVIDER','cuda')
    monkeypatch.setattr(inference.platform,'system',lambda:'Linux')
    monkeypatch.setattr(inference.ort,'get_available_providers',lambda:['CUDAExecutionProvider','CPUExecutionProvider'])
    calls=[]
    class CPU:
        def get_providers(self):return ['CPUExecutionProvider']
        def run(self,*_):return [np.array([1.])]
    def factory(*_args,providers,**_kwargs):
        calls.append(providers)
        if isinstance(providers[0],tuple):raise RuntimeError('No CUDA driver fixture')
        return CPU()
    monkeypatch.setattr(inference.ort,'InferenceSession',factory)
    session=inference.PadSession('fixture.onnx',None)
    assert session.status['selected']=='cpu' and 'CUDA' in session.status['fallback_reason']
    assert calls[0][0][0]=='CUDAExecutionProvider'


@pytest.mark.skipif('CUDAExecutionProvider' not in inference.ort.get_available_providers(),reason='NVIDIA CUDA runtime/hardware tidak tersedia pada Mac ini.')
def test_native_cuda_cpu_parity_when_available(monkeypatch,face_image):
    from app.services.antispoof import AntiSpoofService
    from app.services.face import FaceService
    face=FaceService().one(face_image)
    monkeypatch.setenv('MOCK_ID_PAD_PROVIDER','cpu');cpu=AntiSpoofService().score(face_image,face)
    monkeypatch.setenv('MOCK_ID_PAD_PROVIDER','cuda');gpu=AntiSpoofService().score(face_image,face)
    assert gpu['runtime_details']['selected']=='cuda'
    assert gpu['live_probability']==pytest.approx(cpu['live_probability'],abs=.001)
