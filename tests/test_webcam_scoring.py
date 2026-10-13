"""Capture regression tests, not a claim of calibrated biometric accuracy."""

from types import SimpleNamespace

import numpy as np
import pytest

from app.services.antispoof import summarize_pad
from app.services.liveness import LiveCapture
from test_verdict_policy import policy_case


def test_one_low_frame_does_not_poison_demo_but_remains_in_strict_evidence():
    values = [0.97, 0.98, 0.0001, 0.96, 0.99]
    demo = summarize_pad(values, 0.8, demo=True)
    strict = summarize_pad(values, 0.8)
    assert demo["score"] == 0.97 and demo["passed"]
    assert demo["minimum"] == 0.0001 and not demo["strict_passed"]
    assert demo["samples"] == values and demo["below_threshold_count"] == 1
    assert strict["score"] == 0.0001 and not strict["passed"]


def test_sustained_low_samples_and_insufficient_evidence_are_not_smoothed_to_pass():
    assert not summarize_pad([0.01, 0.02, 0.03, 0.99, 0.98], 0.8, demo=True)["passed"]
    assert summarize_pad([0.01, 0.99], 0.8, demo=True)["score"] == 0.01
    for values in [[], [float("nan")], [float("inf")], [-0.01], [1.01], [True]]:
        with pytest.raises(ValueError):
            summarize_pad(values, 0.8, demo=True)


def test_temporal_pad_does_not_complete_missing_gestures_and_clears_only_pad_warning():
    capture = LiveCapture(["blink", "smile", "turn"])
    capture.pad_review_enabled = True
    capture.rules = {"pad_probability": 0.8}
    for score in [0.98, 0.01, 0.99, 0.97, 0.96]:
        capture.record_pad(score)
    feedback = {"ready": True, "warnings": [{"code": "pad_review"}, {"code": "mask"}]}
    result = capture.result(feedback)
    assert result["pad_probability"] == 0.97 and result["pad_passed"]
    assert not result["done"] and not result["passed"]
    assert result["feedback"]["warnings"] == [{"code": "mask"}]
    assert len(feedback["warnings"]) == 2  # Caller data is not mutated.
    fresh = LiveCapture(["blink"])
    assert fresh.pad_samples == [] and fresh.pad_min == 1


def test_stream_median_survives_low_raw_minimum_but_strict_mode_keeps_it(
    client, policy_case
):
    state, _run, session = policy_case
    verifier = client.app.state.verifier
    selfie = session.document.copy()
    holding = selfie.copy()
    session.liveness_result = {
        "passed": True,
        "stream": True,
        "pad_probability": 0.96,
        "pad_summary": summarize_pad([0.97, 0.0001, 0.96, 0.99, 0.95], 0.8, demo=True),
        "live": {"passed": True},
        "continuity": [0.95],
    }
    result = verifier.run(session, selfie, holding, [], [])
    assert result["status"] == "pass" and result["scores"]["liveness"] == 0.96
    verifier.pad_review_enabled = False
    strict = verifier.run(session, selfie, holding, [], [])
    assert strict["status"] == "attack" and strict["scores"]["liveness"] == 0.0001


def test_pipeline_classifier_receives_original_images_never_arcface_alignment(
    client, policy_case
):
    _state, _run, session = policy_case
    verifier = client.app.state.verifier
    selfie = session.document.copy()
    holding = selfie.copy()
    session.liveness_result = {
        "passed": True,
        "stream": True,
        "pad_probability": 0.97,
        "live": {"passed": True},
        "continuity": [0.95],
    }
    images = []

    def score(image):
        images.append(image)
        return {"fake_probability": 0.001, "real_probability": 0.999}

    def forbidden(*args):
        raise AssertionError("ArcFace alignment must not feed the image classifier")

    verifier.deepfake = SimpleNamespace(score=score)
    verifier.face.feature = forbidden
    result = verifier.run(session, selfie, holding, [], [])
    assert result["status"] == "pass" and result["scores"]["deepfake"] == 0.001
    assert images[0] is selfie and images[1] is holding
    diagnostic = next(
        c for c in result["checks"] if c["name"] == "Classifier gambar AI (diagnostik)"
    )
    assert diagnostic["detail"]["input_scope"] == "full_camera_image"


def test_holding_preview_low_pad_never_overrides_visibility(client):
    verifier = client.app.state.verifier
    verifier.face = SimpleNamespace(faces=lambda _: [[0, 0, 100, 100]])
    verifier.pad = SimpleNamespace(score=lambda *_: {"live_probability": 0.01})
    verifier.visibility = SimpleNamespace(
        inspect=lambda *_: {
            "ready": False,
            "face_box": [0, 0, 100, 100],
            "warnings": [{"code": "mask", "message": "Masker"}],
        }
    )
    result = verifier.inspect_capture(None, holding=True)
    assert not result["ready"] and result["warnings"][0]["code"] == "mask"
    assert result["pad_scope"] == "holding_diagnostic"
    verifier.pad_review_enabled = False
    strict = verifier.inspect_capture(None, holding=True)
    assert not strict["ready"] and any(
        w["code"] == "spoof_risk" for w in strict["warnings"]
    )
