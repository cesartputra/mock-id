import cv2
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


def test_card_geometry(ktp_image):
    image=np.full((900,1300,3),80,np.uint8)
    image[180:720,200:1056]=ktp_image
    candidates=card_region(image)
    assert candidates[0][1].shape == (540,856,3)
    with pytest.raises(CaptureError):
        card_region(np.zeros_like(image))
