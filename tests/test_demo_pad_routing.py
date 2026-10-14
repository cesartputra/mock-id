"""Demo routing/protocol fixtures: no claim of measured biometric accuracy."""
import json
import time
from copy import deepcopy
import pytest
from app.model.entities import CaptureSession
from app.services.score_policy import ScorePolicy, REQUIRED_CONTROLS
from conftest import complete_control_fixture
from test_workflow import account, service_day


def measured_case():
    result = {'id': 'VRF-PAD-FIXTURE', 'status': 'manual', 'reason': 'Measured PAD below model threshold',
              'scores': {'face_cosine': .6125, 'kyc_face_cosine': .93, 'liveness': .41344, 'ocr': .9616},
              'checks': complete_control_fixture(), 'nik_masked': '•••• •••• •••• 3456',
              'identity_verified': False, 'identity_demo_passed': True}
    for check in result['checks']:
        if check['name'] == 'Anti-spoof / PAD':
            check.update(status='failed', detail={'score': .41344, 'threshold': .8})
        elif check['name'] == 'PAD foto memegang KTP':
            check.update(status='failed', detail={'sample': {'live_probability': .2}, 'threshold': .8})
    mandatory = {key: True for key in REQUIRED_CONTROLS}
    mandatory.update(document_face_liveness_pad=False, approved_identity_procedure=False)
    return result, mandatory


def test_screenshot_76_98_is_approved_without_changing_score_or_failed_pad():
    result, mandatory = measured_case()
    original = deepcopy(result)
    routed = ScorePolicy().route(result, mandatory)
    assert int(routed['routing_score'] * 100) / 100 == 76.98
    assert routed['components']['controls'] == 85
    assert routed['decision'] == 'AUTO_APPROVED' and routed['demo_model_override']
    assert routed['demo_override_controls'] == ['Anti-spoof / PAD', 'PAD foto memegang KTP']
    assert not routed['assessment']['all_passed']
    assert result == original and routed['mandatory'] == mandatory


@pytest.mark.parametrize('score,decision', [(49.999, 'MANUAL_PENDING'), (50, 'AUTO_APPROVED'), (50.001, 'AUTO_APPROVED')])
def test_exact_score_boundary_with_real_numeric_pad_details(monkeypatch, score, decision):
    result, mandatory = measured_case()
    policy = ScorePolicy()
    monkeypatch.setattr(policy.calibrator, 'score', lambda _: (score, {}))
    routed = policy.route(result, mandatory)
    assert routed['decision'] == decision
    assert routed['routing_score'] == score


@pytest.mark.parametrize('control', ['Wajah KTP ↔ selfie', 'Wajah selfie ↔ foto KYC', 'Kesesuaian NIK kedua foto KTP',
                                    'Selfie tanpa penutup wajah', 'Foto KYC tanpa penutup wajah', 'Kualitas capture',
                                    'Tangan dekat KTP', 'Tantangan liveness', 'Kontinuitas wajah capture', 'Dukcapil'])
def test_identity_capture_and_new_controls_still_block_even_above_50(control):
    result, mandatory = measured_case()
    next(c for c in result['checks'] if c['name'] == control)['status'] = 'failed'
    routed = ScorePolicy().route(result, mandatory)
    assert routed['routing_score'] > 50 and routed['decision'] != 'AUTO_APPROVED'
    assert not routed['demo_model_override']


@pytest.mark.parametrize('control', ['session_nonce_proof', 'document_identity_complete', 'applicant_authority', 'no_security_rejection'])
def test_bound_proof_identity_and_authority_are_never_waived(control):
    result, mandatory = measured_case()
    mandatory[control] = False
    assert ScorePolicy().route(result, mandatory)['decision'] != 'AUTO_APPROVED'


@pytest.mark.parametrize('status', ['capture', 'technical', 'attack'])
def test_explicit_capture_error_technical_error_and_attack_are_not_approved(status):
    result, mandatory = measured_case()
    result['status'] = status
    assert ScorePolicy().route(result, mandatory)['decision'] != 'AUTO_APPROVED'


@pytest.mark.parametrize('failure', ['missing', 'duplicate', 'unavailable', 'missing_score', 'nan', 'mismatch', 'unknown_control'])
def test_missing_or_invalid_pad_measurement_is_not_a_demo_override(failure):
    result, mandatory = measured_case()
    check = next(c for c in result['checks'] if c['name'] == 'Anti-spoof / PAD')
    if failure == 'missing': result['checks'].remove(check)
    elif failure == 'duplicate': result['checks'].append(deepcopy(check))
    elif failure == 'unavailable': check['status'] = 'unavailable'
    elif failure == 'missing_score': check['detail'].pop('score')
    elif failure == 'nan': check['detail']['score'] = float('nan')
    elif failure == 'mismatch': check['detail']['score'] = .7
    else: result['checks'].append({'name': 'Unknown control', 'status': 'failed'})
    assert ScorePolicy().route(result, mandatory)['decision'] != 'AUTO_APPROVED'


@pytest.mark.parametrize('mode,calibrated', [('production', False), ('production', True), ('demo', True)])
def test_production_and_calibrated_profiles_keep_all_pad_gates(mode, calibrated):
    result, mandatory = measured_case()
    policy = ScorePolicy()
    policy.mode = mode
    policy.calibrator.calibrated = calibrated
    routed = policy.route(result, mandatory)
    assert routed['decision'] == 'MANUAL_PENDING' and not routed['demo_model_override']
    assert routed['automatic_threshold'] == 95


def legacy_scheduled(client, face_image, monkeypatch):
    owner, headers = account(client, 'demo-pad-owner')
    client.headers.update(headers)
    flow = client.app.state.workflow
    app = flow.create(owner)
    flow.attest(app['id'], owner, True)
    session = CaptureSession(owner_id=owner['id'], application_id=app['id'], revision=app['revision'])
    session.document = face_image
    session.document_result = {'fields': {'nik': '1234567890123456', 'name': 'PEMOHON DEMO', 'birth': '1990-01-01'}, 'confidence': .9616}
    session.consumed = True
    session.proof_checked_revision = session.revision
    session.liveness_result = {'passed': True}
    session.liveness_selfie = 'fixture-verified-selfie-digest'
    result, _ = measured_case()
    with monkeypatch.context() as old:
        old.setattr(flow.policy, 'pad_score_eligible', lambda *_: False)
        old.setattr(flow.policy.calibrator, 'version', 'demo-routing-v7-ai-optional')
        app = flow.ingest(session, result, face_image, face_image, [face_image])
    assert app['state'] == 'MANUAL_PENDING'
    day = service_day(client).date().isoformat()
    app = client.app.state.manual.reserve(app['id'], owner, day, 'fixture-demo-old-reservation')
    assert app['state'] == 'MANUAL_SCHEDULED'
    return app, owner


def test_existing_scheduled_case_reuses_sealed_proof_releases_slot_and_downloads_pdf(client, face_image, monkeypatch):
    app, owner = legacy_scheduled(client, face_image, monkeypatch)
    flow = client.app.state.workflow
    assert flow.snapshot(app['id'], owner)['demo_policy_recheck_available']
    with flow.repository.connect() as con:
        before = flow.get(con, app['id'])['payload']['evidence']
        verification = next(e for e in before if e['kind'] == 'verification')
        original, _ = flow.evidence.read(con, verification['id'])
        assert client.app.state.manual.used(con, app['reservation']['day']) == 1
    response = client.post(f'/api/applications/{app["id"]}/demo/recheck', json={'capture_revision': app['capture_revision']})
    assert response.status_code == 200, response.text
    current = response.json()
    assert current['state'] == 'SLIK_READY' and current['capture_revision'] == app['capture_revision']
    assert current['routing']['routing_score'] == app['routing']['routing_score']
    assert current['reservation'] is None and not current['demo_policy_recheck_available']
    assert not current['identity_verified'] and current['routing']['demo_model_override']
    report = client.get(f'/api/applications/{app["id"]}/slik').json()['report']
    assert report['synthetic'] and report['debtor']['name'] == 'PEMOHON DEMO'
    assert report['subject_nik'] == '1234567890123456'
    assert client.get(f'/api/applications/{app["id"]}/slik.pdf').content.startswith(b'%PDF')
    assert client.post(f'/api/applications/{app["id"]}/demo/recheck', json={'capture_revision': app['capture_revision']}).json()['state'] == 'SLIK_READY'
    with flow.repository.connect() as con:
        assert flow.get(con, app['id'])['payload']['evidence'] == before
        assert flow.evidence.read(con, verification['id'])[0] == original
        assert client.app.state.manual.used(con, app['reservation']['day']) == 0
        assert con.execute('SELECT COUNT(*) AS n FROM issuance WHERE application_id=?', (app['id'],)).fetchone()['n'] == 1
        assert con.execute("SELECT state FROM manual_cases WHERE application_id=?", (app['id'],)).fetchone()['state'] == 'CANCELLED'


def test_recheck_never_accepts_another_owner_or_old_revision(client, face_image, monkeypatch):
    app, owner = legacy_scheduled(client, face_image, monkeypatch)
    _, headers = account(client, 'other-demo-pad-owner')
    path = f'/api/applications/{app["id"]}/demo/recheck'
    body = {'capture_revision': app['capture_revision']}
    assert client.post(path, json=body, headers=headers).status_code == 404
    assert client.post(path, json={'capture_revision': 999}).status_code == 409
    assert client.app.state.workflow.snapshot(app['id'], owner)['state'] == 'MANUAL_SCHEDULED'


@pytest.mark.parametrize('failure', ['expired', 'wrong_binding', 'missing_digest', 'missing_attestation', 'in_review', 'production', 'calibrated'])
def test_recheck_does_not_approve_invalid_evidence_or_change_cases_under_review(client, face_image, monkeypatch, failure):
    app, owner = legacy_scheduled(client, face_image, monkeypatch)
    flow = client.app.state.workflow
    if failure == 'production': flow.policy.mode = 'production'
    elif failure == 'calibrated': flow.policy.calibrator.calibrated = True
    elif failure == 'in_review':
        helper, _ = account(client, 'demo-pad-reviewer', 'helpdesk')
        client.app.state.manual.start(app['id'], helper)
    else:
        with flow.repository.connect(write=True) as con:
            stored = flow.get(con, app['id'])
            if failure == 'expired': stored['payload']['evidence'][0]['expires'] = time.time() - 1
            elif failure == 'missing_attestation': stored['payload']['authority_attested'] = False
            else:
                entry = next(e for e in stored['payload']['evidence'] if e['kind'] == 'verification')
                packed = json.loads(flow.evidence.read(con, entry['id'])[0])
                if failure == 'wrong_binding': packed['session_binding']['capture_revision'] += 1
                else: packed['session_binding']['selfie_digest'] = ''
                replacement = flow.evidence.json(con, stored, 'verification', packed, 21, 'demo-routing-v7-ai-optional')
                stored['payload']['evidence'] = [replacement if e['kind'] == 'verification' else e for e in stored['payload']['evidence']]
            flow.save(con, stored)
    response = client.post(f'/api/applications/{app["id"]}/demo/recheck', json={'capture_revision': app['capture_revision']})
    assert response.status_code == (410 if failure == 'expired' else 409)
    assert flow.snapshot(app['id'], owner)['state'] == ('MANUAL_IN_REVIEW' if failure == 'in_review' else 'MANUAL_SCHEDULED')
    assert client.get(f'/api/applications/{app["id"]}/slik.pdf').status_code == 409
