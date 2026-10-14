"""Status stages test protocol truth, not biometric/model accuracy."""
import time
import pytest
from app.services.document_progress import document_progress
from test_workflow import prepare, account
from test_registration import payload


def application(state, revision=2):
    return {'state': state, 'revision': revision, 'created': '2026-10-14T00:00:00+00:00',
            'updated': '2026-10-14T02:00:00+00:00', 'payload': {
                'decision': {'kind': 'automatic'}, 'evidence': [{'kind': 'document'}],
                'history': [
                    {'from': 'VERIFYING', 'to': 'AUTO_APPROVED', 'at': 'old-capture', 'revision': 1},
                    {'from': 'SLIK_PENDING', 'to': 'SLIK_READY', 'at': 'old-pdf', 'revision': 1},
                    {'from': 'VERIFYING', 'to': 'MANUAL_PENDING', 'at': 'received', 'revision': 2},
                    {'from': 'MANUAL_SCHEDULED', 'to': 'MANUAL_IN_REVIEW', 'at': 'review-start', 'revision': 2},
                    {'from': 'MANUAL_IN_REVIEW', 'to': 'MANUAL_APPROVED', 'at': 'approved', 'revision': 2},
                    {'from': 'SLIK_PENDING', 'to': 'SLIK_READY', 'at': 'ready', 'revision': 2},
                ]}}


@pytest.mark.parametrize('state,expected', [
    ('VERIFYING', ['current', 'pending', 'pending']),
    ('CAPTURE_RETRY', ['attention', 'pending', 'pending']),
    ('TECHNICAL_PENDING', ['done', 'attention', 'pending']),
    ('MANUAL_PENDING', ['done', 'current', 'pending']),
    ('MANUAL_SCHEDULED', ['done', 'current', 'pending']),
    ('MANUAL_IN_REVIEW', ['done', 'current', 'pending']),
    ('REJECTED', ['done', 'failed', 'pending']),
    ('MANUAL_REJECTED', ['done', 'failed', 'pending']),
    ('AUTO_APPROVED', ['done', 'done', 'current']),
    ('MANUAL_APPROVED', ['done', 'done', 'current']),
    ('SLIK_PENDING', ['done', 'done', 'current']),
    ('SLIK_READY', ['done', 'done', 'done']),
    ('REQUEST_CREATED', ['pending', 'pending', 'pending']),
])
def test_current_state_controls_completion(state, expected):
    progress = document_progress(application(state))
    assert [stage['status'] for stage in progress['stages']] == expected
    assert 'old-capture' not in str(progress) and 'old-pdf' not in str(progress)
    if state != 'SLIK_READY':
        assert progress['stages'][2]['at'] is None


def test_ready_times_belong_to_current_evidence_and_manual_review():
    app = application('SLIK_READY')
    app['payload']['decision']['kind'] = 'manual'
    stages = document_progress(app)['stages']
    assert [stage['at'] for stage in stages] == ['received', 'approved', 'ready']
    assert 'manual' in stages[1]['message']
    app['revision'] = 3
    assert all(stage['at'] is None for stage in document_progress(app)['stages'])


def test_technical_error_before_evidence_does_not_claim_document_received():
    app = application('TECHNICAL_PENDING')
    app['payload']['evidence'] = []
    stages = document_progress(app)['stages']
    assert [stage['status'] for stage in stages] == ['attention', 'pending', 'pending']
    assert stages[0]['at'] is None


def test_mock_status_is_owner_bound_and_does_not_advance(client):
    receipt = client.post('/api/registrations', json=payload(preview=True)).json()
    response = client.get('/api/registrations/' + receipt['id'])
    assert response.status_code == 200
    result = response.json()
    assert result['application'] is None
    assert [s['status'] for s in result['document_progress']['stages']] == ['done', 'pending', 'pending']
    _, headers = account(client)
    assert client.get('/api/registrations/' + receipt['id'], headers=headers).status_code == 404
    assert client.app.state.repository.registration(receipt['id']) == receipt


def test_linked_registration_tracks_latest_state_and_server_identity(client, face_image):
    owner, owner_headers = account(client, login='document-owner')
    client.headers.update(owner_headers)
    app, _, _ = prepare(client, face_image, owner=owner)
    identity = client.get(f'/api/applications/{app["id"]}/registration-context')
    assert identity.status_code == 200
    assert identity.json() == {'name': 'PEMOHON DEMO', 'nik': '1234567890123456', 'birth': '1990-01-01', 'address': ''}
    _, headers = account(client)
    assert client.get(f'/api/applications/{app["id"]}/registration-context', headers=headers).status_code == 404
    record = client.post('/api/registrations', json={**payload(), 'application_id': app['id'], 'verification_id': app['verification_id']}).json()
    before = client.get('/api/registrations/' + record['id']).json()
    assert before['application']['state'] == 'AUTO_APPROVED'
    assert before['document_progress']['stages'][2]['status'] == 'current'
    assert client.post(f'/api/applications/{app["id"]}/slik').json()['state'] == 'SLIK_READY'
    after = client.get('/api/registrations/' + record['id']).json()
    assert after['application']['state'] == 'SLIK_READY'
    assert after['document_progress']['stages'][2]['status'] == 'done'
    assert after['document_progress']['stages'][2]['at']
    assert 'history' not in after['application'] and 'evidence' not in after['application']
    client.app.state.workflow.invalidate(app['id'], owner, app['capture_revision'] + 1)
    reset = client.get('/api/registrations/' + record['id']).json()
    assert reset['document_progress']['stages'][0]['status'] == 'current'
    assert all(s['at'] is None for s in reset['document_progress']['stages'])
    assert client.get(f'/api/applications/{app["id"]}/registration-context').status_code == 409


def test_expired_or_unapproved_decision_cannot_supply_registration_identity(client, face_image):
    app, _, _ = prepare(client, face_image)
    workflow = client.app.state.workflow
    with client.app.state.repository.connect(write=True) as con:
        stored = workflow.get(con, app['id'])
        stored['payload']['decision']['expires'] = time.time() - 1
        workflow.save(con, stored)
    assert client.get(f'/api/applications/{app["id"]}/registration-context').status_code == 409
    fresh = workflow.create(client.fixture_actor)
    assert client.get(f'/api/applications/{fresh["id"]}/registration-context').status_code == 409
