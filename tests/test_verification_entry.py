"""Preflight protocol tests; no private KTP, webcam or external CAPTCHA."""

import base64
import io
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import HTTPException
from PIL import Image

from app.services.verification_entry import VerificationEntryService
from conftest import verification_entry_body


def browser(client):
    client.headers.pop('Authorization', None)
    headers = {'X-Workspace-Mode': 'public'}
    response = client.post('/api/auth/guest', headers=headers)
    assert response.status_code == 200
    return response.json()['principal'], headers


def test_public_session_requires_consent_and_solved_captcha(client):
    who, headers = browser(client)
    for body in [{}, {'consent': True}, {'consent': True, 'captcha_token': 'invalid-token-of-sufficient-length'}]:
        response = client.post('/api/sessions', json=body, headers=headers)
        assert response.status_code == 403
    assert client.get('/api/applications', headers=headers).json() == []
    entry = verification_entry_body(client, headers)
    # Missing/false consent must not consume a solved receipt.
    assert client.post('/api/sessions', json={**entry, 'consent': False}, headers=headers).status_code == 403
    response = client.post('/api/sessions', json=entry, headers=headers)
    assert response.status_code == 200, response.text
    session = response.json()
    with client.app.state.repository.connect() as con:
        app = client.app.state.workflow.get(con, session['application_id'])
    assert app['payload']['authority_attested'] is True
    assert app['owner_id'] == who['id']
    assert client.post('/api/sessions', json=entry, headers=headers).status_code == 403
    assert len(client.get('/api/applications', headers=headers).json()) == 1


def test_puzzle_images_are_local_pngs_and_answer_is_not_exposed(client):
    _, headers = browser(client)
    response = client.post('/api/verification-entry/challenge', headers=headers)
    assert response.status_code == 200
    puzzle = response.json()
    assert 'target_x' not in puzzle and 'answer' not in puzzle
    for key, dimensions in [('background', (320, 180)), ('piece', (52, 52))]:
        assert puzzle[key].startswith('data:image/png;base64,')
        with Image.open(io.BytesIO(base64.b64decode(puzzle[key].split(',', 1)[1]))) as image:
            assert image.size == dimensions
    assert response.headers['cache-control'] == 'no-store'
    assert client.post('/api/verification-entry/solve', json={
        'challenge_id': puzzle['challenge_id'], 'offset': 999}).status_code == 422


def test_puzzle_wrong_answer_expiry_refresh_and_single_use():
    service = VerificationEntryService()
    old = service.issue('owner')
    for attempt in range(3):
        with pytest.raises(HTTPException) as error:
            service.solve('owner', old['challenge_id'], 0)
        assert error.value.status_code == (422 if attempt == 0 else 409)
    assert old['challenge_id'] not in service.challenges
    fresh = service.issue('owner')
    service.challenges[fresh['challenge_id']].expires = 0
    with pytest.raises(HTTPException): service.solve('owner', fresh['challenge_id'], 100)
    fresh = service.issue('owner')
    private = service.challenges[fresh['challenge_id']]
    solved = service.solve('owner', private.id, private.target_x)
    with pytest.raises(HTTPException): service.solve('owner', private.id, private.target_x)
    service.issue('owner')
    with pytest.raises(HTTPException): service.consume('owner', solved['captcha_token'])


def test_receipt_is_owner_bound_expiring_and_atomically_consumed():
    service = VerificationEntryService()
    public = service.issue('owner')
    private = service.challenges[public['challenge_id']]
    with pytest.raises(HTTPException): service.solve('other', private.id, private.target_x)
    token = service.solve('owner', private.id, private.target_x)['captcha_token']
    with pytest.raises(HTTPException): service.consume('other', token)
    def consume():
        try:
            service.consume('owner', token)
            return 'accepted'
        except HTTPException:
            return 'rejected'
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: consume(), range(2)))
    assert sorted(results) == ['accepted', 'rejected']
    public = service.issue('owner')
    private = service.challenges[public['challenge_id']]
    token = service.solve('owner', private.id, private.target_x)['captcha_token']
    service.receipts[token].expires = 0
    with pytest.raises(HTTPException): service.consume('owner', token)


def test_public_receipt_cannot_create_another_owners_session(client):
    _, headers = browser(client)
    entry = verification_entry_body(client, headers)
    other = client.app.state.auth.create_user('other-captcha-owner', 'fixture-password-123', 'applicant')
    token, _ = client.app.state.auth.login('other-captcha-owner', 'fixture-password-123')
    response = client.post('/api/sessions', json=entry, headers={'Authorization': 'Bearer ' + token})
    assert response.status_code == 403
    assert client.post('/api/sessions', json=entry, headers=headers).status_code == 200


def test_public_resume_requires_fresh_preflight_but_stage_retake_does_not(client):
    _, headers = browser(client)
    entry = verification_entry_body(client, headers)
    session = client.post('/api/sessions', json=entry, headers=headers).json()
    app_id = session['application_id']
    assert client.post('/api/sessions', json={**entry, 'application_id': app_id}, headers=headers).status_code == 403
    retake = client.post(f"/api/sessions/{session['id']}/retake",
                         json={'stage': 'document', 'nonce': session['nonce']}, headers=headers)
    assert retake.status_code == 200, retake.text
    fresh = verification_entry_body(client, headers)
    assert client.post('/api/sessions', json={**fresh, 'application_id': app_id}, headers=headers).status_code == 200


def test_wrong_position_invalidates_only_that_owners_puzzle_then_fresh_receipt_works():
    service = VerificationEntryService()
    old = service.issue('owner')
    other = service.issue('other')
    target = service.challenges[old['challenge_id']].target_x
    with pytest.raises(HTTPException) as error:
        service.solve('owner', old['challenge_id'], 0)
    assert error.value.status_code == 422
    assert old['challenge_id'] not in service.challenges
    assert other['challenge_id'] in service.challenges
    with pytest.raises(HTTPException):
        service.solve('owner', old['challenge_id'], target)
    fresh = service.issue('owner')
    assert fresh['challenge_id'] != old['challenge_id']
    assert fresh['background'] != old['background']
    token = service.solve('owner', fresh['challenge_id'], service.challenges[fresh['challenge_id']].target_x)['captcha_token']
    service.consume('owner', token)
