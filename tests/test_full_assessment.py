"""Explicit missing/uncertain control gates and all-feature score arithmetic."""

from copy import deepcopy
from types import SimpleNamespace

import numpy as np
import pytest

from app.services.assessment import CONTROL_NAMES, assess_controls
from app.services.deepfake import DeepfakeService
from app.services.score_policy import ScorePolicy, REQUIRED_CONTROLS, ScoreCalibrator
from conftest import complete_control_fixture
from test_verdict_policy import policy_case


def case():
    return {
        "status": "pass",
        "checks": complete_control_fixture(),
        "scores": {
            "face_cosine": 0.62,
            "kyc_face_cosine": 0.93,
            "liveness": 0.95,
            "ocr": 0.98,
            "deepfake": 0.01,
            "ai_reliability": True,
        },
    }, {k: True for k in REQUIRED_CONTROLS}


@pytest.mark.parametrize("name", CONTROL_NAMES)
def test_every_control_blocks_approval_even_with_a_high_numeric_score(name):
    result, mandatory = case()
    policy = ScorePolicy()
    baseline = policy.route(result, mandatory)
    assert baseline["decision"] == "AUTO_APPROVED"
    changed = next(c for c in result["checks"] if c["name"] == name)
    changed.update(status="review", effect="advisory")  # Cannot hide via advisory.
    review = policy.route(result, mandatory)
    assert review["decision"] == "MANUAL_PENDING" and not review["demo_model_override"]
    assert review["routing_score"] < baseline["routing_score"]
    assert name in review["assessment"]["blocked_controls"]


def test_missing_duplicate_extra_controls_and_mock_source_cannot_disappear():
    result, mandatory = case()
    result["checks"].pop()
    assert ScorePolicy().route(result, mandatory)["decision"] == "TECHNICAL_PENDING"
    result, mandatory = case()
    result["checks"].append(deepcopy(result["checks"][0]))
    assert ScorePolicy().route(result, mandatory)["decision"] == "TECHNICAL_PENDING"
    result, mandatory = case()
    result["checks"].append(
        {
            "name": "New unknown validation",
            "status": "review",
            "mode": "real",
            "effect": "advisory",
        }
    )
    assert not assess_controls(result, mandatory, demo=True)["all_passed"]
    duk = next(c for c in result["checks"] if c["name"] == "Dukcapil")
    duk.update(mode="mock", detail={"simulated": True})
    assert (
        "Dukcapil" in assess_controls(result, mandatory, demo=False)["blocked_controls"]
    )


def test_weighted_sum_and_ai_direction_are_auditable_and_not_identity_probability():
    result, mandatory = case()
    routing = ScorePolicy().route(result, mandatory)
    assert sum(routing["weights"].values()) == pytest.approx(1)
    assert sum(routing["contributions"].values()) == pytest.approx(
        routing["routing_score"]
    )
    assert "ai" not in routing["components"] and not routing["calibrated"]
    result["scores"]["deepfake"] = 0.5
    lower = ScorePolicy().route(result, mandatory)
    assert lower["routing_score"] == routing["routing_score"]
    result["scores"]["ai_reliability"] = False
    unusable = ScorePolicy().route(result, mandatory)
    assert "ai" not in unusable["components"]
    # AI reliability is optional and never gates the complete core evidence.
    assert unusable["decision"] == "AUTO_APPROVED"


def test_ai_context_disagreement_is_uncertainty_not_a_high_score_selected_for_pass():
    service = DeepfakeService.__new__(DeepfakeService)
    values = iter(
        [
            {"fake_probability": 0.01, "real_probability": 0.99},
            {"fake_probability": 0.99, "real_probability": 0.01},
        ]
    )
    inputs = []

    def score(image):
        inputs.append(image.shape)
        return next(values)

    service.score = score
    result = service.assess(np.zeros((720, 1280, 3), np.uint8), [400, 100, 300, 400])
    assert inputs == [(720, 1280, 3), (440, 340, 3)]
    assert (
        result["fake_probability"] == 0.01
        and result["context_fake_probability"] == 0.99
    )
    assert not result["reliable"] and result["disagreement"] == 0.98


def test_bound_recording_is_not_penalized_twice_by_its_first_selfie(
    client, policy_case
):
    state, _run, session = policy_case
    verifier = client.app.state.verifier
    from app.services.antispoof import summarize_pad

    summary = summarize_pad([0.04, 0.95, 0.96, 0.97, 0.98], 0.8, demo=True)
    session.liveness_result = {
        "passed": True,
        "stream": True,
        "pad_probability": summary["score"],
        "pad_summary": summary,
        "live": {"passed": True},
        "continuity": [0.96],
    }
    selfie, holding = session.document.copy(), session.document.copy()
    verifier.pad.score = lambda image, face: {
        "live_probability": 0.04 if image is selfie else 0.99
    }
    result = verifier.run(session, selfie, holding, [], [])
    assert result["scores"]["liveness"] == 0.96
    pad = next(c for c in result["checks"] if c["name"] == "Anti-spoof / PAD")
    assert pad["detail"]["samples"][0]["live_probability"] == 0.04
    assert pad["detail"]["minimum_live_probability"] == 0.04
    assert result["status"] == "pass"


def test_ai_disagreement_does_not_block_valid_core_evidence(
    client, face_image, policy_case
):
    state, run, session = policy_case
    state["ai_reliable"] = False
    result = run()
    assert result["status"] == "pass" and result["scores"]["ai_reliability"] is False
    session.document_result["fields"].update(name="TEST", birth="1990-01-01")
    session.proof_checked_revision = session.revision
    session.liveness_selfie = "bound-protocol-fixture"
    workflow = client.app.state.workflow
    workflow.attest(session.application_id, client.fixture_actor, True)
    app = workflow.ingest(session, result, face_image, face_image, [])
    assert (
        app["state"] == "AUTO_APPROVED" and not app["routing"]["ai_validation_required"]
    )
    assert app["routing"]["assessment"]["all_passed"]
    issued = client.app.state.slik.issue(app["id"], client.fixture_actor)
    assert issued["state"] == "SLIK_READY"
    assert client.get(
        "/api/applications/" + app["id"] + "/slik.pdf"
    ).content.startswith(b"%PDF")


def test_offline_evaluation_needs_genuine_and_attack_labels_and_does_not_approve_calibration():
    from scripts.evaluate_kyc import evaluate

    result, mandatory = case()
    good = {"label": "genuine", "result": result, "mandatory": mandatory}
    with pytest.raises(ValueError, match="satu kelas"):
        evaluate([good])
    bad = deepcopy(good)
    bad["label"] = "attack"
    bad["result"]["status"] = "attack"
    report = evaluate([good, bad])
    assert report["attack_auto_approval_rate"] == 0
    assert report["genuine_auto_approval_rate"] == 1
    assert not report["calibrated"] and report["sample_counts"] == {
        "genuine": 1,
        "attack": 1,
    }


def test_geometry_jitter_is_stabilized_without_score_selection_or_stale_face_reuse():
    from app.services.liveness import LiveCapture

    capture = LiveCapture(["blink"])
    original = np.array([200.0, 100.0, 300.0, 400.0, 210.0, 120.0])
    for dx in [0, 4, -4]:
        face = original.copy()
        face[0] += dx
        stabilized = capture.stabilize_pad_face(face)
    assert stabilized[0] == 200
    assert np.array_equal(stabilized[4:], face[4:])
    moved = original.copy()
    moved[0] += 100
    assert capture.stabilize_pad_face(moved)[0] == 300
    capture.pause_detection()
    assert capture.pad_box_history == []
    assert capture.stabilize_pad_face(original)[0] == 200
