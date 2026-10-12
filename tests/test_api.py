import json
import time
import cv2
import numpy as np
import pytest
from fastapi import HTTPException
from app.services.sessions import SessionService
from app.services.dukcapil import DukcapilService
from app.config import SESSION_TTL
from conftest import encoded


def test_local_only(client):
    assert client.post('/api/sessions',headers={'X-Local-Client':''}).status_code==403
    assert client.post('/api/sessions',headers={'Origin':'https://other.example'}).status_code==403
    assert client.get('/api/health',headers={'Host':'other.example'}).status_code==400
    assert client.get('/').status_code==200
    assert client.get('/docs').status_code==200
    assert client.get('/static/app.js').status_code==200


def test_empty_persisted_workspace(client):
    workspace=client.get('/api/workspace').json()
    assert workspace['records']==[] and workspace['audit']==[]
    assert workspace['health']['inference']=='real'


def test_nonce_expiry_retry_limits():
    sessions=SessionService();s=sessions.create();s.document=np.zeros((80,80,3));original=s.nonce
    with pytest.raises(HTTPException): sessions.consume(s.id,'wrong')
    sessions.consume(s.id,s.nonce)
    with pytest.raises(HTTPException): sessions.consume(s.id,s.nonce)
    s.processing=False;s.last_result={'status':'capture'}
    sessions.retry(s.id);assert s.nonce!=original and s.attempt==2
    s.last_result={'status':'capture'};sessions.retry(s.id)
    with pytest.raises(HTTPException): sessions.retry(s.id)
    s.created=time.time()-SESSION_TTL-1;sessions.purge()
    assert s.id not in sessions.items
    with pytest.raises(HTTPException): sessions.get(s.id)


def test_actual_document_endpoint(client,real_models,ktp_image):
    # Reuse loaded real CPU models, keeping this client's database isolated.
    client.app.state.verifier.ocr=real_models.ocr
    s=client.post('/api/sessions').json()
    result=client.post(f'/api/sessions/{s["id"]}/document',files={'image':('test.jpg',encoded(ktp_image),'image/jpeg')})
    assert result.status_code==200,result.text
    assert result.json()['fields']['nik']=='1234567890123456'
    corrected=client.patch(f'/api/sessions/{s["id"]}/identity',json={'name':'USER UJI','birth':'1990-01-01','address':'JALAN UJI'})
    assert corrected.json()['nik']=='1234567890123456'
    # No raw NIK or capture persisted in audit/SQLite.
    assert '1234567890123456' not in json.dumps(client.get('/api/workspace').json())


def test_missing_document_and_invalid_file(client):
    s=client.post('/api/sessions').json()
    assert client.post(f'/api/sessions/{s["id"]}/document',files={'image':('bad.jpg',b'not an image','image/jpeg')}).status_code==422
    assert client.patch(f'/api/sessions/{s["id"]}/identity',json={'name':'USER UJI'}).status_code==409


def verify_payload(s,face_image,unique=False,reverse=False):
    order=list(reversed(s['challenges'])) if reverse else s['challenges']
    manifest=[{'challenge':c,'t_ms':(ci*8+i)*350} for ci,c in enumerate(order) for i in range(8)]
    parts=[('selfie',('selfie.jpg',encoded(face_image),'image/jpeg')),('holding',('held.jpg',encoded(face_image),'image/jpeg'))]
    for i in range(24):
        img=face_image.copy()
        if unique: cv2.putText(img,str(i),(10,500),cv2.FONT_HERSHEY_SIMPLEX,.7,(255,255,255),2)
        parts.append(('frames',(f'{i}.jpg',encoded(img),'image/jpeg')))
    return {'nonce':s['nonce'],'manifest':json.dumps(manifest)},parts


def test_replay_and_wrong_order(client,face_image):
    s=client.post('/api/sessions').json()
    data,files=verify_payload(s,face_image)
    r=client.post(f'/api/sessions/{s["id"]}/verify',data=data,files=files)
    assert r.status_code==422 and 'identik' in r.json()['detail']
    data,files=verify_payload(s,face_image,reverse=True)
    r=client.post(f'/api/sessions/{s["id"]}/verify',data=data,files=files)
    assert r.status_code==422 and 'Urutan' in r.json()['detail']


def test_actual_pipeline_does_not_fabricate_success(client,real_models,face_image):
    s=client.post('/api/sessions').json()
    session=client.app.state.sessions.get(s['id'])
    session.document=face_image
    session.document_result={'fields':{'nik':'1234567890123456','name':'TEST'},'confidence':.99,'engine':'test fixture metadata'}
    verifier=client.app.state.verifier
    verifier.face,verifier.pad,verifier.deepfake,verifier.landmarks,verifier.ocr=real_models.face,real_models.pad,real_models.deepfake,real_models.landmarks,real_models.ocr
    data,files=verify_payload(s,face_image,unique=True)
    # Protocol fixture binds this exact payload; the pipeline still performs
    # actual image inference and must reject the missing held card.
    import hashlib
    from app.controller.verification import manifest_digest
    session.liveness_result={'passed':True,'pad_probability':.9,'mode':'test protocol fixture'}
    session.liveness_hashes=[hashlib.sha256(part[1][1]).hexdigest() for part in files if part[0]=='frames']
    session.liveness_selfie=hashlib.sha256(files[0][1][1]).hexdigest()
    session.liveness_manifest=manifest_digest(json.loads(data['manifest']))
    verifier.visibility=real_models.visibility
    swapped=list(files)
    swapped[0]=('selfie',('other.jpg',encoded(np.flip(face_image,axis=1)),'image/jpeg'))
    changed=client.post(f'/api/sessions/{s["id"]}/verify',data=data,files=swapped)
    assert changed.status_code==409 and not session.consumed
    changed_data={**data,'manifest':json.dumps([{**m,'t_ms':m['t_ms']+1} for m in json.loads(data['manifest'])])}
    changed=client.post(f'/api/sessions/{s["id"]}/verify',data=changed_data,files=files)
    assert changed.status_code==409 and not session.consumed
    r=client.post(f'/api/sessions/{s["id"]}/verify',data=data,files=files)
    assert r.status_code==200,r.text
    result=r.json()
    assert result['status']=='capture' # No held card, so no invented scores/pass.
    assert result['scores']['face_cosine'] > .99
    assert result['retry']['stage']=='holding'
    assert result['checks'][-2]['stage']=='holding'
    assert result['identity_verified'] is False
    assert result['checks'][-1]['mode']=='mock'
    assert len(client.get('/api/workspace').json()['records'])==1
    assert client.post(f'/api/sessions/{s["id"]}/verify',data=data,files=files).status_code==409
    retry=client.post(f'/api/sessions/{s["id"]}/retry').json()
    assert retry['nonce']!=s['nonce'] and retry['attempt']==2


def test_settings_and_review_validation(client):
    assert client.put('/api/settings',json={'face_cosine':1.5,'pad_probability':.8,'deepfake_risk':.8,'blur_min':45}).status_code==422
    assert client.post('/api/records/unknown/review',json={'decision':'approved','note':'Test review'}).status_code==409
    assert DukcapilService().check({'nik':'1234567890123456'})['identity_verified'] is False


def test_swagger_header_scheme(client):
    spec=client.get('/openapi.json').json()
    assert spec['components']['securitySchemes']['APIKeyHeader']['name']=='X-Local-Client'


def test_manual_schedule_and_review_persist(client):
    from datetime import datetime,timedelta,timezone
    repo=client.app.state.repository
    fixture={'id':'TEST-MANUAL','created':datetime.now(timezone.utc).isoformat(),'status':'manual','identity_verified':False}
    repo.save_result(fixture)
    at=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()
    response=client.post('/api/records/TEST-MANUAL/schedule',json={'at':at})
    assert response.status_code==200 and response.json()['status']=='scheduled'
    response=client.post('/api/records/TEST-MANUAL/review',json={'decision':'approved','note':'Catatan unit test'})
    assert response.status_code==200 and response.json()['status']=='approved'
    assert response.json()['identity_verified'] is False
    assert client.post('/api/records/TEST-MANUAL/review',json={'decision':'rejected','note':'Ganti keputusan'}).status_code==409
    assert repo.result('TEST-MANUAL')['note']=='Catatan unit test'


def test_settings_persist_and_audit(client):
    rules={'face_cosine':.4,'pad_probability':.85,'deepfake_risk':.75,'blur_min':55}
    response=client.put('/api/settings',json=rules)
    assert response.status_code==200 and response.json()==rules
    ws=client.get('/api/workspace').json()
    assert ws['settings']==rules and ws['audit'][0]['type']=='Konfigurasi diperbarui'


def test_capture_check_real_and_no_nonce_consumption(client,real_models,monkeypatch):
    import cv2
    from pathlib import Path
    from types import SimpleNamespace
    # Throttle correctness is independent of model initialization/inference
    # duration, which can legitimately exceed its 500 ms interval.
    monkeypatch.setattr('app.controller.verification.time', SimpleNamespace(monotonic=lambda: 100.0))
    verifier=client.app.state.verifier
    verifier.face,verifier.landmarks,verifier.visibility=real_models.face,real_models.landmarks,real_models.visibility
    s=client.post('/api/sessions').json()
    image=cv2.imread(str(Path(__file__).parent/'fixtures'/'face_attributes'/'eyeglasses.jpg'))
    r=client.post(f'/api/sessions/{s["id"]}/capture-check',data={'context':'selfie'},files={'image':('frame.jpg',encoded(cv2.resize(image,(640,480))),'image/jpeg')})
    assert r.status_code==200,r.text
    assert not r.json()['ready']
    assert 'eyeglasses' in [w['code'] for w in r.json()['warnings']]
    session=client.app.state.sessions.get(s['id'])
    assert not session.consumed and session.nonce==s['nonce']
    r=client.post(f'/api/sessions/{s["id"]}/capture-check',files={'image':('frame.jpg',encoded(image),'image/jpeg')})
    assert r.status_code==429


def test_final_verify_requires_checked_liveness(client,face_image):
    s=client.post('/api/sessions').json();data,files=verify_payload(s,face_image,unique=True)
    r=client.post(f'/api/sessions/{s["id"]}/verify',data=data,files=files)
    assert r.status_code==422 and 'Liveness belum' in r.json()['detail']


def test_liveness_capture_tokens_and_real_static_rejection(client,real_models,face_image):
    verifier=client.app.state.verifier
    verifier.face,verifier.pad,verifier.deepfake,verifier.landmarks,verifier.ocr,verifier.visibility=real_models.face,real_models.pad,real_models.deepfake,real_models.landmarks,real_models.ocr,real_models.visibility
    s=client.post('/api/sessions').json()
    assert client.post(f'/api/sessions/{s["id"]}/liveness/start').status_code==422
    session=client.app.state.sessions.get(s['id']);session.document=face_image
    capture=client.post(f'/api/sessions/{s["id"]}/liveness/start').json()
    data,parts=verify_payload(capture,face_image,unique=True)
    data={'capture_nonce':capture['capture_nonce'],'manifest':data['manifest']}
    parts=[p for p in parts if p[0]!='holding']
    early=client.post(f'/api/sessions/{s["id"]}/liveness/check',data=data,files=parts)
    assert early.status_code==422 and 'durasi' in early.json()['detail']
    session.liveness_started-=10 # Simulate elapsed capture time, not model output.
    result=client.post(f'/api/sessions/{s["id"]}/liveness/check',data=data,files=parts)
    assert result.status_code==200,result.text
    assert not result.json()['passed'] and not session.liveness_hashes
    assert not session.consumed
    assert client.post(f'/api/sessions/{s["id"]}/liveness/check',data=data,files=parts).status_code==409
    second=client.post(f'/api/sessions/{s["id"]}/liveness/start').json()
    assert second['capture_nonce']!=capture['capture_nonce']
    client.post(f'/api/sessions/{s["id"]}/liveness/start')
    assert client.post(f'/api/sessions/{s["id"]}/liveness/start').status_code==429
