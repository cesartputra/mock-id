from app.model.repository import Repository


def payload(kind='individual', preview=False):
    return {'debtor_type': kind, 'preview': preview, 'name': 'PEMOHON DEMO',
            'email': 'pemohon@example.com', 'phone': '081234567890',
            'address': 'Jalan Contoh No. 1', 'purpose': 'personal'}


def test_post_kyc_registration_rejects_unverified_or_reset_capture(client, face_image):
    body = payload()
    assert client.post('/api/registrations', json=body).status_code == 422
    session = client.app.state.sessions.create(owner_id=client.fixture_actor['id'])
    session.document = face_image
    session.document_result = {'fields': {'nik': '1234567890123456'}}
    session.last_result = {'id':'TEST-PASS','status':'pass'}
    session.consumed = True
    body.update(session_id=session.id,verification_id='TEST-PASS')
    # An in-memory pass alone can no longer authorize the host handoff.
    assert client.post('/api/registrations',json=body).status_code==409


def test_preview_receipt_never_fabricates_pass_and_survives_restart(client):
    result = client.post('/api/registrations', json=payload(preview=True))
    assert result.status_code == 200
    record = result.json()
    assert record['mode'] == 'preview' and record['kyc'] == 'preview'
    assert record['verification_id'] is None and not record['identity_verified']
    assert record['status'] == 'received_mock'
    assert client.app.state.repository.results() == []
    restarted = Repository(client.app.state.data_directory)
    assert restarted.registration(record['id']) == record
    assert client.get('/api/registrations/DEMO-NOT-FOUND').status_code == 404


def test_business_and_deceased_skip_kyc_without_claiming_verification(client):
    for kind in ['business', 'deceased']:
        response = client.post('/api/registrations', json=payload(kind))
        assert response.status_code == 200
        record = response.json()
        assert record['kyc'] == 'not_applicable' and record['verification_id'] is None
        assert not record['identity_verified'] and not record['submitted_to_ojk']
    bad = {**payload('business'), 'verification_id': 'arbitrary'}
    assert client.post('/api/registrations', json=bad).status_code == 422


def test_registration_validation_and_local_only_policy(client):
    for key, value in [('debtor_type', 'unknown'), ('email', 'not-an-email'), ('phone', 'abc'), ('purpose', 'unknown')]:
        assert client.post('/api/registrations', json={**payload(preview=True), key: value}).status_code == 422
    assert client.post('/api/registrations', json=payload(preview=True), headers={'Origin': 'https://other.example'}).status_code == 403
