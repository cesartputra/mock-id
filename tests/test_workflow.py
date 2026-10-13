"""Application/protocol fixtures verify routing & authorization, not AI accuracy."""

import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from app.main import create_app
from app.services.score_policy import (
    ScorePolicy,
    ScoreCalibrator,
    mapped,
    DEMO_POINTS,
    REQUIRED_CONTROLS,
)
from app.services.workflow import JAKARTA
from app.services.slik import DEMO_MARKER, MockSlikAdapter
from app.model.entities import CaptureSession
from test_registration import payload
from conftest import complete_control_fixture


def account(client, login="another-user", role="applicant"):
    user = client.app.state.auth.create_user(login, "fixture-password-123", role)
    token, _ = client.app.state.auth.login(login, "fixture-password-123")
    return user, {"X-Local-Client": "mock-id", "Authorization": "Bearer " + token}


def prepare(client, face_image, owner=None, manual=False):
    # Protocol-only fixtures explicitly inject a validated proof flag. Actual
    # camera binding/replay tests remain in the existing model/API suites.
    owner = owner or client.fixture_actor
    flow = client.app.state.workflow
    app = flow.create(owner)
    flow.attest(app["id"], owner, True)
    session = CaptureSession(
        owner_id=owner["id"], application_id=app["id"], revision=app["revision"]
    )
    session.document = face_image
    session.document_result = {
        "fields": {
            "nik": "1234567890123456",
            "name": "PEMOHON DEMO",
            "birth": "1990-01-01",
        },
        "confidence": 0.98,
    }
    session.consumed = True
    session.proof_checked_revision = session.revision
    session.liveness_result = {"passed": True}
    session.liveness_selfie = "fixture-bound-image-digest"
    result = {
        "id": "VRF-TEST-" + session.id,
        "status": "manual" if manual else "pass",
        "nik_masked": "•••• •••• •••• 3456",
        "reason": "Protocol policy fixture",
        "scores": {
            "face_cosine": 0.2 if manual else 0.62,
            "kyc_face_cosine": 0.93,
            "liveness": 0.4 if manual else 0.972,
            "ocr": 0.8 if manual else 0.98,
            "deepfake": .01, "ai_reliability": True,
        },
        "checks": complete_control_fixture(),
        "identity_verified": False,
        "retry": None,
    }
    if manual:
        next(c for c in result["checks"] if c["name"] == "Anti-spoof / PAD")["status"] = "failed"
    snapshot = flow.ingest(session, result, face_image, face_image, [face_image])
    return snapshot, session, result


def service_day(client):
    now = datetime.now(JAKARTA)
    day = now.date() + timedelta(days=(0 - now.weekday()) % 7)
    moment = datetime.combine(day, datetime.strptime("10:00", "%H:%M").time(), JAKARTA)
    client.app.state.manual.clock = lambda: moment
    return moment


@pytest.mark.parametrize(
    "score,decision",
    [
        (49.99, "MANUAL_PENDING"),
        (50, "AUTO_APPROVED"),
        (74.99, "AUTO_APPROVED"),
        (75, "AUTO_APPROVED"),
        (94, "AUTO_APPROVED"),
        (94.99, "AUTO_APPROVED"),
        (95, "AUTO_APPROVED"),
        (100, "AUTO_APPROVED"),
    ],
)
def test_unrounded_policy_boundaries(monkeypatch, score, decision):
    policy = ScorePolicy()
    monkeypatch.setattr(policy.calibrator, "score", lambda raw: (score, {}))
    result = policy.route(
        {"status": "pass", "scores": {}, "checks": complete_control_fixture()}, {key: True for key in REQUIRED_CONTROLS}
    )
    assert (
        result["decision"] == decision
        and result["routing_score"] == score
        and result["calibrated"] is False
    )


def test_mandatory_and_errors_cannot_be_hidden_by_score(monkeypatch):
    policy = ScorePolicy()
    monkeypatch.setattr(policy.calibrator, "score", lambda raw: (100, {}))
    assert (
        policy.route(
            {"status": "pass", "scores": {}, "checks": complete_control_fixture()},
            {
                **{key: True for key in REQUIRED_CONTROLS},
                "approved_identity_procedure": False,
            },
        )["decision"]
        == "MANUAL_PENDING"
    )
    assert (
        policy.route({"status": "capture", "scores": {}}, {})["decision"]
        == "CAPTURE_RETRY"
    )
    assert (
        policy.route({"status": "technical", "scores": {}}, {})["decision"]
        == "TECHNICAL_PENDING"
    )
    assert (
        policy.route({"status": "attack", "scores": {}}, {})["decision"] == "REJECTED"
    )
    policy = ScorePolicy()
    result = policy.route({"status": "pass", "scores": {}, "checks": complete_control_fixture()}, {"valid": True})
    assert result["routing_score"] is None and result["decision"] == "TECHNICAL_PENDING"


def test_demo_mapping_is_not_cosine_percent_and_rejects_nonfinite():
    assert mapped(0.6, DEMO_POINTS["face"]) == 97
    score, _ = ScoreCalibrator().score(
        {"face_cosine": 0.6, "kyc_face_cosine": 0.9, "liveness": 0.95, "ocr": 0.9, "deepfake": .01, "ai_reliability": True, "validation_coverage": 1}
    )
    assert 95 < score < 100
    assert ScoreCalibrator().score({"face_cosine": float("nan")}) == (None, None)


def test_production_without_calibration_cannot_autoapprove(monkeypatch):
    monkeypatch.setenv("MOCK_ID_MODE", "production")
    policy = ScorePolicy()
    monkeypatch.setattr(policy.calibrator, "score", lambda raw: (100, {}))
    assert (
        policy.route(
            {"status": "pass", "scores": {}, "checks": complete_control_fixture()}, {key: True for key in REQUIRED_CONTROLS}
        )["decision"]
        == "MANUAL_PENDING"
    )


def test_calibration_artifact_requires_integrity_and_evaluation(monkeypatch, tmp_path):
    data = {
        "schema": 2,
        "feature_policy": "core-controls-v2-pad-min-geometry-ai-optional",
        "model_sha256": __import__("app.services.score_policy", fromlist=["calibration_contract"]).calibration_contract(),
        "version": "calibration-fixture-v2",
        "face_model": "insightface-buffalo-l-w600k-r50",
        "points": DEMO_POINTS,
        "weights": {"face": .25/.90, "pad": .25/.90, "ocr": .1/.90, "controls": .3/.90},
        "evaluation_report": "fixture only — not approved production accuracy",
        "approved_by": "protocol-test",
    }
    path = tmp_path / "artifact.json"
    path.write_text(json.dumps(data))
    monkeypatch.setenv("MOCK_ID_CALIBRATION_FILE", str(path))
    with pytest.raises(ValueError):
        ScoreCalibrator()
    monkeypatch.setenv(
        "MOCK_ID_CALIBRATION_SHA256", hashlib.sha256(path.read_bytes()).hexdigest()
    )
    assert ScoreCalibrator().calibrated
    path.write_text("{}")
    with pytest.raises(ValueError):
        ScoreCalibrator()


def test_auto_synthetic_report_bound_to_server_identity_and_idempotent(
    client, face_image
):
    app, session, _ = prepare(client, face_image)
    assert app["state"] == "AUTO_APPROVED" and not app["identity_verified"]
    issued = client.post("/api/applications/" + app["id"] + "/slik")
    assert issued.status_code == 200, issued.text
    assert issued.json()["state"] == "SLIK_READY"
    report = client.get("/api/applications/" + app["id"] + "/slik").json()
    assert report["report"]["label"] == DEMO_MARKER and report["report"]["synthetic"]
    assert report["report"]["subject_nik"] == "1234567890123456"
    assert report["report"]["subject_name"] == "PEMOHON DEMO"
    assert report["report"]["debtor"]["birth"] == "1990-01-01"
    assert report["request_subject"]["name"] == "PEMOHON DEMO"
    first = report["report"]["reference"]
    client.post("/api/applications/" + app["id"] + "/slik")
    assert (
        client.get("/api/applications/" + app["id"] + "/slik").json()["report"][
            "reference"
        ]
        == first
    )
    with client.app.state.repository.connect() as con:
        assert con.execute("SELECT COUNT(*) AS n FROM issuance").fetchone()["n"] == 1
    # Real raw NIK/images are AEAD-sealed, never in the DB's unencrypted bytes.
    database = client.app.state.repository.path.read_bytes()
    assert b"1234567890123456" not in database and b"\xff\xd8\xff" not in database
    assert "1234567890123456" not in json.dumps(client.app.state.repository.events())


def test_manual_approval_survives_capture_expiry_restart_and_handoff(
    client, face_image
):
    app, _, _ = prepare(client, face_image, manual=True)
    moment = service_day(client)
    reserved = client.post(
        f'/api/applications/{app["id"]}/manual/reserve',
        json={"day": moment.date().isoformat()},
        headers={"Idempotency-Key": "reservation-key-test"},
    )
    assert reserved.status_code == 200, reserved.text
    helper, headers = account(client, "helpdesk-test", "helpdesk")
    assert (
        client.post(
            f'/api/applications/{app["id"]}/manual/start', headers=headers
        ).status_code
        == 200
    )
    reviewed = client.post(
        f'/api/applications/{app["id"]}/manual/review',
        headers=headers,
        json={
            "decision": "approve",
            "capture_revision": 0,
            "note": "Dokumen dan kewenangan diperiksa pada fixture demo.",
            "identity_review": True,
            "authority_review": True,
        },
    )
    assert reviewed.status_code == 200, reviewed.text
    assert not reviewed.json()["identity_verified"]
    assert reviewed.json()["state"] == "SLIK_READY"
    directory = client.app.state.data_directory
    with TestClient(create_app(directory)) as restarted:
        restarted.headers.update(client.headers)
        assert restarted.app.state.sessions.items == {}
        body = {
            **payload(),
            "application_id": app["id"],
            "verification_id": app["verification_id"],
        }
        mismatch = restarted.post(
            "/api/registrations", json={**body, "name": "NAMA ORANG LAIN"}
        )
        assert mismatch.status_code == 409
        receipt = restarted.post("/api/registrations", json=body)
        assert receipt.status_code == 200, receipt.text
        assert (
            receipt.json()["name"] == "PEMOHON DEMO"
            and receipt.json()["identity_verified"] is False
        )
        issued = restarted.post(f'/api/applications/{app["id"]}/slik')
        assert issued.json()["state"] == "SLIK_READY"


def test_manual_rejection_and_missing_review_basis_block_issuance(client, face_image):
    app, _, _ = prepare(client, face_image, manual=True)
    moment = service_day(client)
    client.app.state.manual.reserve(
        app["id"], client.fixture_actor, moment.date().isoformat(), "reserve-rejection"
    )
    helper, _ = account(client, "rejection-helper", "helpdesk")
    client.app.state.manual.start(app["id"], helper)
    with pytest.raises(HTTPException):
        client.app.state.manual.review(
            app["id"], helper, "approve", 0, "Valid fixture note", False, True
        )
    client.app.state.manual.review(
        app["id"],
        helper,
        "reject",
        0,
        "Identitas belum memadai untuk permohonan ini.",
        False,
        False,
    )
    assert client.post(f'/api/applications/{app["id"]}/slik').status_code == 409


def test_two_applicants_compete_for_last_slot(client, face_image):
    first, _, _ = prepare(client, face_image, manual=True)
    second_owner, _ = account(client, "competing-user")
    second, _, _ = prepare(client, face_image, second_owner, True)
    moment = service_day(client)
    with client.app.state.repository.connect(write=True) as con:
        config = client.app.state.workflow.settings(con)
        config["daily_capacity"] = 1
        con.execute(
            "UPDATE flow_settings SET payload=? WHERE id=1", (json.dumps(config),)
        )

    def reserve(app, owner, key):
        try:
            return client.app.state.manual.reserve(
                app["id"], owner, moment.date().isoformat(), key
            )["state"]
        except HTTPException as exc:
            return exc.detail

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(
            pool.map(
                lambda x: reserve(*x),
                [
                    (first, client.fixture_actor, "first-last-slot"),
                    (second, second_owner, "second-last-slot"),
                ],
            )
        )
    assert outcomes.count("MANUAL_SCHEDULED") == 1 and any(
        isinstance(o, dict) and o["code"] == "CAPACITY_FULL" for o in outcomes
    )


def test_cancel_move_and_idempotency_are_atomic(client, face_image):
    app, _, _ = prepare(client, face_image, manual=True)
    moment = service_day(client)
    manual = client.app.state.manual
    day = moment.date().isoformat()
    other = (moment.date() + timedelta(days=1)).isoformat()
    first = manual.reserve(app["id"], client.fixture_actor, day, "repeat-slot-key")
    assert (
        manual.reserve(app["id"], client.fixture_actor, day, "repeat-slot-key") == first
    )
    with pytest.raises(HTTPException):
        manual.reserve(app["id"], client.fixture_actor, other, "repeat-slot-key")
    moved = manual.reserve(
        app["id"], client.fixture_actor, other, "move-slot-key", True
    )
    assert moved["reservation"]["case_id"] == first["reservation"]["case_id"]
    with client.app.state.repository.connect() as con:
        assert manual.used(con, day) == 0 and manual.used(con, other) == 1
    manual.cancel(app["id"], client.fixture_actor, "cancel-slot-key")
    with client.app.state.repository.connect() as con:
        assert manual.used(con, other) == 0
    assert (
        manual.cancel(app["id"], client.fixture_actor, "cancel-slot-key")["state"]
        == "MANUAL_PENDING"
    )


def test_weekends_holidays_hours_horizon_and_all_full(client, face_image):
    app, _, _ = prepare(client, face_image, manual=True)
    moment = service_day(client)
    manual = client.app.state.manual
    saturday = (moment.date() + timedelta(days=5)).isoformat()
    with pytest.raises(HTTPException):
        manual.reserve(app["id"], client.fixture_actor, saturday, "weekend-slot-key")
    with pytest.raises(HTTPException):
        manual.reserve(
            app["id"],
            client.fixture_actor,
            (moment.date() + timedelta(days=100)).isoformat(),
            "horizon-slot-key",
        )
    with client.app.state.repository.connect(write=True) as con:
        config = manual.flow.settings(con)
        config["holidays"] = [moment.date().isoformat()]
        con.execute(
            "UPDATE flow_settings SET payload=? WHERE id=1", (json.dumps(config),)
        )
    assert manual.calendar()["code"] == "OUTSIDE_HOURS"
    with pytest.raises(HTTPException):
        manual.reserve(
            app["id"],
            client.fixture_actor,
            moment.date().isoformat(),
            "holiday-slot-key",
        )
    manual.clock = lambda: moment.replace(hour=20)
    assert manual.calendar()["code"] == "OUTSIDE_HOURS"
    with client.app.state.repository.connect(write=True) as con:
        config["holidays"] = [d["day"] for d in manual.calendar()["days"]]
        con.execute(
            "UPDATE flow_settings SET payload=? WHERE id=1", (json.dumps(config),)
        )
    assert manual.calendar()["all_full"] is True


def test_replacing_evidence_revokes_previous_decision_and_old_report(
    client, face_image
):
    app, _, _ = prepare(client, face_image)
    client.app.state.slik.issue(app["id"], client.fixture_actor)
    resumed = client.post("/api/sessions", json={"application_id": app["id"]})
    assert resumed.status_code == 200, resumed.text
    assert client.get(f'/api/applications/{app["id"]}').json()["decision"] is None
    assert client.get(f'/api/applications/{app["id"]}/slik').status_code == 409
    with client.app.state.repository.connect() as con:
        assert (
            con.execute(
                "SELECT state FROM issuance WHERE application_id=?", (app["id"],)
            ).fetchone()["state"]
            == "REVOKED"
        )


def test_cross_owner_operator_assignment_and_configuration_authorization(
    client, face_image
):
    app, _, _ = prepare(client, face_image)
    other, headers = account(client, "intruder-account")
    assert (
        client.get("/api/applications/" + app["id"], headers=headers).status_code == 404
    )
    assert (
        client.post(
            "/api/applications/" + app["id"] + "/slik", headers=headers
        ).status_code
        == 404
    )
    assert client.get("/api/workspace", headers=headers).status_code == 403
    assert (
        client.put(
            "/api/settings",
            headers=headers,
            json={
                "face_cosine": 0.4,
                "pad_probability": 0.8,
                "deepfake_risk": 0.8,
                "blur_min": 45,
            },
        ).status_code
        == 403
    )
    with client.app.state.repository.connect() as con:
        private = client.app.state.workflow.get(con, app["id"])
        evidence = private["payload"]["evidence"][0]
    assert (
        client.get("/api/evidence/" + evidence["id"], headers=headers).status_code
        == 404
    )
    helper, hheaders = account(client, "unassigned-helper", "helpdesk")
    assert (
        client.get("/api/applications/" + app["id"], headers=hheaders).status_code
        == 404
    )
    assert (
        client.post("/api/applications/" + app["id"] + "/manual/start").status_code
        == 403
    )
    unauth = client.get("/api/workspace", headers={"Authorization": ""})
    assert unauth.status_code == 401


def test_evidence_tamper_retention_and_hmac_binding(client, face_image):
    app, _, _ = prepare(client, face_image)
    flow = client.app.state.workflow
    with client.app.state.repository.connect(write=True) as con:
        stored = flow.get(con, app["id"])
        identity = stored["payload"]["evidence"][0]
        assert stored["subject_id"] != hashlib.sha256(b"1234567890123456").hexdigest()
        original = con.execute(
            "SELECT ciphertext FROM evidence WHERE id=?", (identity["id"],)
        ).fetchone()["ciphertext"]
        con.execute("UPDATE evidence SET revision=99 WHERE id=?", (identity["id"],))
        with pytest.raises(Exception):
            flow.evidence.read(con, identity["id"])
        con.execute(
            "UPDATE evidence SET revision=0,expires=? WHERE id=?",
            (time.time() - 1, identity["id"]),
        )
    assert flow.evidence.purge() == 1
    assert client.post("/api/applications/" + app["id"] + "/slik").status_code == 410


def test_downstream_retry_uses_one_issuance_key(client, face_image):
    app, _, _ = prepare(client, face_image)
    calls = []

    class Flaky(MockSlikAdapter):
        def fetch(self, identity, key):
            calls.append(key)
            if len(calls) == 1:
                raise RuntimeError("Controlled downstream failure")
            return super().fetch(identity, key)

    client.app.state.slik.adapter = Flaky()
    assert (
        client.post("/api/applications/" + app["id"] + "/slik").json()["state"]
        == "SLIK_PENDING"
    )
    assert (
        client.post("/api/applications/" + app["id"] + "/slik").json()["state"]
        == "SLIK_READY"
    )
    assert len(set(calls)) == 1


def test_high_score_with_authority_or_proof_missing_never_issues(client, face_image):
    flow = client.app.state.workflow
    app = flow.create(client.fixture_actor)
    session = CaptureSession(
        application_id=app["id"], owner_id=client.fixture_actor["id"]
    )
    session.document = face_image
    session.document_result = {
        "fields": {"nik": "1234567890123456", "name": "USER", "birth": "1990-01-01"}
    }
    session.consumed = True
    session.liveness_result = {"passed": True}
    result = {
        "id": "invalid-proof-fixture",
        "status": "pass",
        "scores": {"face_cosine": 0.9, "kyc_face_cosine": 0.9, "ocr": 1, "liveness": 1, "deepfake": 0, "ai_reliability": True},
        "checks": complete_control_fixture(),
        "identity_verified": False,
        "nik_masked": "3456",
        "reason": "fixture",
    }
    routed = flow.ingest(session, result, face_image, face_image, [])
    assert (
        routed["routing"]["routing_score"] < 100
        and routed["state"] == "MANUAL_PENDING"
    )
    assert client.post("/api/applications/" + app["id"] + "/slik").status_code == 409


def test_helpdesk_cannot_access_another_assigned_case(client, face_image):
    app, _, _ = prepare(client, face_image, manual=True)
    moment = service_day(client)
    first, headers = account(client, "assigned-one", "helpdesk")
    second, other_headers = account(client, "assigned-two", "helpdesk")
    client.app.state.manual.reserve(
        app["id"],
        client.fixture_actor,
        moment.date().isoformat(),
        "assignment-slot-key",
    )
    client.app.state.manual.start(app["id"], first)
    assert (
        client.get("/api/applications/" + app["id"], headers=other_headers).status_code
        == 404
    )
    assert (
        client.get("/api/applications/" + app["id"], headers=headers).status_code == 200
    )


def test_real_authenticated_application_creation_and_self_scope(client):
    owner, headers = account(client, "owned-capture-user")
    created = client.post("/api/sessions", headers=headers).json()
    other, other_headers = account(client, "another-capture-user")
    assert (
        client.post(
            "/api/sessions/" + created["id"] + "/liveness/start", headers=other_headers
        ).status_code
        == 404
    )
    assert (
        client.get(
            "/api/applications/" + created["application_id"], headers=headers
        ).status_code
        == 200
    )
    app_list = client.get("/api/applications", headers=other_headers).json()
    assert app_list == []


def test_integration_handoff_requires_service_owner_and_server_subject(
    client, face_image
):
    app, _, _ = prepare(client, face_image)
    service, headers = account(client, "host-integration", "integration")
    with client.app.state.repository.connect() as con:
        stored = client.app.state.workflow.get(con, app["id"])
    body = {
        "application_id": app["id"],
        "owner_id": client.fixture_actor["id"],
        "subject_id": stored["subject_id"],
    }
    assert client.post("/api/integration/handoff", json=body).status_code == 403
    assert (
        client.post(
            "/api/integration/handoff",
            headers=headers,
            json={**body, "subject_id": "f" * 64},
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/api/integration/handoff",
            headers=headers,
            json={**body, "owner_id": "wrong-owner"},
        ).status_code
        == 409
    )
    response = client.post("/api/integration/handoff", headers=headers, json=body)
    assert response.status_code == 200 and response.json()["state"] == "SLIK_READY"


def test_decision_expiry_and_production_unverified_identity_hold_results(
    client, face_image
):
    app, _, _ = prepare(client, face_image)
    flow = client.app.state.workflow
    with flow.repository.connect(write=True) as con:
        stored = flow.get(con, app["id"])
        stored["payload"]["decision"]["expires"] = time.time() - 1
        flow.save(con, stored)
    assert client.post("/api/applications/" + app["id"] + "/slik").status_code == 409
    with flow.repository.connect(write=True) as con:
        stored = flow.get(con, app["id"])
        stored["payload"]["decision"]["expires"] = time.time() + 100
        flow.save(con, stored)
    flow.policy.mode = "production"
    assert client.post("/api/applications/" + app["id"] + "/slik").status_code == 409


def test_migrations_are_idempotent_and_capture_resume_is_bounded(client):
    repo = client.app.state.repository
    repo.migrate()
    repo.migrate()
    with repo.connect() as con:
        assert (
            con.execute("SELECT COUNT(*) AS n FROM schema_migrations").fetchone()["n"]
            == 5
        )
    public = client.post("/api/sessions").json()
    app_id = public["application_id"]
    assert (
        client.post("/api/sessions", json={"application_id": app_id}).status_code == 200
    )
    assert (
        client.post("/api/sessions", json={"application_id": app_id}).status_code == 200
    )
    assert (
        client.post("/api/sessions", json={"application_id": app_id}).status_code == 429
    )


def test_applicant_sees_no_raw_model_metrics(client, face_image):
    from app.controller.verification import applicant_result

    data = {
        "scores": {"deepfake": 0.99},
        "checks": [
            {"name": "PAD", "status": "passed", "mode": "real", "detail": {"raw": 123}},
            {"name": "ViT", "effect": "advisory"},
        ],
        "rules": {"threshold": 0.8},
        "status": "pass",
    }
    sanitized = applicant_result(data, {"id": "user", "role": "applicant"})
    assert not sanitized["scores"] and "detail" not in sanitized["checks"][0]
    assert len(sanitized["checks"]) == 1 and "rules" not in sanitized


def test_legacy_plaintext_payload_is_migrated_and_wrong_key_is_rejected(tmp_path):
    from app.model.repository import Repository

    repo = Repository(tmp_path)
    with repo.connect(write=True) as con:
        con.execute(
            "INSERT INTO results VALUES (?,?,?)",
            (
                "legacy",
                "2020-01-01",
                json.dumps(
                    {"id": "legacy", "name": "PRIVATE LEGACY NAME", "status": "manual"}
                ),
            ),
        )
    repo.migrate()
    assert repo.result("legacy")["name"] == "PRIVATE LEGACY NAME"
    assert b"PRIVATE LEGACY NAME" not in repo.path.read_bytes()
    (tmp_path / ".local.key").write_bytes(b"z" * 32)
    with pytest.raises(RuntimeError, match="Kunci enkripsi"):
        Repository(tmp_path).migrate()


def test_lost_inflight_lease_retries_same_issuance_id(client, face_image):
    app, _, _ = prepare(client, face_image)

    class Fails(MockSlikAdapter):
        def fetch(self, *args):
            raise RuntimeError("Controlled network uncertainty")

    service = client.app.state.slik
    service.adapter = Fails()
    service.issue(app["id"], client.fixture_actor)
    with service.repository.connect(write=True) as con:
        record = con.execute(
            "SELECT id FROM issuance WHERE application_id=?", (app["id"],)
        ).fetchone()
        con.execute(
            "UPDATE issuance SET state='IN_FLIGHT',lease_until=0 WHERE id=?",
            (record["id"],),
        )
    service.adapter = MockSlikAdapter()
    assert service.issue(app["id"], client.fixture_actor)["state"] == "SLIK_READY"
    assert (
        service.report(app["id"], client.fixture_actor)["report"]["reference"]
        == record["id"]
    )


def test_two_resumes_cannot_reuse_the_same_capture_generation(client):
    start = client.post("/api/sessions").json()
    flow = client.app.state.workflow
    owner = client.fixture_actor
    flow.invalidate(start["application_id"], owner, 1, new_capture=True)
    with pytest.raises(HTTPException) as stale:
        flow.invalidate(start["application_id"], owner, 1, new_capture=True)
    assert stale.value.status_code == 409
    assert (
        client.post("/api/sessions/" + start["id"] + "/liveness/start").status_code
        == 409
    )


def test_missing_mandatory_fields_never_autoapprove(monkeypatch):
    policy = ScorePolicy()
    monkeypatch.setattr(policy.calibrator, "score", lambda raw: (100, {}))
    assert (
        policy.route({"status": "pass", "scores": {}, "checks": complete_control_fixture()}, {})["decision"]
        == "TECHNICAL_PENDING"
    )


def test_manual_operator_may_publish_own_approved_case_but_not_read_finances(
    client, face_image
):
    app, _, _ = prepare(client, face_image, manual=True)
    moment = service_day(client)
    user, headers = account(client, "publishing-helper", "helpdesk")
    client.app.state.manual.reserve(
        app["id"], client.fixture_actor, moment.date().isoformat(), "publish-slot-test"
    )
    client.app.state.manual.start(app["id"], user)
    client.app.state.manual.review(
        app["id"],
        user,
        "approve",
        0,
        "Pemeriksaan fixture dokumen dan kewenangan.",
        True,
        True,
    )
    assert (
        client.post("/api/applications/" + app["id"] + "/slik", headers=headers).json()[
            "state"
        ]
        == "SLIK_READY"
    )
    assert (
        client.get(
            "/api/applications/" + app["id"] + "/slik", headers=headers
        ).status_code
        == 404
    )


def test_bearer_logout_revokes_the_actual_session(client):
    user, headers = account(client, "logout-fixture")
    assert client.post("/api/auth/logout", headers=headers).status_code == 200
    assert client.get("/api/auth/me", headers=headers).status_code == 401


def test_browser_owner_without_login_and_staff_cookie_isolation(client):
    client.headers.pop("Authorization", None)
    public = {"X-Workspace-Mode": "public"}
    operator = {"X-Workspace-Mode": "operator"}
    guest = client.post("/api/auth/guest", headers=public)
    assert guest.status_code == 200
    who = guest.json()["principal"]
    assert who["role"] == "applicant" and who["guest"]
    cookie = client.cookies["mock_id_guest"]
    assert "HttpOnly" in guest.headers["set-cookie"]
    assert (
        client.post("/api/auth/guest", headers=public).json()["principal"]["id"]
        == who["id"]
    )
    session = client.post("/api/sessions", json={}, headers=public).json()
    assert session["application_id"]
    assert len(client.get("/api/applications", headers=public).json()) == 1
    assert client.get("/api/workspace", headers=public).status_code == 403
    assert client.get("/api/auth/me", headers=operator).status_code == 401
    client.app.state.auth.create_user(
        "staff-cookie-test", "fixture-password-123", "helpdesk"
    )
    assert (
        client.post(
            "/api/auth/login",
            json={"login": "staff-cookie-test", "password": "fixture-password-123"},
            headers=operator,
        ).status_code
        == 200
    )
    assert (
        client.get("/api/auth/me", headers=operator).json()["principal"]["role"]
        == "helpdesk"
    )
    assert (
        client.get("/api/auth/me", headers=public).json()["principal"]["id"]
        == who["id"]
    )
    client.post("/api/auth/logout", headers=operator)
    assert client.cookies["mock_id_guest"] == cookie
    assert (
        client.get("/api/applications", headers=public).json()[0]["id"]
        == session["application_id"]
    )
    # A fresh browser has neither the capability nor access to its application.
    client.cookies.clear()
    stranger = client.post("/api/auth/guest", headers=public).json()["principal"]
    assert stranger["id"] != who["id"]
    assert (
        client.get(
            "/api/applications/" + session["application_id"], headers=public
        ).status_code
        == 404
    )


def test_automatic_today_quota_full_then_next_workday_without_recapture(
    client, face_image
):
    now = service_day(client)
    flow, manual = client.app.state.workflow, client.app.state.manual
    with flow.repository.connect(write=True) as con:
        cfg = flow.settings(con)
        cfg["daily_capacity"] = 1
        con.execute("UPDATE flow_settings SET payload=? WHERE id=1", (json.dumps(cfg),))
    a, _, _ = prepare(client, face_image, manual=True)
    other, _ = account(client, "auto-slot-other")
    b, _, _ = prepare(client, face_image, other, manual=True)
    original = flow.snapshot(b["id"], other)["capture_revision"]
    booked = manual.admit_today(a["id"], client.fixture_actor)
    assert (
        booked["state"] == "MANUAL_SCHEDULED"
        and booked["manual_admission"]["code"] == "RESERVED"
    )
    again = manual.admit_today(a["id"], client.fixture_actor)
    assert again["reservation"]["case_id"] == booked["reservation"]["case_id"]
    full = manual.admit_today(b["id"], other)
    assert (
        full["state"] == "MANUAL_PENDING"
        and full["manual_admission"]["code"] == "CAPACITY_FULL"
    )
    assert not full["reservation"]
    manual.clock = lambda: now + timedelta(days=1)
    next_day = manual.admit_today(b["id"], other)
    assert next_day["state"] == "MANUAL_SCHEDULED"
    assert next_day["capture_revision"] == original
    with flow.repository.connect() as con:
        assert manual.used(con, now.date().isoformat()) == 1
        assert manual.used(con, (now + timedelta(days=1)).date().isoformat()) == 1


def test_auto_admission_races_last_slot_and_skips_weekend(client, face_image):
    moment = service_day(client)
    manual, flow = client.app.state.manual, client.app.state.workflow
    with flow.repository.connect(write=True) as con:
        cfg = flow.settings(con)
        cfg["daily_capacity"] = 1
        con.execute("UPDATE flow_settings SET payload=? WHERE id=1", (json.dumps(cfg),))
    other, _ = account(client, "auto-race-other")
    a, _, _ = prepare(client, face_image, manual=True)
    b, _, _ = prepare(client, face_image, other, manual=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda pair: manual.admit_today(*pair),
                [(a["id"], client.fixture_actor), (b["id"], other)],
            )
        )
    assert sorted(r["state"] for r in results) == ["MANUAL_PENDING", "MANUAL_SCHEDULED"]
    loser = next(r for r in results if r["state"] == "MANUAL_PENDING")
    owner = other if loser["id"] == b["id"] else client.fixture_actor
    manual.clock = lambda: moment + timedelta(days=5)
    closed = manual.admit_today(loser["id"], owner)
    assert closed["manual_admission"]["code"] == "OUTSIDE_HOURS"
    assert (
        closed["manual_admission"]["next_working_day"]
        == (moment + timedelta(days=7)).date().isoformat()
    )


def test_synthetic_report_sections_and_twelve_month_history():
    report = MockSlikAdapter().fetch(
        {"nik": "0000000000000000", "name": "PEMOHON FIXTURE", "birth": "1990-01-01"},
        "SLIK-DEMO-TEST",
    )
    assert report["synthetic"] and report["label"] == DEMO_MARKER
    assert report["debtor"]["type"] == "Perseorangan"
    assert "PRIVATE" not in json.dumps(report)
    assert report["summary"]["total_outstanding"] == sum(
        f["outstanding"] for f in report["facilities"]
    )
    for f in report["facilities"]:
        assert len(f["history"]) == 12
        assert len({h["month"] for h in f["history"]}) == 12
        assert all(1 <= h["quality"] <= 5 for h in f["history"])
        assert isinstance(f["collateral"], list) and isinstance(f["guarantors"], list)


def test_auto_admission_after_cancel_takes_real_slot_again(client, face_image):
    service_day(client)
    app, _, _ = prepare(client, face_image, manual=True)
    manual = client.app.state.manual
    first = manual.admit_today(app["id"], client.fixture_actor)
    manual.cancel(app["id"], client.fixture_actor, "cancel-auto-admission")
    rebooked = manual.admit_today(app["id"], client.fixture_actor)
    assert rebooked["state"] == "MANUAL_SCHEDULED"
    assert rebooked["reservation"]["case_id"] == first["reservation"]["case_id"]
    with client.app.state.repository.connect() as con:
        assert manual.used(con, first["reservation"]["day"]) == 1


def test_capacity_idempotency_response_is_encrypted_at_rest(client, face_image):
    moment = service_day(client)
    app, _, _ = prepare(client, face_image, manual=True)
    manual = client.app.state.manual
    key = "protected-capacity-response"
    first = manual.reserve(
        app["id"], client.fixture_actor, moment.date().isoformat(), key
    )
    with client.app.state.repository.connect() as con:
        raw = con.execute(
            "SELECT response FROM idempotency WHERE key=?", (key,)
        ).fetchone()["response"]
    assert "PEMOHON DEMO" not in raw and "__sealed__" in raw
    assert (
        manual.reserve(app["id"], client.fixture_actor, moment.date().isoformat(), key)
        == first
    )


@pytest.mark.parametrize(
    "score,decision",
    [
        (74.99, "REJECTED"),
        (75, "MANUAL_PENDING"),
        (94.99, "MANUAL_PENDING"),
        (95, "AUTO_APPROVED"),
    ],
)
def test_calibrated_production_keeps_previous_thresholds(monkeypatch, score, decision):
    policy = ScorePolicy()
    policy.mode = "production"
    policy.calibrator.calibrated = True
    monkeypatch.setattr(policy.calibrator, "score", lambda _: (score, {}))
    routed = policy.route(
        {"status": "pass", "scores": {}, "checks": complete_control_fixture()}, {key: True for key in REQUIRED_CONTROLS}
    )
    assert routed["decision"] == decision and routed["automatic_threshold"] == 95
    assert not routed["demo_model_override"]


def test_operator_workspace_reports_routing_policy_without_exposing_it_to_guests(
    client,
):
    operator = client.get("/api/workspace")
    assert operator.status_code == 200
    assert operator.json()["routing_policy"]["automatic_threshold"] == 50
    assert operator.json()["routing_policy"]["mode"] == "demo"
    assert client.get(
        "/api/workspace", headers={"X-Workspace-Mode": "public", "Authorization": ""}
    ).status_code in [401, 403]
