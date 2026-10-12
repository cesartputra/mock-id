"""Routing is neither identity probability nor a mean of raw model scores."""

import hashlib
import json
import math
import os
from pathlib import Path
from app.services.face import FACE_MODEL_ID

DEMO_POINTS = {
    "face": [(-1, 0), (0.2, 40), (0.4, 75), (0.5, 92), (0.6, 97), (0.85, 100)],
    "pad": [(0, 0), (0.8, 75), (0.9, 92), (0.95, 97), (0.995, 100)],
    "ocr": [(0, 0), (0.6, 60), (0.8, 85), (0.9, 95), (1, 100)],
}
REQUIRED_CONTROLS = {
    "session_nonce_proof",
    "document_identity_complete",
    "document_face_liveness_pad",
    "no_security_rejection",
    "applicant_authority",
    "approved_identity_procedure",
}

WEIGHTS = {"face": 0.45, "pad": 0.35, "ocr": 0.20}


def mapped(value, points):
    if value <= points[0][0]:
        return points[0][1]
    for (x, y), (nx, ny) in zip(points, points[1:]):
        if value <= nx:
            return y + (value - x) / (nx - x) * (ny - y)
    return points[-1][1]


class ScoreCalibrator:
    def __init__(self):
        self.version = "demo-routing-v3-arcface-r50"
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
                or artifact.get("schema") != 1
                or artifact.get("face_model") != FACE_MODEL_ID
            ):
                raise ValueError(
                    "Artefak kalibrasi harus memiliki evaluasi/persetujuan dan model ArcFace R50 yang sesuai."
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
        required = ["face_cosine", "kyc_face_cosine", "liveness", "ocr"]
        if any(
            type(raw.get(k)) not in [float, int] or not math.isfinite(raw[k])
            for k in required
        ):
            return None, None
        values = {
            "face": min(raw["face_cosine"], raw["kyc_face_cosine"]),
            "pad": raw["liveness"],
            "ocr": raw["ocr"],
        }
        if (
            not -1 <= values["face"] <= 1
            or not 0 <= values["pad"] <= 1
            or not 0 <= values["ocr"] <= 1
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

    def route(self, result, mandatory):
        score, components = self.calibrator.score(result.get("scores", {}))
        state = result["status"]
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
        elif (
            self.mode == "demo"
            and not self.calibrator.calibrated
            and state == "manual"
            and result.get("pad_review_required") is True
            and mandatory["session_nonce_proof"]
            and mandatory["document_identity_complete"]
        ):
            # PAD uncertainty is not proof of fraud and must not become a
            # score-only rejection. The failed mandatory PAD control remains
            # false, so this path can never automatically approve/issue PDF.
            decision = "MANUAL_PENDING"
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
            "calibrated": self.calibrator.calibrated,
            "policy_version": self.calibrator.version,
            "mandatory": mandatory,
            "decision": decision,
            "security_review": security,
            "scope": "synthetic_only" if self.mode == "demo" else "production",
        }
