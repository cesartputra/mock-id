import cv2
import json
import numpy as np
import pytest
from pathlib import Path
from app.services.imaging import CaptureError, decode_image, card_region
from app.services.ocr import parse_identity
from app.services.assets import verify_assets
from conftest import encoded


def test_parser_never_invents_identity():
    assert parse_identity(['gambar kosong'])['nik'] == ''
    assert parse_identity(['NIK: 1234567890123456', 'Nama', 'USER UJI', '01-01-1990']) == {'nik':'1234567890123456','name':'USER UJI','birth':'1990-01-01','address':''}


def test_reject_invalid_image():
    with pytest.raises(CaptureError):
        decode_image(b'not an image')
    with pytest.raises(CaptureError):
        decode_image(encoded(np.zeros((20,20,3),np.uint8)))


def test_real_assets(real_models):
    assert verify_assets() == []
    assert real_models.availability()['loaded']


def test_actual_ocr(real_models, ktp_image):
    result=real_models.ocr.read(ktp_image)
    assert result['fields']['nik']=='1234567890123456'
    assert result['confidence'] > .8
    assert result['mode']=='real'
    assert real_models.ocr.read(np.full((300,400,3),255,np.uint8))['fields']['nik']==''


def test_actual_face_matching(real_models, face_image):
    face=real_models.face.one(face_image)
    assert real_models.face.compare(face_image,face,face_image,face) > .99
    reflected=cv2.flip(face_image,1)
    other=real_models.face.one(reflected)
    assert real_models.face.compare(face_image,face,reflected,other) > .363
    with pytest.raises(CaptureError):
        real_models.face.one(np.zeros_like(face_image))


def test_actual_pad_and_deepfake(real_models,face_image):
    face=real_models.face.one(face_image)
    pad=real_models.pad.score(face_image,face)
    altered=real_models.pad.score(cv2.GaussianBlur(face_image,(25,25),0),face)
    assert 0 <= pad['live_probability'] <= 1
    assert abs(sum(pad['class_probabilities'])-1)<1e-6
    assert altered['live_probability'] != pad['live_probability']
    crop=real_models.face.feature(face_image,face)[1]
    fake=real_models.deepfake.score(crop)
    assert 0 <= fake['fake_probability'] <= 1
    assert abs(fake['fake_probability']+fake['real_probability']-1)<1e-4


def test_static_face_fails_actual_challenges(real_models,face_image):
    order=['blink','turn','smile']
    manifest=[{'challenge':c,'t_ms':i*350} for c in order for i in range(8)]
    result=real_models.landmarks.challenges([face_image]*24,manifest,order)
    assert not result['passed']
    assert all(not c['passed'] for c in result['challenges'])


def test_actual_hands(real_models,face_image):
    absent=real_models.landmarks.hand_near_card(face_image,[0,0,512,512])
    assert absent['hands_detected']==0 and not absent['passed']
    image=cv2.imread(str(Path(__file__).parent/'fixtures'/'hands.png'))
    detected=real_models.landmarks.hand_near_card(image,[0,0,image.shape[1],image.shape[0]])
    assert detected['hands_detected']>0 and detected['passed']
    assert type(detected['passed']) is bool
    assert json.loads(json.dumps(detected)) == detected
    assert json.loads(json.dumps(absent)) == absent


def test_card_geometry(ktp_image):
    image=np.full((900,1300,3),80,np.uint8)
    image[180:720,200:1056]=ktp_image
    candidates=card_region(image)
    assert candidates[0][1].shape == (540,856,3)
    with pytest.raises(CaptureError):
        card_region(np.zeros_like(image))


def test_nik_with_spaces_is_not_guessed():
    assert parse_identity(['NIK: 1234 5678 9012 3456'])['nik']=='1234567890123456'
    assert parse_identity(['NIK: 123456789012345O'])['nik']==''
    assert parse_identity(['12345678','90123456'])['nik']==''


@pytest.mark.parametrize('name,code',[('eyeglasses','eyeglasses'),('mask','mask'),('sunglasses','sunglasses')])
def test_actual_visibility_attributes(real_models,name,code):
    image=cv2.imread(str(Path(__file__).parent/'fixtures'/'face_attributes'/f'{name}.jpg'))
    result=real_models.visibility.inspect(image)
    assert not result['ready']
    assert code in [w['code'] for w in result['warnings']]
    assert result['attributes'][code]>.6


def test_clear_face_visibility_and_preview_pad(real_models,face_image):
    result=real_models.visibility.inspect(face_image)
    assert result['ready']
    blank=real_models.visibility.inspect(np.zeros_like(face_image))
    assert not blank['ready'] and blank['warnings'][0]['code']=='face_missing'
    checked=real_models.inspect_capture(face_image)
    assert checked['pad']['mode']=='real'
    assert 0<=checked['pad']['live_probability']<=1


def test_small_rotated_partly_covered_card(real_models,ktp_image):
    from app.services.card import HoldingCardService
    image=np.full((1280,1920,3),120,np.uint8)
    # 2.3% of the scene, below the old mandatory 2.5% threshold. Fingers
    # break the rectangular border, but the actual text remains readable.
    small=cv2.resize(ktp_image,(300,190))
    image[510:700,710:1010]=small
    cv2.rectangle(image,(707,580),(740,638),(100,130,175),-1)
    transform=cv2.getRotationMatrix2D((860,605),-12,1)
    image=cv2.warpAffine(image,transform,(1920,1280),borderValue=(120,120,120))
    card=HoldingCardService(real_models.ocr).read(image,reference=ktp_image,expected_nik='1234567890123456')
    assert card['reading']['fields']['nik']=='1234567890123456'
    assert card['box'][2]<700


def test_card_fallback_cannot_invent_nik(real_models,ktp_image):
    from app.services.card import HoldingCardService
    with pytest.raises(CaptureError):
        HoldingCardService(real_models.ocr).read(np.full((500,800,3),120,np.uint8),reference=ktp_image,expected_nik='1234567890123456')


def test_real_liveness_rejects_moving_photo(real_models,face_image):
    from app.model.entities import CaptureSession
    s=CaptureSession();s.challenges=['blink','turn','smile']
    # Moving a flat photograph changes pixel hashes but not facial expression.
    frames=[];manifest=[]
    for group,c in enumerate(s.challenges):
        for i in range(8):
            affine=np.float32([[1,0,i%3],[0,1,i%2]])
            frame=cv2.warpAffine(face_image,affine,(512,512),borderMode=cv2.BORDER_REFLECT)
            frames.append(frame);manifest.append({'challenge':c,'t_ms':(group*8+i)*350})
    result=real_models.evaluate_liveness(s,face_image,frames,manifest)
    assert not result['passed']
    assert not result['live']['passed']
