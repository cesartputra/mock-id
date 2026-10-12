import threading
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor

import cv2
import pytest
from app.services.pipeline import ModelUnavailable
from conftest import encoded


def card_with_portrait(ktp_image, face_image):
    image=ktp_image.copy()
    portrait=cv2.resize(face_image[40:240,155:340],(135,160))
    image[235:395,695:830]=portrait
    return image


def test_actual_auto_document_requires_readable_nik_and_portrait(real_models, ktp_image, face_image):
    reading=real_models.inspect_auto_capture(card_with_portrait(ktp_image,face_image),'document')
    assert reading['ready'] and not reading['complete'],reading
    assert reading['_document_reading']['fields']['birth']=='1990-01-01'
    assert reading['nik_readable'] and reading['subject_key']
    assert not real_models.inspect_auto_capture(ktp_image,'document')['complete'] # no portrait
    assert not real_models.inspect_auto_capture(face_image,'document')['complete'] # no NIK


def test_actual_held_photo_without_readable_nik_never_auto_captures(real_models,face_image):
    # Full photo inference is real; astronaut fixture is not a held KTP scene.
    result=real_models.inspect_auto_capture(face_image,'holding',face_image,{'nik':'1234567890123456'})
    assert not result['ready'] and not result['complete'] and result['warnings']


def test_auto_endpoint_checks_prerequisites_and_does_not_consume_session(client,real_models,ktp_image,face_image,monkeypatch):
    # Test the throttle interval independently of CPU/OCR duration, which may
    # legitimately exceed 500 ms on a loaded machine.
    clock=[100.]
    monkeypatch.setattr('app.controller.verification.time', SimpleNamespace(monotonic=lambda: clock[0]))
    verifier=client.app.state.verifier
    verifier.ocr=real_models.ocr;verifier.face=real_models.face
    public=client.post('/api/sessions').json();sid=public['id']
    route=f'/api/sessions/{sid}/auto-capture/check'
    file={'image':('camera.jpg',encoded(card_with_portrait(ktp_image,face_image)),'image/jpeg')}
    assert client.post(route,data={'context':'holding'},files=file).status_code==422
    assert client.post(route,data={'context':'unknown'},files=file).status_code==422
    result=client.post(route,data={'context':'document'},files=file)
    assert result.status_code==200 and not result.json()['complete'],result.text
    session=client.app.state.sessions.get(sid)
    assert session.document is None and not session.consumed and session.nonce==public['nonce']
    assert 'image_size' in result.json() and client.app.state.repository.results()==[]
    assert client.post(route,data={'context':'document'},files=file).status_code==429
    for n in [1,2]:
        clock[0]+=1.
        image=card_with_portrait(ktp_image,face_image)
        cv2.circle(image,(840,520),2,(n*50,30,30),-1)
        file={'image':('camera.jpg',encoded(image),'image/jpeg')}
        result=client.post(route,data={'context':'document'},files=file)
        assert result.status_code==200,result.text
    assert result.json()['complete'],result.text
    token=result.json()['document_capture_token']
    assert client.post(f'/api/sessions/{sid}/document',data={'capture_token':token},files=file).status_code==200
    assert session.document_result['fields']['nik']=='1234567890123456'


def test_old_auto_response_rejected_after_capture_reset(client,face_image,monkeypatch):
    public=client.post('/api/sessions').json();sid=public['id']
    entered,release=threading.Event(),threading.Event()
    def delayed(*args):
        entered.set();assert release.wait(5)
        return {'ready':True,'complete':True,'context':'document'}
    monkeypatch.setattr(client.app.state.verifier,'inspect_auto_capture',delayed)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future=pool.submit(client.post,f'/api/sessions/{sid}/auto-capture/check',data={'context':'document'},files={'image':('frame.jpg',encoded(face_image),'image/jpeg')},headers={'X-Capture-Revision':'0'})
        assert entered.wait(5)
        try:
            reset=client.post(f'/api/sessions/{sid}/retake',json={'stage':'document','nonce':public['nonce']})
            assert reset.status_code==200
        finally:release.set()
        assert future.result(timeout=5).status_code==409
    assert client.app.state.sessions.get(sid).document is None


@pytest.mark.parametrize('failure', ['nik','hand','face','none'])
def test_held_capture_gate_rejects_each_missing_requirement(client,face_image,monkeypatch,failure):
    from app.services.card import HoldingCardService
    from types import SimpleNamespace
    # These protocol stubs isolate conjunction of requirements; real OCR, face,
    # PAD/visibility and hand inference have separate actual-model tests.
    verifier=client.app.state.verifier
    monkeypatch.setattr(verifier,'inspect_capture',lambda *_args,**_kwargs:{'ready':True,'warnings':[]})
    monkeypatch.setattr(HoldingCardService,'read',lambda *_args,**_kwargs:{'reading':{'fields':{'nik':'0000000000000000' if failure=='nik' else '1234567890123456'}},'box':[10,10,200,125]})
    verifier.landmarks=SimpleNamespace(hand_near_card=lambda *_args:{'passed':failure!='hand'})
    verifier.face=SimpleNamespace(one=lambda *_args,**_kwargs:None,compare=lambda *_args:0 if failure=='face' else .9)
    result=verifier.inspect_auto_capture(face_image,'holding',face_image,{'nik':'1234567890123456'})
    if failure == 'none':
        assert result['complete'] and result['ready'] and result['subject_key']
        return
    assert not result['complete'] and not result['ready']
    assert result['warnings'][0]['code']=={'nik':'card_mismatch','hand':'hand_missing','face':'face_mismatch'}[failure]
