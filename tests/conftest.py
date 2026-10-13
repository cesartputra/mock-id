import os
# Security/temporal regression tests use a reproducible CPU baseline.
os.environ["MOCK_ID_PAD_PROVIDER"] = "cpu"
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.model.repository import Repository
from app.services.pipeline import VerificationService

@pytest.fixture(scope='session')
def real_models(tmp_path_factory):
    service = VerificationService(Repository(tmp_path_factory.mktemp('models')))
    if not service.availability()['ready']:
        pytest.skip('Model belum diunduh; jalankan npm run setup untuk tes inference nyata.')
    service.load()
    return service

@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path)) as c:
        principal=c.app.state.auth.create_user('fixture-admin','test-password-12345','admin')
        token,_=c.app.state.auth.login('fixture-admin','test-password-12345')
        c.headers.update({'X-Local-Client': 'mock-id','Authorization':'Bearer '+token})
        c.fixture_actor=principal
        yield c

@pytest.fixture(scope='session')
def face_image():
    return cv2.imread(str(Path(__file__).parent/'fixtures'/'astronaut.png'))

@pytest.fixture(scope='session')
def ktp_image():
    image = np.full((540, 856, 3), (225, 215, 180), np.uint8)
    cv2.rectangle(image,(5,5),(850,534),(0,0,0),3)
    for i, text in enumerate(['KARTU UJI - BUKAN KTP', 'NIK: 1234567890123456', 'Nama: PEMOHON TEST', 'Lahir: 01-01-1990', 'Alamat: JALAN UJI']):
        cv2.putText(image,text,(35,85+i*80),cv2.FONT_HERSHEY_SIMPLEX,1.1,(0,0,0),2)
    return image


def encoded(image):
    return cv2.imencode('.jpg',image)[1].tobytes()


def complete_control_fixture():
    """Protocol fixture only: no claim of actual model/security accuracy."""
    from app.services.assessment import CONTROL_NAMES
    return [{'name': name, 'status': 'passed', 'mode': 'protocol fixture',
             'detail': {'fixture': True}} for name in CONTROL_NAMES]
