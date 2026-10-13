"""Optional AI cannot block approval through score, coverage, load or workflow."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.services.score_policy import ScorePolicy, REQUIRED_CONTROLS
from app.services.pipeline import MODEL_FILES
from app.services.assets import verify_assets
from conftest import complete_control_fixture
from test_verdict_policy import policy_case


def core_result():
    return {
        "status": "pass",
        "checks": complete_control_fixture(),
        "scores": {
            "face_cosine": 0.62,
            "kyc_face_cosine": 0.93,
            "liveness": 0.99,
            "ocr": 0.98,
        },
    }


@pytest.mark.parametrize(
    "state",
    ["missing", "review", "unavailable", "failed", "duplicate", "invalid_score"],
)
def test_ai_diagnostics_never_change_score_or_required_coverage(state):
    result = core_result()
    mandatory = {k: True for k in REQUIRED_CONTROLS}
    policy = ScorePolicy()
    baseline = policy.route(result, mandatory)
    result["scores"].update(
        deepfake=float("nan") if state == "invalid_score" else 0.999,
        ai_reliability=False,
    )
    if state != "missing":
        result["checks"].append(
            {
                "name": "Classifier gambar AI (diagnostik)",
                "status": state,
                "effect": "required",
                "mode": "real",
            }
        )
    if state == "duplicate":
        result["checks"].append(deepcopy(result["checks"][-1]))
    updated = policy.route(result, mandatory)
    assert updated["decision"] == baseline["decision"] == "AUTO_APPROVED"
    assert updated["routing_score"] == baseline["routing_score"]
    assert updated["assessment"]["coverage"] == baseline["assessment"]["coverage"] == 1
    assert "ai" not in updated["weights"] and not updated["ai_validation_required"]


@pytest.mark.parametrize("error", [False, True])
def test_high_or_unavailable_ai_still_issues_pdf_when_core_valid(
    client, face_image, policy_case, error
):
    state, run, session = policy_case
    state.update(fake=0.999, ai_reliable=False, diagnostic_error=error)
    result = run()
    assert result["status"] == "pass"
    check = next(
        c for c in result["checks"] if c["name"] == "Classifier gambar AI (diagnostik)"
    )
    assert check["effect"] == "advisory" and check["status"] == (
        "unavailable" if error else "review"
    )
    session.document_result["fields"].update(name="PEMOHON TEST", birth="1990-01-01")
    session.proof_checked_revision = session.revision
    session.liveness_selfie = "protocol-proof-binding"
    workflow = client.app.state.workflow
    workflow.attest(session.application_id, client.fixture_actor, True)
    app = workflow.ingest(session, result, face_image, face_image, [])
    assert (
        app["state"] == "AUTO_APPROVED" and app["routing"]["assessment"]["all_passed"]
    )
    assert not app["routing"]["ai_validation_required"]
    issued = client.app.state.slik.issue(app["id"], client.fixture_actor)
    assert issued["state"] == "SLIK_READY"
    assert client.get("/api/applications/" + app["id"] + "/slik.pdf").status_code == 200


def test_optional_ai_load_failure_does_not_change_core_readiness_or_repeat_loading(
    client, monkeypatch
):
    import app.services.pipeline as pipeline

    verifier = client.app.state.verifier
    verifier.face = verifier.pad = verifier.landmarks = verifier.visibility = (
        SimpleNamespace()
    )
    verifier.assets_verified = True
    monkeypatch.setattr(verifier, "availability", lambda: {"files": {"core": True}})
    calls = []

    def check(*, exclude=(), only=None):
        calls.append(only)
        return ["deepfake.onnx missing"] if only else []

    monkeypatch.setattr(pipeline, "verify_assets", check)
    verifier.load()
    verifier.load()
    assert verifier.deepfake is None and verifier.ai_load_attempted
    assert verifier.diagnostic_error and calls == [("deepfake.onnx",)]
    assert "deepfake.onnx" not in MODEL_FILES


def test_asset_validation_can_isolate_optional_corrupt_model(tmp_path, monkeypatch):
    import hashlib
    import json
    from app.services import assets

    monkeypatch.setattr(assets, "ROOT", tmp_path)
    monkeypatch.setattr(assets, "WEIGHTS", tmp_path)
    (tmp_path / "core.onnx").write_bytes(b"core")
    (tmp_path / "deepfake.onnx").write_bytes(b"corrupt")
    (tmp_path / "model-manifest.json").write_text(
        json.dumps(
            [
                {"file": "core.onnx", "sha256": hashlib.sha256(b"core").hexdigest()},
                {
                    "file": "deepfake.onnx",
                    "sha256": hashlib.sha256(b"expected").hexdigest(),
                },
            ]
        )
    )
    assert verify_assets(exclude=("deepfake.onnx",)) == []
    assert verify_assets(only=("deepfake.onnx",)) == [
        "deepfake.onnx (checksum tidak cocok)"
    ]
