"""Regression coverage: capture generations and real streaming inference.

Synthetic landmark sequences test temporal rules, not face-model accuracy.
The camera API's negative cases use actual ONNX models/public images.
"""
import hashlib
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import cv2
import pytest

from app.services.liveness import GestureTracker, LiveCapture
from conftest import encoded


def metrics(blink=.30, smile=.65, yaw=0):
    return {'blink': blink, 'smile': smile, 'yaw': yaw}


def neutral(tracker):
    for _ in range(3):
        tracker.update(metrics())


def test_gestures_finish_on_evidence_without_fixed_duration():
    tracker = GestureTracker(['blink', 'turn', 'smile'], turn_direction=1)
    neutral(tracker)
    tracker.update(metrics(blink=.13))
    assert not tracker.completed # Closed eyes alone do not pass.
    tracker.update(metrics())
    assert not tracker.completed # Require two open samples after closure.
    tracker.update(metrics())
    assert [x['challenge'] for x in tracker.completed] == ['blink']
    neutral(tracker)
    for _ in range(2):
        tracker.update(metrics(yaw=-.18))
    assert len(tracker.completed) == 1 # Wrong direction is not accepted.
    for _ in range(2):
        tracker.update(metrics(yaw=.18))
    assert len(tracker.completed) == 2
    # A held smile cannot establish the next neutral baseline.
    for _ in range(8):
        tracker.update(metrics(smile=.78))
    assert tracker.baseline is None
    neutral(tracker)
    tracker.update(metrics(smile=.78))
    result = tracker.update(metrics(smile=.78))
    assert result['passed'] and result['phase'] == 'complete'
    assert len(result['completed']) == 3


def test_static_metrics_and_interrupted_blink_do_not_pass():
    tracker = GestureTracker(['blink', 'smile', 'turn'], turn_direction=1)
    for _ in range(80):
        tracker.update(metrics())
    assert not tracker.public()['passed'] and not tracker.completed
    tracker.update(metrics(blink=.12))
    tracker.reset_action() # Occlusion/disconnection invalidates pending closure.
    neutral(tracker)
    for _ in range(3):
        tracker.update(metrics())
    assert not tracker.completed


def test_stream_limits_replay_order_and_gap():
    capture = LiveCapture(['turn', 'smile', 'blink'])
    now = time.monotonic()
    assert capture.accept('a', 0, now) is None
    assert 'identik' in capture.accept('a', 1, now+.2)
    assert capture.sequence == 1
    assert 'Urutan' in capture.accept('b', 2, now+.4)
    assert 'cepat' in capture.accept('b', 1, now+.01)
    neutral(capture.gestures)
    assert capture.gestures.baseline
    assert capture.accept('b', 1, now+4) is None
    assert capture.gestures.baseline is None
    assert 'Waktu' in capture.accept('c', 2, now+91)


def seed_session(client, face_image):
    public = client.post('/api/sessions').json()
    session = client.app.state.sessions.get(public['id'])
    session.document = face_image.copy()
    session.document_result = {'fields': {'nik': '1234567890123456', 'name': 'TEST'}, 'confidence': .9, 'engine': 'protocol fixture'}
    return public, session


def seed_proof(session):
    # Explicit protocol fixture, never used to claim that a face model passed.
    session.liveness_result = {'passed': True, 'stream': True, 'pad_probability': .91}
    session.liveness_proof = 'test-proof-token'
    session.liveness_selfie = 'test-selfie-hash'
    session.liveness_manifest = 'test-manifest'
    session.liveness_hashes = ['old-frame']


@pytest.mark.parametrize('stage', ['document', 'liveness', 'holding'])
def test_retake_consumed_session_flushes_dependents_and_keeps_audit(client, face_image, stage):
    public, session = seed_session(client, face_image)
    seed_proof(session)
    session.consumed = True
    session.last_result = {'id': 'TEST-RESULT', 'status': 'capture', 'created': '2026-10-12T00:00:00Z'}
    client.app.state.repository.save_result(session.last_result)
    session.last_preview = time.monotonic()
    response = client.post(f'/api/sessions/{session.id}/retake', json={'stage': stage, 'nonce': public['nonce']}, headers={'X-Capture-Revision': '0'})
    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated['id'] == public['id'] and updated['nonce'] != public['nonce']
    assert updated['revision'] == 1 and updated['attempt'] == 2
    assert not session.consumed and not session.last_result and session.last_preview == 0
    if stage in ['holding', 'document']:
        assert session.liveness_proof == 'test-proof-token'
        assert (session.document is None) == (stage == 'document')
    else:
        assert session.liveness_result is None and session.liveness_proof is None
        assert session.liveness_manifest is None and session.liveness_selfie is None
        assert session.liveness_hashes == [] and session.liveness_nonce is None
        assert session.stream_state is None
        assert (session.document is None) == (stage == 'document')
    assert client.app.state.repository.result('TEST-RESULT')['status'] == 'capture'
    # Old requests cannot restore data nor consume the fresh nonce.
    stale = client.post(f'/api/sessions/{session.id}/capture-check', files={'image': ('frame.jpg', encoded(face_image), 'image/jpeg')}, headers={'X-Capture-Revision': '0'})
    assert stale.status_code == 409 and not session.consumed
    assert client.post(f'/api/sessions/{session.id}/retake', json={'stage': stage, 'nonce': public['nonce']}).status_code == 409


def test_actual_ocr_can_be_retaken_in_same_session(client, real_models, ktp_image):
    client.app.state.verifier.ocr = real_models.ocr
    public = client.post('/api/sessions').json()
    for revision in range(2):
        if revision:
            public = client.post(f'/api/sessions/{public["id"]}/retake', json={'stage': 'document', 'nonce': public['nonce']}).json()
        result = client.post(f'/api/sessions/{public["id"]}/document', files={'image': ('card.jpg', encoded(ktp_image), 'image/jpeg')}, headers={'X-Capture-Revision': str(revision)})
        assert result.status_code == 200 and result.json()['fields']['nik'] == '1234567890123456'
        session = client.app.state.sessions.get(public['id'])
        session.consumed = True
        session.last_result = {'status': 'capture'}


def test_inflight_ocr_cannot_repopulate_reset_session(client, face_image, monkeypatch):
    public, session = seed_session(client, face_image)
    entered, finish = threading.Event(), threading.Event()
    def slow_document(image):
        entered.set()
        assert finish.wait(5)
        return {'fields': {'nik': '1234567890123456'}, 'confidence': .9}
    # Delayed service isolates async generation handling, not OCR accuracy.
    monkeypatch.setattr(client.app.state.verifier, 'document', slow_document)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(client.post, f'/api/sessions/{session.id}/document', files={'image': ('card.jpg', encoded(face_image), 'image/jpeg')}, headers={'X-Capture-Revision': '0'})
        assert entered.wait(5)
        try:
            reset = client.post(f'/api/sessions/{session.id}/retake', json={'stage': 'document', 'nonce': public['nonce']})
            assert reset.status_code == 200
        finally:
            finish.set()
        assert pending.result(timeout=5).status_code == 409
    assert session.document is None and session.document_result is None


def attach_models(client, real_models):
    verifier = client.app.state.verifier
    for name in ['face', 'pad', 'landmarks', 'visibility', 'deepfake', 'ocr']:
        setattr(verifier, name, getattr(real_models, name))


def test_stream_api_rejects_replay_and_invalidated_token(client, real_models, face_image):
    attach_models(client, real_models)
    public, session = seed_session(client, face_image)
    capture = client.post(f'/api/sessions/{session.id}/liveness/start').json()
    image = encoded(face_image)
    first = client.post(f'/api/sessions/{session.id}/liveness/frame', data={'capture_nonce': capture['capture_nonce'], 'seq': 0}, files={'image': ('frame.jpg', image, 'image/jpeg')})
    assert first.status_code == 200, first.text
    assert not first.json()['passed'] and first.json()['feedback']['face_box']
    session.stream_state.last_frame -= .2
    repeated = client.post(f'/api/sessions/{session.id}/liveness/frame', data={'capture_nonce': capture['capture_nonce'], 'seq': 1}, files={'image': ('frame.jpg', image, 'image/jpeg')})
    assert repeated.status_code == 422 and 'identik' in repeated.json()['detail']
    reset = client.post(f'/api/sessions/{session.id}/retake', json={'stage': 'liveness', 'nonce': public['nonce']})
    assert reset.status_code == 200 and session.liveness_proof is None
    old = client.post(f'/api/sessions/{session.id}/liveness/frame', data={'capture_nonce': capture['capture_nonce'], 'seq': 1}, files={'image': ('frame.jpg', image, 'image/jpeg')})
    assert old.status_code == 409
    assert client.post(f'/api/sessions/{session.id}/liveness/start').status_code == 200


def test_actual_stream_moving_flat_photo_never_completes(real_models, face_image):
    capture = LiveCapture(['blink', 'smile', 'turn'])
    for seq in range(12):
        # A photo moving around the image is not a facial expression change.
        shift = (seq % 5)-2
        frame = cv2.warpAffine(face_image, __import__('numpy').float32([[1, 0, shift*3], [0, 1, -shift*2]]), (512, 512))
        result = real_models.inspect_liveness_frame(capture, frame, hashlib.sha256(encoded(frame)).hexdigest(), seq)
        assert not result['passed']
    assert not capture.gestures.completed


def test_stream_final_verification_binds_proof_and_selfie(client, real_models, face_image):
    attach_models(client, real_models)
    public, session = seed_session(client, face_image)
    seed_proof(session)
    blob = encoded(face_image)
    session.liveness_selfie = hashlib.sha256(blob).hexdigest()
    files = {'selfie': ('self.jpg', blob, 'image/jpeg'), 'holding': ('held.jpg', blob, 'image/jpeg')}
    route = f'/api/sessions/{session.id}/verify'
    assert client.post(route, data={'nonce': public['nonce'], 'proof_token': 'wrong-proof'}, files=files).status_code == 409
    changed = {**files, 'selfie': ('other.jpg', encoded(cv2.flip(face_image, 1)), 'image/jpeg')}
    assert client.post(route, data={'nonce': public['nonce'], 'proof_token': session.liveness_proof}, files=changed).status_code == 409
    result = client.post(route, data={'nonce': public['nonce'], 'proof_token': session.liveness_proof}, files=files)
    assert result.status_code == 200 and result.json()['status'] == 'capture' # No held card.
    updated = client.post(f'/api/sessions/{session.id}/retake', json={'stage': 'holding', 'nonce': public['nonce']}).json()
    assert updated['id'] == public['id'] and session.liveness_proof == 'test-proof-token'
    assert client.post(route, data={'nonce': public['nonce'], 'proof_token': session.liveness_proof}, files=files).status_code == 409
    assert not session.consumed
    assert client.post(route, data={'nonce': updated['nonce'], 'proof_token': session.liveness_proof}, files=files).status_code == 200


def test_reset_does_not_interrupt_processing_or_bypass_attempt_budget(client, face_image):
    public, session = seed_session(client, face_image)
    session.liveness_processing = True
    assert client.post(f'/api/sessions/{session.id}/retake', json={'stage': 'liveness', 'nonce': public['nonce']}).status_code == 409
    session.liveness_processing = False
    session.consumed = True
    session.attempt = 3
    assert client.post(f'/api/sessions/{session.id}/retake', json={'stage': 'document', 'nonce': public['nonce']}).status_code == 429


def test_stream_issues_proof_only_at_completion_and_binds_first_neutral_frame(client, face_image, monkeypatch):
    public, session = seed_session(client, face_image)
    capture_info = client.post(f'/api/sessions/{session.id}/liveness/start').json()
    tracker = session.stream_state.gestures
    tracker.challenges = ['blink', 'smile', 'turn']
    tracker.turn_direction = 1
    samples = ([metrics()]*3 + [metrics(blink=.12)] + [metrics()]*2
               + [metrics()]*3 + [metrics(smile=.78)]*2
               + [metrics()]*3 + [metrics(yaw=.18)]*2)
    def temporal_fixture(capture, image, digest, seq):
        if capture.selfie_hash is None:
            capture.selfie_hash = digest
            capture.selfie_seq = seq
        capture.pad_min = .95
        capture.cosine_min = .95
        capture.gestures.update(samples[seq])
        return capture.result({'ready': True, 'warnings': [], 'face_box': [10, 10, 90, 100]}, samples[seq])
    # Only the temporal/proof protocol is simulated here. Actual model negative
    # cases are tested above; this fixture is not an end-to-end live-face pass.
    monkeypatch.setattr(client.app.state.verifier, 'inspect_liveness_frame', temporal_fixture)
    route = f'/api/sessions/{session.id}/liveness/frame'
    first_hash = None
    for seq in range(len(samples)):
        image = face_image.copy()
        cv2.putText(image, str(seq), (10, 500), cv2.FONT_HERSHEY_SIMPLEX, .7, (255, 255, 255), 2)
        blob = encoded(image)
        if first_hash is None:
            first_hash = hashlib.sha256(blob).hexdigest()
        session.stream_state.last_frame = time.monotonic()-.2
        response = client.post(route, data={'capture_nonce': capture_info['capture_nonce'], 'seq': seq}, files={'image': ('frame.jpg', blob, 'image/jpeg')})
        assert response.status_code == 200, response.text
        result = response.json()
        if seq < len(samples)-1:
            assert not result['done'] and 'proof_token' not in result
            assert session.liveness_proof is None
        else:
            assert result['done'] and result['passed'] and result['proof_token'] == session.liveness_proof
            assert session.liveness_selfie == first_hash
            assert session.stream_state is None and session.liveness_nonce is None
    assert client.post(route, data={'capture_nonce': capture_info['capture_nonce'], 'seq': len(samples)}, files={'image': ('frame.jpg', blob, 'image/jpeg')}).status_code == 409


@pytest.mark.parametrize('stage', ['document', 'liveness', 'holding', 'verify'])
def test_automatic_retry_targets_failed_stage_and_retains_other_evidence(client, face_image, stage):
    public, session = seed_session(client, face_image)
    seed_proof(session)
    session.consumed = True
    session.last_result = {'status': 'technical' if stage == 'verify' else 'capture',
                           'retry': {'stage': stage, 'label': 'Ulangi tahap ini', 'reason': 'Unit regression'}}
    response = client.post(f'/api/sessions/{session.id}/retry')
    assert response.status_code == 200, response.text
    resumed = response.json()
    assert resumed['id'] == public['id'] and resumed['retry']['stage'] == stage
    assert resumed['nonce'] != public['nonce'] and resumed['attempt'] == 2
    assert not session.consumed and session.last_result is None
    assert (session.document is None) == (stage == 'document')
    assert (session.liveness_proof is None) == (stage == 'liveness')
    if stage != 'liveness':
        assert session.liveness_selfie == 'test-selfie-hash'
        assert session.liveness_manifest == 'test-manifest'


def test_ocr_retry_preserves_live_proof_and_rejects_old_nonce(client, real_models, ktp_image, face_image):
    public, session = seed_session(client, face_image)
    seed_proof(session)
    session.consumed = True
    session.last_result = {'status': 'capture', 'retry': {'stage': 'document', 'label': 'Ulangi foto KTP', 'reason': 'Wajah dokumen tidak terbaca'}}
    client.app.state.verifier.ocr = real_models.ocr
    updated = client.post(f'/api/sessions/{session.id}/retry').json()
    response = client.post(f'/api/sessions/{session.id}/document', files={'image': ('card.jpg', encoded(ktp_image), 'image/jpeg')}, headers={'X-Capture-Revision': str(updated['revision'])})
    assert response.status_code == 200
    assert session.document_result['fields']['nik'] == '1234567890123456'
    assert session.liveness_proof == 'test-proof-token'
    assert session.liveness_selfie == 'test-selfie-hash'
    with pytest.raises(__import__("fastapi").HTTPException) as invalid:
        client.app.state.sessions.consume(session.id, public['nonce'])
    assert invalid.value.status_code == 409 and not session.consumed


@pytest.mark.parametrize('bad_stage', ['document', 'liveness', 'holding'])
def test_real_face_capture_failure_identifies_correct_retry_stage(real_models, face_image, bad_stage):
    import numpy as np
    from app.model.entities import CaptureSession
    blank = np.full_like(face_image, 180)
    session = CaptureSession()
    session.document = blank if bad_stage == 'document' else face_image
    session.document_result = {'fields': {'nik': '1234567890123456', 'name': 'TEST STAGE'}, 'confidence': .9, 'engine': 'protocol fixture'}
    session.liveness_result = {'passed': True, 'pad_probability': .9, 'mode': 'protocol_test_fixture'}
    result = real_models.run(session, blank if bad_stage == 'liveness' else face_image,
                             blank if bad_stage == 'holding' else face_image, [], [])
    assert result['status'] == 'capture' and result['retry']['stage'] == bad_stage
    assert result['checks'][-2]['stage'] == bad_stage
    assert result['checks'][-2]['detail']['message'] == result['reason']


def test_detection_retries_do_not_use_three_recordings_budget(client, face_image):
    public, session = seed_session(client, face_image)
    previous_nonce = None
    for _ in range(8):
        started = client.post(f'/api/sessions/{session.id}/liveness/start')
        assert started.status_code == 200, started.text
        nonce=started.json()['capture_nonce']
        assert nonce != previous_nonce
        assert session.liveness_proof is None
        if previous_nonce:
            old=client.post(f'/api/sessions/{session.id}/liveness/frame',data={'capture_nonce':previous_nonce,'seq':0},files={'image':('frame.jpg',encoded(face_image),'image/jpeg')})
            assert old.status_code==409
        previous_nonce=nonce
        reset=client.post(f'/api/sessions/{session.id}/retake',json={'stage':'liveness','nonce':session.nonce})
        assert reset.status_code==200,reset.text
        assert session.attempt==1 and session.document is not None
    assert session.retake_attempts.get('liveness',0)==0


def test_brief_detector_gap_pauses_evidence_without_resetting_baseline():
    capture=LiveCapture(['blink','turn','smile'])
    neutral(capture.gestures)
    baseline=capture.gestures.baseline
    capture.gestures.hits=1
    capture.pause_detection(now=10)
    assert capture.gestures.baseline==baseline
    assert capture.gestures.hits==0
    assert not capture.result({'ready':False,'warnings':[]})['passed']
    capture.pause_detection(now=10.3)
    assert capture.gestures.baseline==baseline
    capture.pause_detection(now=10.4)
    assert capture.gestures.baseline is None
    assert not capture.gestures.completed


def test_prolonged_detector_gap_requires_fresh_neutral_evidence():
    capture=LiveCapture(['blink','turn','smile'])
    neutral(capture.gestures)
    capture.pause_detection(now=10)
    capture.pause_detection(now=11.1)
    assert capture.gestures.baseline is None
    capture.resume_detection()
    assert capture.detection_missing_since is None and capture.detection_misses==0


def test_mask_and_spoof_still_reset_gesture_after_soft_gap(client, monkeypatch):
    capture=LiveCapture(['blink','turn','smile'])
    neutral(capture.gestures)
    verifier=client.app.state.verifier
    # Detector outputs isolate state transitions, not model accuracy.
    monkeypatch.setattr(verifier,'inspect_capture',lambda _: {'ready':False,'warnings':[{'code':'mask','message':'Masker'}]})
    result=verifier.inspect_liveness_frame(capture,None,'x',0)
    assert capture.gestures.baseline is None and not result['passed']
    monkeypatch.setattr(verifier,'inspect_capture',lambda _: {'ready':False,'warnings':[{'code':'spoof_risk','message':'Spoof'}]})
    first=verifier.inspect_liveness_frame(capture,None,'y',1)
    second=verifier.inspect_liveness_frame(capture,None,'z',2)
    assert not first['done'] and second['done'] and not second['passed']
