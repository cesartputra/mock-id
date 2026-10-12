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
    ('pad', .20, 'manual'), ('face', .1, 'manual'), ('same_face', .1, 'manual'),
    ('nik_matches', False, 'manual'), ('visible', False, 'capture'),
    ('hand', False, 'capture'), ('live', False, 'capture'), ('continuity', .1, 'manual'),
])
def test_core_controls_still_block_invalid_capture_with_high_classifier_score(client, policy_case, field, value, status):
    state, run, session = policy_case
    state[field] = value
    result = run()
    assert result['status'] == status
    if field == 'pad':
        assert 'anti-spoof' in result['reason'] and result['pad_review_required']
        assert next(c for c in result['checks'] if c['name']=='Anti-spoof / PAD')['status']=='failed'
    body = {**payload(), 'session_id': session.id, 'verification_id': result['id']}
    assert client.post('/api/registrations', json=body).status_code == 409


def test_advisory_classifier_exception_does_not_invalidate_core_checks(policy_case):
    state, run, _session = policy_case
    state['diagnostic_error'] = True
    result = run()
    assert result['status'] == 'pass' and 'deepfake' not in result['scores']
    diagnostic = next(c for c in result['checks'] if c.get('effect') == 'advisory')
    assert diagnostic['status'] == 'unavailable'


def test_strict_pad_policy_still_rejects_low_scores(client, policy_case):
    state, run, _session = policy_case
    client.app.state.verifier.pad_review_enabled = False
    state['pad'] = .2
    result = run()
    assert result['status'] == 'attack' and not result['pad_review_required']


def test_pad_uncertainty_does_not_hide_failed_motion(policy_case):
    state, run, _session = policy_case
    state.update(pad=.2, live=False)
    result = run()
    assert result['status']=='capture' and not result['pad_review_required']


def test_uncertain_pad_takes_today_quota_but_never_issues_without_review(client, face_image, policy_case):
    from test_workflow import service_day
    state, run, session = policy_case
    session.document_result['fields'].update(name='PEMOHON TEST',birth='1990-01-01')
    session.proof_checked_revision = session.revision
    session.liveness_selfie = 'protocol-fixture-binding'
    workflow = client.app.state.workflow
    workflow.attest(session.application_id, client.fixture_actor, True)
    state['pad'] = .001
    result = run()
    routed = workflow.ingest(session,result,face_image,face_image,[face_image])
    assert routed['routing']['routing_score'] < 75
    assert routed['state']=='MANUAL_PENDING'
    with workflow.repository.connect() as con:
        stored=workflow.get(con,routed['id'])['payload']['routing']
    assert stored['mandatory']['document_face_liveness_pad'] is False
    assert not stored['security_review']
    assert client.get('/api/applications/'+routed['id']+'/slik.pdf').status_code==409
    service_day(client)
    reserved = client.app.state.manual.admit_today(routed['id'],client.fixture_actor)
    assert reserved['state']=='MANUAL_SCHEDULED'
    assert client.get('/api/applications/'+routed['id']+'/slik.pdf').status_code==409


def test_holding_pad_is_also_required_before_automatic_approval(client, policy_case):
    state, run, _session = policy_case
    calls=[]
    def score(image,face):
        calls.append(image)
        return {'live_probability':.98 if len(calls)%2 else .01,'mode':'protocol fixture'}
    client.app.state.verifier.pad.score = score
    result = run()
    assert len(calls)==2
    assert result['status']=='manual' and result['pad_review_required']
    assert result['scores']['liveness']==.01


def test_production_service_keeps_strict_pad_policy(client, monkeypatch):
    from app.services.pipeline import VerificationService
    monkeypatch.setenv('MOCK_ID_MODE','production')
    verifier=VerificationService(client.app.state.repository)
    assert not verifier.pad_review_enabled


def test_uncertain_pad_route_requires_valid_proof_and_never_autoapproves():
    from app.services.score_policy import ScorePolicy, REQUIRED_CONTROLS
    policy=ScorePolicy()
    result={'status':'manual','pad_review_required':True,'scores':{'face_cosine':.62,'kyc_face_cosine':.93,'liveness':.001,'ocr':.98}}
    controls={key:True for key in REQUIRED_CONTROLS}
    controls['document_face_liveness_pad']=False
    assert policy.route(result,controls)['decision']=='MANUAL_PENDING'
    assert policy.route(result,{**controls,'session_nonce_proof':False})['decision']=='REJECTED'
    policy.mode='production'
    assert policy.route(result,controls)['decision']=='REJECTED'
    policy.mode='demo'
    policy.calibrator.calibrated=True
    assert policy.route(result,controls)['decision']=='REJECTED'


def test_mock_dukcapil_pass_is_persisted_and_reset_without_changing_official_identity(client, face_image, policy_case):
    state,run,session=policy_case
    session.document_result['fields'].update(name='PEMOHON TEST',birth='1990-01-01')
    session.proof_checked_revision=session.revision
    session.liveness_selfie='protocol-fixture-binding'
    workflow=client.app.state.workflow
    workflow.attest(session.application_id,client.fixture_actor,True)
    result=run()
    dukcapil=next(c for c in result['checks'] if c['name']=='Dukcapil')
    assert dukcapil['status']=='passed' and dukcapil['mode']=='mock'
    assert result['identity_demo_passed'] and not result['identity_verified']
    routed=workflow.ingest(session,result,face_image,face_image,[face_image])
    assert routed['state']=='AUTO_APPROVED' and routed['identity_demo_passed']
    assert workflow.snapshot(routed['id'],client.fixture_actor)['identity_demo_passed']
    workflow.invalidate(routed['id'],client.fixture_actor,session.revision+1)
    assert not workflow.snapshot(routed['id'],client.fixture_actor)['identity_demo_passed']


def test_mock_dukcapil_pass_does_not_approve_uncertain_pad(policy_case):
    state,run,_session=policy_case
    state['pad']=.01
    result=run()
    assert result['identity_demo_passed'] and result['pad_review_required']
    assert result['status']=='manual'
