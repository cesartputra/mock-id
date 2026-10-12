"""JSON transport/persistence regression tests using public images only."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import cv2
import pytest

from app.services.card import HoldingCardService
from conftest import encoded
from test_liveness_stream import attach_models, seed_proof, seed_session


def verification_request(client, face_image):
    public, session = seed_session(client, face_image)
    seed_proof(session)  # Protocol fixture; not proof of a real passing capture.
    blob = encoded(face_image)
    session.liveness_selfie = hashlib.sha256(blob).hexdigest()
    route = f'/api/sessions/{session.id}/verify'
    files = {'selfie': ('self.jpg', blob, 'image/jpeg'),
             'holding': ('held.jpg', blob, 'image/jpeg')}
    data = {'nonce': public['nonce'], 'proof_token': session.liveness_proof}
    return session, route, files, data


def test_actual_hand_metrics_survive_full_pipeline_json_and_sqlite(client, real_models, face_image, monkeypatch):
    attach_models(client, real_models)
    session, route, files, data = verification_request(client, face_image)
    session.liveness_result.update(live={'passed': True, 'mode': 'protocol fixture'}, continuity=[.99])
    image = cv2.imread(str(Path(__file__).parent / 'fixtures' / 'hands.png'))
    hand = real_models.landmarks.hand_near_card(image, [0, 0, image.shape[1], image.shape[0]])
    assert hand['passed'] and hand['hands_detected'] > 0
    # Isolate transport from card/OCR accuracy. Face, PAD, visibility, deepfake,
    # and hand metrics come from real models; only card evidence is a fixture.
    monkeypatch.setattr(HoldingCardService, 'read', lambda *_args, **_kwargs: {
        'reading': {'fields': {'nik': '1234567890123456'}, 'confidence': .9},
        'box': [0, 0, 100, 60], 'method': 'serialization fixture'})
    client.app.state.verifier.landmarks = SimpleNamespace(hand_near_card=lambda *_: hand)
    response = client.post(route, data=data, files=files)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['status'] != 'technical'
    check = next(c for c in result['checks'] if c['name'] == 'Tangan dekat KTP')
    assert check['detail']['passed'] is True
    assert 'deepfake' in result['scores']
    assert client.app.state.repository.result(result['id']) == result
    assert json.loads(json.dumps(session.last_result)) == result


@pytest.mark.parametrize('failure_method', ['save_result', 'audit'])
def test_verification_storage_failure_is_json_and_retry_keeps_captures(client, real_models, face_image, monkeypatch, failure_method):
    attach_models(client, real_models)
    session, route, files, data = verification_request(client, face_image)
    document, proof = session.document, session.liveness_result
    repository = client.app.state.repository
    original = getattr(repository, failure_method)
    def unavailable(*_args):
        raise OSError('private storage diagnostic')
    monkeypatch.setattr(repository, failure_method, unavailable)
    response = client.post(route, data=data, files=files)
    assert response.status_code == 503
    assert response.headers['content-type'].startswith('application/json')
    body = response.json()
    assert body['retry']['stage'] == 'verify' and body['request_id']
    assert 'private storage diagnostic' not in response.text
    assert session.consumed and not session.processing
    assert client.post(route, data=data, files=files).status_code == 409
    if failure_method == 'audit':
        before = vars(session).copy()
        assert client.post(f'/api/sessions/{session.id}/retry').status_code == 500
        assert session.public()['nonce'] == before['nonce']
        assert session.revision == before['revision'] and session.attempt == before['attempt']
        assert session.last_result is before['last_result'] and session.liveness_result is proof
    monkeypatch.setattr(repository, failure_method, original)
    updated = client.post(f'/api/sessions/{session.id}/retry').json()
    assert updated['retry']['stage'] == 'verify'
    assert updated['nonce'] != data['nonce'] and updated['attempt'] == 2
    assert session.document is document and session.liveness_result is proof
    assert session.liveness_proof == data['proof_token']
    # Same validated selfie and held image can be resubmitted after recovery.
    response = client.post(route, data={**data, 'nonce': updated['nonce']}, files=files)
    assert response.status_code == 200 and response.json()['status'] == 'capture'


def test_unexpected_api_error_has_safe_json_and_log_reference(client, monkeypatch, caplog):
    def fail():
        raise RuntimeError('private diagnostic must not reach browser')
    monkeypatch.setattr(client.app.state.repository, 'results', fail)
    response = client.get('/api/workspace')
    assert response.status_code == 500
    assert response.headers['cache-control'] == 'no-store'
    body = response.json()
    assert body['code'] == 'internal_error'
    assert body['request_id'] in caplog.text
    assert 'private diagnostic' not in response.text


def test_retake_audit_failure_preserves_nonce_and_capture_before_retry(client, face_image, monkeypatch):
    session, _route, _files, _data = verification_request(client, face_image)
    before = vars(session).copy()
    original = client.app.state.repository.audit
    def fail(*_args):
        raise OSError('Controlled audit failure')
    monkeypatch.setattr(client.app.state.repository, 'audit', fail)
    route = f'/api/sessions/{session.id}/retake'
    data = {'stage': 'document', 'nonce': session.nonce}
    assert client.post(route, json=data).status_code == 500
    assert session.document is before['document'] and session.document_result is before['document_result']
    assert session.liveness_result is before['liveness_result']
    assert session.nonce == before['nonce'] and session.revision == before['revision']
    monkeypatch.setattr(client.app.state.repository, 'audit', original)
    assert client.post(route, json=data).status_code == 200
    assert session.document is None and session.document_result is None
    assert session.liveness_result is before['liveness_result']
