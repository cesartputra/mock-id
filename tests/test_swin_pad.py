"""CVPR checkpoint contract and authenticated model-distribution boundaries."""
import json
from types import SimpleNamespace
import urllib.request

import numpy as np
import pytest
from app.services.antispoof import AntiSpoofService, PAD_FILE, PAD_MODEL, face_tensor, softmax
from app.services.imaging import CaptureError
from scripts.setup_models import model_request, SecureRedirect


def test_swin_tensor_is_rgb_imagenet_and_has_fixed_batch_shape():
    image=np.full((100,100,3),(0,128,255),np.uint8) # BGR
    tensor=face_tensor(image,[20,20,60,60])
    assert tensor.shape==(1,3,224,224) and tensor.dtype==np.float32 and tensor.flags.c_contiguous
    expected=(np.array([255,128,0])/255-np.array([.485,.456,.406]))/np.array([.229,.224,.225])
    np.testing.assert_allclose(tensor[0,:,100,100],expected,rtol=1e-6)
    # Margin includes background around the face, following face-area inference.
    image[:20]=255
    assert face_tensor(image,[20,20,60,60])[0,0,0,0] > 2
    for box in [[0,0,0,60],[200,200,60,60],[0,0,float('nan'),60]]:
        with pytest.raises(CaptureError):face_tensor(image,box)


def test_swin_labels_cannot_inherit_minifas_live_index(monkeypatch):
    class Session:
        def get_inputs(self):return [SimpleNamespace(name='face_rgb',shape=[1,3,224,224])]
        def get_outputs(self):return [SimpleNamespace(shape=[1,2])]
        def run(self, *_args):return [np.array([[5.,-5.]],np.float32)]
    monkeypatch.setattr('app.services.antispoof.ort.InferenceSession',lambda *_args,**_kwargs:Session())
    result=AntiSpoofService().score(np.zeros((100,100,3),np.uint8),[20,20,60,60])
    assert result['live_probability'] > .99 and result['spoof_probability'] < .01
    assert result['class_labels']==['live','spoof'] and result['model']==PAD_MODEL
    json.dumps(result)
    with pytest.raises(ValueError):softmax([float('nan'),1])


def test_real_swin_model_uses_official_class_zero_and_cpu(real_models,face_image):
    face=real_models.face.one(face_image)
    service=real_models.pad
    assert service.model.get_providers()==['CPUExecutionProvider']
    logits=service.model.run(None,{service.input:face_tensor(face_image,face)})[0]
    probabilities=softmax(logits)
    result=service.score(face_image,face)
    assert result['live_probability']==round(float(probabilities[0]),5)
    assert result['spoof_probability']==round(float(probabilities[1]),5)
    assert result['model']==PAD_MODEL and result['checkpoint']=='face_swin_v2_base.pth'
    assert real_models.availability()['files'][PAD_FILE]


def test_github_model_credential_is_not_forwarded_to_asset_cdn(monkeypatch):
    monkeypatch.setattr('scripts.setup_models.subprocess.run',lambda *_args,**_kwargs:SimpleNamespace(returncode=0,stdout='username=test\npassword=test-token\n'))
    request=model_request({'url':'https://api.github.com/repos/cesartputra/mock-id/releases/assets/123','github_asset':True})
    assert request.get_header('Authorization')=='Bearer test-token'
    redirected=SecureRedirect().redirect_request(request,None,302,'Found',{},'https://release-assets.githubusercontent.com/model.onnx')
    assert redirected.get_header('Authorization') is None
    with pytest.raises(RuntimeError):
        SecureRedirect().redirect_request(request,None,302,'Found',{},'http://example.com/model.onnx')
    with pytest.raises(RuntimeError):
        model_request({'url':'https://example.com/model.onnx','github_asset':True})


def test_missing_github_credentials_gives_actionable_setup_error(monkeypatch):
    monkeypatch.setattr('scripts.setup_models.subprocess.run',lambda *_args,**_kwargs:SimpleNamespace(returncode=1,stdout=''))
    with pytest.raises(RuntimeError,match='repo private'):
        model_request({'url':'https://api.github.com/repos/cesartputra/mock-id/releases/assets/123','github_asset':True})
    assert model_request({'url':'https://example.com/model.onnx'}).get_header('Authorization') is None
