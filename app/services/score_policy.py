"""Routing is neither identity probability nor a mean of raw model scores."""

import hashlib
import json
import math
import os
from pathlib import Path
from app.services.face import FACE_MODEL_ID
from app.services.assessment import assess_controls
from app.config import ROOT

DEMO_POINTS = {
    "face": [(-1, 0), (0.2, 40), (0.4, 75), (0.5, 92), (0.6, 97), (0.85, 100)],
    "pad": [(0, 0), (0.8, 75), (0.9, 92), (0.95, 97), (0.995, 100)],
    "ocr": [(0, 0), (0.6, 60), (0.8, 85), (0.9, 95), (1, 100)],
    "controls": [(0, 0), (1, 100)],
}
REQUIRED_CONTROLS = {
    "session_nonce_proof",
    "document_identity_complete",
    "document_face_liveness_pad",
    "no_security_rejection",
    "applicant_authority",
    "approved_identity_procedure",
}

# In the uncalibrated demo, measured PAD contributes to the combined score.
# Identity, face matching, motion, visibility and bound evidence remain gates.
# Production and calibrated policies still require every control to pass.
DEMO_PAD_CONTROLS = {"Anti-spoof / PAD", "PAD foto memegang KTP"}
DEMO_PAD_COMPOSITES = {"document_face_liveness_pad", "approved_identity_procedure"}
# Preserve relative weights of the four required components after removing AI.
WEIGHTS = {
    "face": 0.25 / 0.90,
    "pad": 0.25 / 0.90,
    "ocr": 0.10 / 0.90,
    "controls": 0.30 / 0.90,
}
FEATURE_POLICY = "core-controls-v2-pad-min-geometry-ai-optional"


def calibration_contract():
    manifest = json.loads((ROOT / "model-manifest.json").read_text())
    # OCR, detectors, landmarks and visibility also affect control coverage.
    return {
        item["file"]: item["sha256"]
        for item in manifest
        if item["file"] != "deepfake.onnx"
    }


def mapped(value, points):
    if value <= points[0][0]:
        return points[0][1]
    for (x, y), (nx, ny) in zip(points, points[1:]):
        if value <= nx:
            return y + (value - x) / (nx - x) * (ny - y)
    return points[-1][1]


class ScoreCalibrator:
    def __init__(self):
        self.version = "demo-routing-v8-pad-score-demo"
        self.calibrated = False
        self.points = DEMO_POINTS
        self.weights = WEIGHTS
        configured = os.getenv("MOCK_ID_CALIBRATION_FILE")
        approved_sha = os.getenv("MOCK_ID_CALIBRATION_SHA256")
        if configured:
            raw = Path(configured).read_bytes()
            if not approved_sha or hashlib.sha256(raw).hexdigest() != approved_sha:
                raise ValueError(
                    "Artefak kalibrasi tidak cocok dengan SHA-256 yang disetujui."
                )
            artifact = json.loads(raw)
            if (
                not artifact.get("evaluation_report")
                or not artifact.get("approved_by")
                or artifact.get("schema") != 2
                or artifact.get("feature_policy") != FEATURE_POLICY
                or artifact.get("model_sha256") != calibration_contract()
                or artifact.get("face_model") != FACE_MODEL_ID
            ):
                raise ValueError(
                    "Artefak kalibrasi schema 2 membutuhkan evaluasi, persetujuan, seluruh model dan kontrak fitur yang sesuai."
                )
            for name in WEIGHTS:
                points = artifact["points"][name]
                if len(points) < 2 or any(
                    len(point) != 2
                    or any(
                        type(v) not in [float, int] or not math.isfinite(v)
                        for v in point
                    )
                    for point in points
                ):
                    raise ValueError("Pemetaan tidak valid.")
                if any(
                    a[0] >= b[0] or a[1] > b[1] for a, b in zip(points, points[1:])
                ) or any(not 0 <= p[1] <= 100 for p in points):
                    raise ValueError("Pemetaan harus monotonic.")
            weights = artifact["weights"]
            if (
                set(weights) != set(WEIGHTS)
                or any(not math.isfinite(v) or v <= 0 for v in weights.values())
                or abs(sum(weights.values()) - 1) > 1e-9
            ):
                raise ValueError("Bobot kalibrasi tidak valid.")
            self.version = artifact["version"]
            self.calibrated = True
            self.points = artifact["points"]
            self.weights = weights

    def score(self, raw):
        required = [
            "face_cosine",
            "kyc_face_cosine",
            "liveness",
            "ocr",
            "validation_coverage",
        ]
        if any(
            type(raw.get(k)) not in [float, int] or not math.isfinite(raw[k])
            for k in required
        ):
            return None, None
        values = {
            "face": min(raw["face_cosine"], raw["kyc_face_cosine"]),
            "pad": raw["liveness"],
            "ocr": raw["ocr"],
            "controls": raw["validation_coverage"],
        }
        if (
            not -1 <= values["face"] <= 1
            or not 0 <= values["pad"] <= 1
            or not 0 <= values["ocr"] <= 1
            or not 0 <= values["controls"] <= 1
        ):
            return None, None
        components = {
            name: mapped(value, self.points[name]) for name, value in values.items()
        }
        return (
            min(
                100.0,
                max(
                    0.0,
                    sum(self.weights[name] * components[name] for name in self.weights),
                ),
            ),
            components,
        )


class ScorePolicy:
    def __init__(self):
        self.calibrator = ScoreCalibrator()
        self.mode = os.getenv("MOCK_ID_MODE", "demo")

    @property
    def automatic_threshold(self):
        return 50 if self.mode == "demo" and not self.calibrator.calibrated else 95

    @property
    def demo_pad_score_routing(self):
        return self.mode == "demo" and not self.calibrator.calibrated

    def pad_score_eligible(self, result, mandatory, assessment):
        if not self.demo_pad_score_routing or result["status"] not in {"pass", "manual"}:
            return False
        if assessment["incomplete"] or not REQUIRED_CONTROLS.issubset(mandatory):
            return False
        if any(type(v) is not bool for v in mandatory.values()):
            return False
        if any(not value for key, value in mandatory.items() if key not in DEMO_PAD_COMPOSITES):
            return False
        blocked = set(assessment["blocked_controls"])
        pad_blocked = blocked & DEMO_PAD_CONTROLS
        if not pad_blocked or not blocked.issubset(DEMO_PAD_CONTROLS | DEMO_PAD_COMPOSITES):
            return False
        # A missing measurement or a failed capture cannot become a demo pass.
        for check in result.get("checks", []):
            if check.get("name") not in pad_blocked:
                continue
            detail = check.get("detail") or {}
            probability = (detail.get("score") if check["name"] == "Anti-spoof / PAD"
                           else (detail.get("sample") or {}).get("live_probability"))
            threshold = detail.get("threshold")
            if (check.get("status") not in {"failed", "review"}
                    or type(probability) not in [int, float] or not math.isfinite(probability)
                    or not 0 <= probability <= 1
                    or type(threshold) not in [int, float] or not math.isfinite(threshold)
                    or not 0 <= threshold <= 1):
                return False
            if check["name"] == "Anti-spoof / PAD" and probability != result.get("scores", {}).get("liveness"):
                return False
        return True

    def route(self, result, mandatory):
        assessment = assess_controls(result, mandatory, demo=self.mode == "demo")
        raw = {
            **result.get("scores", {}),
            "validation_coverage": assessment["coverage"],
        }
        score, components = self.calibrator.score(raw)
        state = result["status"]
        demo_override = (score is not None and score >= self.automatic_threshold
                         and self.pad_score_eligible(result, mandatory, assessment))
        if state == "attack" or mandatory.get("no_security_rejection") is False:
            decision = "REJECTED"
            security = True
        elif state == "capture":
            decision = "CAPTURE_RETRY"
            security = False
        elif (
            state == "technical"
            or score is None
            or not REQUIRED_CONTROLS.issubset(mandatory)
            or any(type(v) is not bool for v in mandatory.values())
        ):
            decision = "TECHNICAL_PENDING"
            security = False
        elif demo_override:
            decision = "AUTO_APPROVED"
            security = False
        elif (
            not assessment["all_passed"]
            or not all(mandatory.values())
            or state != "pass"
        ):
            decision = (
                "TECHNICAL_PENDING" if assessment["incomplete"] else "MANUAL_PENDING"
            )
            security = False
        elif self.mode == "demo" and not self.calibrator.calibrated:
            decision = (
                "AUTO_APPROVED"
                if score >= self.automatic_threshold
                else "MANUAL_PENDING"
            )
            security = False
        elif score < 75:
            decision = "REJECTED"
            security = False
        elif (
            score >= 95
            and all(mandatory.values())
            and (self.mode == "demo" or self.calibrator.calibrated)
        ):
            decision = "AUTO_APPROVED"
            security = False
        else:
            decision = "MANUAL_PENDING"
            security = False
        return {
            "demo_routing_score": score if not self.calibrator.calibrated else None,
            "routing_score": score,
            "components": components,
            "weights": dict(self.calibrator.weights),
            "contributions": (
                {
                    name: self.calibrator.weights[name] * value
                    for name, value in components.items()
                }
                if components
                else None
            ),
            "assessment": assessment,
            "formula": "sum(component_points * weight); demo PAD uses aggregate score; other required controls must pass" if self.demo_pad_score_routing else "sum(component_points * weight); automatic approval also requires every control passing",
            "ai_evidence_usable": raw.get("ai_reliability") is True,
            "ai_validation_required": False,
            "calibrated": self.calibrator.calibrated,
            "policy_version": self.calibrator.version,
            "mandatory": mandatory,
            "decision": decision,
            "security_review": security,
            "automatic_threshold": self.automatic_threshold,
            "demo_model_override": bool(demo_override),
            "demo_pad_score_routing": self.demo_pad_score_routing,
            "demo_override_controls": sorted(set(assessment["blocked_controls"]) & DEMO_PAD_CONTROLS) if demo_override else [],
            "scope": "synthetic_only" if self.mode == "demo" else "production",
        }
