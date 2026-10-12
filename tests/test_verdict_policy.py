"""Policy fixtures isolate verdict logic; they do not claim biometric accuracy."""
from types import SimpleNamespace
import numpy as np
import pytest
from app.services.card import HoldingCardService
from test_liveness_stream import seed_session
from test_registration import payload


@pytest.fixture
def policy_case(client, face_image, monkeypatch):
    _, session = seed_session(client, face_image)
    session.consumed = True
    state = {'pad': .972, 'face': .620, 'same_face': .93, 'nik_matches': True,
             'visible': True, 'hand': True, 'live': True, 'continuity': .92,
             'fake': .997, 'diagnostic_error': False}
    verifier = client.app.state.verifier
    monkeypatch.setattr(verifier, 'load', lambda: None)
    verifier.face = SimpleNamespace(
        one=lambda *_args, **_kwargs: np.array([0, 0, 200, 200]),
        compare=lambda first, *_args: state['face'] if first is session.document else state['same_face'],
        feature=lambda image, _face: (None, image))
    verifier.visibility = SimpleNamespace(inspect=lambda *_args, **_kwargs: {
        'ready': state['visible'], 'warnings': [] if state['visible'] else [{'message': 'Wajah tertutup'}]})
    verifier.landmarks = SimpleNamespace(hand_near_card=lambda *_args: {'passed': state['hand']})
    verifier.pad = SimpleNamespace(score=lambda *_args: {'live_probability': state['pad'], 'mode': 'policy fixture'})
    def diagnostic(_image):
        if state['diagnostic_error']:
            raise RuntimeError('Diagnostic-only fixture failure')
        return {'fake_probability': state['fake'], 'real_probability': 1-state['fake'], 'mode': 'policy fixture'}
    verifier.deepfake = SimpleNamespace(score=diagnostic)
    monkeypatch.setattr(HoldingCardService, 'read', lambda *_args, **_kwargs: {
        'reading': {'fields': {'nik': '1234567890123456' if state['nik_matches'] else '9999999999999999'}, 'confidence': .9},
        'box': [0, 0, 100, 60], 'method': 'policy fixture'})
    def run():
        session.liveness_result = {'passed': True, 'stream': True, 'pad_probability': state['pad'],
                                  'live': {'passed': state['live'], 'mode': 'policy fixture'},
                                  'continuity': [state['continuity']]}
        # Separate image object identifies doc↔selfie versus selfie↔held scores.
        result = verifier.run(session, face_image.copy(), face_image.copy(), [], [])
        session.last_result = result
        return result
    return state, run, session


def test_high_fake_score_preserves_valid_kyc_and_registration_handoff(client, policy_case):
    state, run, session = policy_case
    result = run()
    assert result['status'] == 'pass'
    assert result['scores']['deepfake'] == .997  # Real raw output not suppressed/changed.
    diagnostic = next(c for c in result['checks'] if c.get('effect') == 'advisory')
    assert diagnostic['status'] == 'informational' and not diagnostic['calibrated']
    assert not any(c['status'] == 'failed' for c in result['checks'])
    assert result['decision_policy'] == 'kyc-core-v1-ai-image-diagnostic'
    assert not result['identity_verified']
    assert client.app.state.repository.result(result['id']) == result
    body = {**payload(), 'session_id': session.id, 'verification_id': result['id']}
    response = client.post('/api/registrations', json=body)
    assert response.status_code == 409  # Raw pass has no persistent application approval.
    # Changing a diagnostic threshold cannot turn valid captures into attacks.
    client.app.state.repository.set_settings({**result['rules'], 'deepfake_risk': .01})
    assert run()['status'] == 'pass'


@pytest.mark.parametrize('field,value,status', [
    ('pad', .20, 'attack'), ('face', .1, 'manual'), ('same_face', .1, 'manual'),
    ('nik_matches', False, 'manual'), ('visible', False, 'capture'),
    ('hand', False, 'capture'), ('live', False, 'capture'), ('continuity', .1, 'manual'),
])
def test_core_controls_still_block_invalid_capture_with_high_classifier_score(client, policy_case, field, value, status):
    state, run, session = policy_case
    state[field] = value
    result = run()
    assert result['status'] == status
    if field == 'pad':
        assert 'anti-spoof / PAD' in result['reason']
    body = {**payload(), 'session_id': session.id, 'verification_id': result['id']}
    assert client.post('/api/registrations', json=body).status_code == 409


def test_advisory_classifier_exception_does_not_invalidate_core_checks(policy_case):
    state, run, _session = policy_case
    state['diagnostic_error'] = True
    result = run()
    assert result['status'] == 'pass' and 'deepfake' not in result['scores']
    diagnostic = next(c for c in result['checks'] if c.get('effect') == 'advisory')
    assert diagnostic['status'] == 'unavailable'
