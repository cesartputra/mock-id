"""Deletion/crop protocol tests use disposable data, never personal KTP images."""
import json
import time
import cv2
import numpy as np
import pytest
from fastapi import HTTPException
from app.model.repository import utcnow
from app.services.document import document_crop
from app.services.imaging import card_region
from test_workflow import prepare as protocol_prepare, account, service_day


def prepare(client, face_image, **kwargs):
    app, session, result = protocol_prepare(client, face_image, **kwargs)
    return client.get('/api/applications/' + app["id"]).json(), session, result


def clean(client, app, mode="photos", body_changes=None, headers=None):
    plan = client.get(f"/api/operator/applications/{app['id']}/cleanup").json()
    body = {"mode": mode, "capture_revision": plan["capture_revision"], "expected_updated_at": plan["updated_at"], "confirm_application_id": app["id"]}
    body.update(body_changes or {})
    return client.post(f"/api/operator/applications/{app['id']}/cleanup", json=body, headers=headers)


def test_photo_cleanup_keeps_identity_results_and_ready_report(client, face_image):
    app, session, result = prepare(client, face_image)
    result.update(created=utcnow(), session_id=session.id, application={"id": app["id"]})
    client.app.state.repository.save_result(result)
    client.app.state.slik.issue(app["id"], client.fixture_actor)
    original = client.get(f"/api/applications/{app['id']}/slik").json()
    images = [e for e in app["evidence"] if e["kind"] not in {"identity", "verification"}]
    response = clean(client, app)
    assert response.status_code == 200 and response.json()["deleted_photos"] == len(images)
    snapshot = client.get(f"/api/applications/{app['id']}").json()
    assert snapshot["state"] == "SLIK_READY" and snapshot["photo_cleanup"]["count"] == len(images)
    assert client.get(f"/api/applications/{app['id']}/slik").json() == original
    assert client.app.state.repository.result(result["id"])
    for entry in images:
        assert client.get('/api/evidence/' + entry["id"]).status_code == 410
    identity_id = next(e["id"] for e in app["evidence"] if e["kind"] == "identity")
    assert client.get('/api/evidence/' + identity_id).json()["nik"] == "1234567890123456"


def test_photo_cleanup_removes_past_capture_images_and_memory(client, face_image):
    app, _, _ = prepare(client, face_image)
    flow = client.app.state.workflow
    with flow.repository.connect(write=True) as con:
        stored = flow.get(con, app["id"])
        old = flow.evidence.image(con, {**stored, "revision": 99}, "document-crop", face_image, 21, "fixture")
    session = client.app.state.sessions.create(client.fixture_actor["id"], app["id"], app["capture_revision"])
    session.document = face_image
    session.evidence_frames = [face_image]
    session.document_probe = {"image": face_image}
    assert clean(client, app).status_code == 200
    assert session.data_cleaned and session.document is None and not session.evidence_frames and session.document_probe is None
    with flow.repository.connect() as con:
        assert con.execute("SELECT ciphertext FROM evidence WHERE id=?", (old["id"],)).fetchone()["ciphertext"] is None
    with pytest.raises(HTTPException) as exc:
        client.app.state.sessions.get(session.id)
    assert exc.value.status_code == 410


def test_full_cleanup_removes_only_selected_application_and_releases_quota(client, face_image):
    app, session, result = prepare(client, face_image, manual=True)
    other, _, _ = prepare(client, face_image)  # Same owner/NIK intentionally preserved.
    service_day(client)
    client.app.state.manual.admit_today(app["id"], client.fixture_actor)
    repo = client.app.state.repository
    result.update(created=utcnow(), session_id=session.id, application={"id": app["id"]})
    repo.save_result(result)
    repo.save_registration({"id": "DEMO-CLEANUP", "created": utcnow(), "verification_id": result["id"], "application_id": app["id"], "name": "PEMOHON DEMO"})
    with repo.connect(write=True) as con:
        con.execute("INSERT INTO idempotency VALUES (?,?,?,?)", (client.fixture_actor["id"], "fixture-clean", "fixture", repo.encode({"application_id": app["id"]}, "idempotency:" + client.fixture_actor["id"] + ":fixture-clean")))
    response = clean(client, app, "full")
    assert response.status_code == 200 and response.json()["application_deleted"]
    for path in [f"/api/applications/{app['id']}", f"/api/applications/{app['id']}/slik.pdf", f"/api/operator/applications/{app['id']}/cleanup"]:
        assert client.get(path).status_code == 404
    assert client.get('/api/applications/' + other["id"]).status_code == 200
    assert repo.result(result["id"]) is None and repo.registration("DEMO-CLEANUP") is None
    with repo.connect() as con:
        for table in ["evidence", "manual_cases", "issuance"]:
            assert con.execute("SELECT COUNT(*) AS n FROM " + table + " WHERE application_id=?", (app["id"],)).fetchone()["n"] == 0
        assert not con.execute("SELECT key FROM idempotency WHERE key='fixture-clean'").fetchone()
        assert not con.execute("SELECT ref FROM audit WHERE ref=?", (app["id"],)).fetchone()
    assert client.get('/api/auth/me').status_code == 200  # Administrator account not removed.


def test_full_cleanup_removes_report_and_old_results_without_touching_other_data(client, face_image):
    app, session, result = prepare(client, face_image)
    client.app.state.slik.issue(app["id"], client.fixture_actor)
    repo = client.app.state.repository
    for suffix in ["old", "current"]:
        repo.save_result({**result, "id": "VRF-" + suffix, "created": utcnow(), "session_id": session.id})
    assert clean(client, app, "full").status_code == 200
    assert repo.result("VRF-old") is None and repo.result("VRF-current") is None
    with repo.connect() as con:
        assert not con.execute("SELECT id FROM issuance WHERE application_id=?", (app["id"],)).fetchone()


@pytest.mark.parametrize("role", ["applicant", "helpdesk", "integration"])
def test_cleanup_is_admin_only(client, face_image, role):
    app, _, _ = prepare(client, face_image)
    _, headers = account(client, "cleanup-" + role, role)
    assert client.get(f"/api/operator/applications/{app['id']}/cleanup", headers=headers).status_code == 403
    assert clean(client, app, headers=headers).status_code == 403
    assert client.get('/api/applications/' + app["id"]).status_code == 200


@pytest.mark.parametrize("change,status", [({"mode": "all-users"}, 422), ({"confirm_application_id": "APP-WRONG"}, 422), ({"capture_revision": 999}, 409), ({"expected_updated_at": "old-version-timestamp"}, 409)])
def test_confirmation_and_stale_version_are_rejected(client, face_image, change, status):
    app, _, _ = prepare(client, face_image)
    assert clean(client, app, body_changes=change).status_code == status
    assert client.get('/api/evidence/' + next(e["id"] for e in app["evidence"] if e["kind"] == "document")).status_code == 200


def test_active_native_work_blocks_cleanup(client, face_image):
    app, _, _ = prepare(client, face_image)
    session = client.app.state.sessions.create(client.fixture_actor["id"], app["id"])
    session.processing = True
    assert clean(client, app, "full").status_code == 409
    session.processing = False
    with client.app.state.repository.connect(write=True) as con:
        con.execute("INSERT INTO issuance(id,application_id,revision,state,lease_until) VALUES (?,?,?,?,?)", ("SLIK-BUSY", app["id"], app["capture_revision"], "IN_FLIGHT", time.time() + 60))
    assert clean(client, app).status_code == 409


def test_missing_object_storage_cannot_claim_photos_deleted(client, face_image):
    app, _, _ = prepare(client, face_image)
    image_id = next(e["id"] for e in app["evidence"] if e["kind"] == "document")
    with client.app.state.repository.connect(write=True) as con:
        con.execute("UPDATE evidence SET ciphertext=? WHERE id=?", ("s3:fixture-remote", image_id))
    assert clean(client, app).status_code == 503
    with client.app.state.repository.connect() as con:
        assert con.execute("SELECT ciphertext FROM evidence WHERE id=?", (image_id,)).fetchone()["ciphertext"] == "s3:fixture-remote"


def reading_for(image):
    _, crop, box = card_region(image)[0]
    return {"fields": {"nik": "1234567890123456"}, "crop_method": "card_geometry", "card_box": box}, crop


def card_scene(ktp_image):
    scene = np.full((850, 1200, 3), 80, np.uint8)
    scene[130:670, 160:1016] = ktp_image
    return scene


def test_crop_recovers_selected_native_card_not_background(ktp_image):
    scene = card_scene(ktp_image)
    reading, expected = reading_for(scene)
    crop, info = document_crop(scene, reading)
    assert np.array_equal(crop, expected) and crop.shape[0] < scene.shape[0] and crop.shape[1] < scene.shape[1]
    assert info["source_box"] == reading["card_box"]
    assert document_crop(scene, {"crop_method": "full_frame", "card_box": [0, 0, 1200, 850]}) is None


def test_ingest_saves_encrypted_crop_with_original_version_and_retention(client, face_image, ktp_image):
    app, session, result = prepare(client, face_image)
    scene = card_scene(ktp_image)
    reading, expected = reading_for(scene)
    session.document = scene
    session.document_result.update(reading)
    client.app.state.workflow.invalidate(app["id"], client.fixture_actor, 1)
    session.revision = session.proof_checked_revision = 1
    client.app.state.workflow.ingest(session, result, face_image, face_image, [face_image])
    snapshot = client.get('/api/applications/' + app["id"]).json()
    source = next(e for e in snapshot["evidence"] if e["kind"] == "document")
    crop = next(e for e in snapshot["evidence"] if e["kind"] == "document-crop")
    assert crop["derived_from"] == source["id"] and crop["revision"] == source["revision"] and crop["expires"] == source["expires"]
    image = cv2.imdecode(np.frombuffer(client.get('/api/evidence/' + crop["id"]).content, np.uint8), cv2.IMREAD_COLOR)
    assert image.shape == expected.shape
    with client.app.state.repository.connect() as con:
        stored = con.execute("SELECT ciphertext FROM evidence WHERE id=?", (crop["id"],)).fetchone()["ciphertext"]
        assert not stored.startswith('JFIF') and "1234567890123456" not in stored


def test_existing_photo_crop_endpoint_is_bound_idempotent_and_authorized(client, face_image, ktp_image, monkeypatch):
    app, _, _ = prepare(client, face_image)
    flow = client.app.state.workflow
    scene = card_scene(ktp_image)
    with flow.repository.connect(write=True) as con:
        saved = flow.get(con, app["id"])
        doc = next(e for e in saved["payload"]["evidence"] if e["kind"] == "document")
        encoded = cv2.imencode('.jpg', scene)[1].tobytes()
        row = dict(con.execute('SELECT * FROM evidence WHERE id=?', (doc["id"],)).fetchone())
        con.execute('UPDATE evidence SET ciphertext=? WHERE id=?', (flow.box.seal(encoded, flow.evidence.binding(row)), doc["id"]))
    monkeypatch.setattr(client.app.state.verifier, "document", lambda image: reading_for(image)[0])
    endpoint = f"/api/applications/{app['id']}/document-crop"
    one = client.post(endpoint)
    assert one.status_code == 200, one.text
    two = client.post(endpoint)
    assert two.status_code == 200
    assert len([e for e in two.json()["evidence"] if e["kind"] == "document-crop"]) == 1
    _, headers = account(client, 'crop-another-owner', 'applicant')
    assert client.post(endpoint, headers=headers).status_code == 403
    assert clean(client, app).status_code == 200
    assert client.post(endpoint).status_code == 410


def test_cleanup_during_crop_ocr_cannot_restore_deleted_photo(client, face_image, ktp_image):
    app, _, _ = prepare(client, face_image)
    service = client.app.state.operator_data
    _, source = service.crop_source(app["id"], client.fixture_actor)
    revision, metadata, _, nik = source
    scene = card_scene(ktp_image)
    reading, _ = reading_for(scene)
    assert clean(client, app).status_code == 200
    with pytest.raises(HTTPException) as exc:
        service.save_crop(app["id"], client.fixture_actor, revision, metadata, scene, reading, nik)
    assert exc.value.status_code == 410


def test_full_cleanup_finds_failed_results_after_session_and_evidence_expire(client, face_image):
    app, session, result = prepare(client, face_image)
    repo = client.app.state.repository
    # The pipeline may save a result before workflow ingest. Its session link
    # must survive both in-memory expiry and regular retention purging.
    orphan = {**result, "id": "VRF-BEFORE-INGEST", "created": utcnow(), "session_id": session.id}
    repo.save_result(orphan)
    with repo.connect(write=True) as con:
        con.execute("UPDATE evidence SET ciphertext=NULL WHERE application_id=?", (app["id"],))
    assert clean(client, app, "full").status_code == 200
    assert repo.result(orphan["id"]) is None
