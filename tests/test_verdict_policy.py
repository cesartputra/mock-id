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
             'fake': .019, 'diagnostic_error': False, 'ai_reliable': True}
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
        return {'fake_probability': state['fake'], 'real_probability': 1-state['fake'], 'mode': 'policy fixture', 'reliable': state['ai_reliable']}
    verifier.deepfake = SimpleNamespace(assess=lambda image, face: diagnostic(image))
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


def test_image_evidence_participates_in_kyc_and_registration_handoff(client, policy_case):
    state, run, session = policy_case
    result = run()
    assert result['status'] == 'pass'
    assert result['scores']['deepfake'] == .019  # Raw output preserved.
    diagnostic = next(c for c in result['checks'] if c['name'] == 'Classifier gambar AI (diagnostik)')
    assert diagnostic['status'] == 'passed' and not diagnostic['calibrated']
    assert not any(c['status'] == 'failed' for c in result['checks'])
    assert result['decision_policy'] == 'kyc-core-v4-ai-optional'
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
    diagnostic = next(c for c in result['checks'] if c['name'] == 'Classifier gambar AI (diagnostik)')
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
    state['face'] = .2
    result = run()
    routed = workflow.ingest(session,result,face_image,face_image,[face_image])
    assert not routed['routing']['assessment']['all_passed']
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


@pytest.mark.parametrize('strict', [False, True])
def test_holding_pad_diagnostic_in_demo_and_required_in_strict_mode(client, policy_case, strict):
    state, run, _session = policy_case
    client.app.state.verifier.pad_review_enabled = not strict
    calls=[]
    def score(image,face):
        calls.append(image)
        return {'live_probability':.98 if len(calls)%2 else .01,'mode':'protocol fixture'}
    client.app.state.verifier.pad.score = score
    result = run()
    assert len(calls)==2
    assert result['status'] == ('attack' if strict else 'manual')
    assert result['scores']['liveness'] == (.01 if strict else state['pad'])
    pad = next(c for c in result['checks'] if c['name'] == 'Anti-spoof / PAD')
    assert pad['detail']['minimum_live_probability'] == .01
    assert pad['detail']['holding']['live_probability'] == .01
    if not strict:
        held = next(c for c in result['checks'] if c['name'] == 'PAD foto memegang KTP')
        assert held['status'] == 'failed'


def test_production_service_keeps_strict_pad_policy(client, monkeypatch):
    from app.services.pipeline import VerificationService
    monkeypatch.setenv('MOCK_ID_MODE','production')
    verifier=VerificationService(client.app.state.repository)
    assert not verifier.pad_review_enabled


def test_uncertain_pad_route_requires_explicit_server_eligibility_and_valid_proof():
    from app.services.score_policy import ScorePolicy, REQUIRED_CONTROLS
    from conftest import complete_control_fixture
    policy=ScorePolicy()
    result={'status':'manual','checks':complete_control_fixture(),'pad_review_required':True,'scores':{'face_cosine':.62,'kyc_face_cosine':.93,'liveness':.001,'ocr':.98,'deepfake':.01,'ai_reliability':True}}
    controls={key:True for key in REQUIRED_CONTROLS}
    controls['document_face_liveness_pad']=False
    assert policy.route(result,controls)['decision']=='MANUAL_PENDING'
    assert policy.route(result,{**controls,'session_nonce_proof':False})['decision']=='MANUAL_PENDING'
    policy.mode='production'
    assert policy.route(result,controls)['decision']=='MANUAL_PENDING'
    policy.mode='demo'
    policy.calibrator.calibrated=True
    assert policy.route(result,controls)['decision']=='MANUAL_PENDING'


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


def test_demo50_cannot_override_numeric_pad_uncertainty(client, face_image, policy_case):
    state,run,session=policy_case
    session.document_result['fields'].update(name='PEMOHON TEST',birth='1990-01-01')
    session.proof_checked_revision=session.revision
    session.liveness_selfie='protocol-fixture-binding'
    workflow=client.app.state.workflow
    workflow.attest(session.application_id,client.fixture_actor,True)
    state['pad']=.001
    result=run()
    assert result['status']=='manual'
    routed=workflow.ingest(session,result,face_image,face_image,[face_image])
    assert routed['state']=='MANUAL_PENDING' and not routed['routing']['demo_model_override']
    assert not routed['routing']['assessment']['all_passed']
    assert client.post('/api/applications/'+routed['id']+'/slik').status_code==409



@pytest.mark.parametrize('field,value', [('nik_matches',False),('visible',False),('hand',False),('live',False)])
def test_demo50_cannot_issue_for_failed_identity_or_capture(client,face_image,policy_case,field,value):
    state,run,session=policy_case
    session.document_result['fields'].update(name='PEMOHON TEST',birth='1990-01-01')
    session.proof_checked_revision=session.revision
    workflow=client.app.state.workflow
    workflow.attest(session.application_id,client.fixture_actor,True)
    state[field]=value
    result=run()
    routed=workflow.ingest(session,result,face_image,face_image,[face_image])
    assert routed['state'] not in ['AUTO_APPROVED','SLIK_READY']
    assert client.post('/api/applications/'+routed['id']+'/slik').status_code==409


@pytest.mark.parametrize('score,decision',[(49.999,'MANUAL_PENDING'),(50,'MANUAL_PENDING'),(50.001,'MANUAL_PENDING')])
def test_demo50_boundary_and_original_failed_controls(monkeypatch,score,decision):
    from app.services.score_policy import ScorePolicy, REQUIRED_CONTROLS
    from conftest import complete_control_fixture
    policy=ScorePolicy()
    monkeypatch.setattr(policy.calibrator,'score',lambda _:(score,{}))
    result={'status':'manual','scores':{},'checks':complete_control_fixture()}
    controls={k:True for k in REQUIRED_CONTROLS}
    controls.update(document_face_liveness_pad=False,approved_identity_procedure=False)
    routed=policy.route(result,controls)
    assert routed['decision']==decision and routed['automatic_threshold']==50
    assert routed['mandatory']['document_face_liveness_pad'] is False
    for key in ['session_nonce_proof','document_identity_complete','applicant_authority']:
        assert policy.route(result,{**controls,key:False})['decision']!='AUTO_APPROVED'
    policy.mode='production'
    assert policy.route(result,controls)['decision']!='AUTO_APPROVED'
    policy.mode='demo';policy.calibrator.calibrated=True
    assert policy.route(result,controls)['decision']!='AUTO_APPROVED'
