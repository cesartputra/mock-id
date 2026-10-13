"""Incremental, server-owned gesture evidence for continuous camera frames.

No fixed action duration. A challenge completes on measured transitions;
neutral samples, deadline and frame limits are guards, never proof of motion.
"""

import secrets
import statistics
import time

from app.services.antispoof import summarize_pad


class GestureTracker:
    def __init__(self, challenges, turn_direction=None):
        self.challenges = list(challenges)
        self.turn_direction = turn_direction or secrets.choice([-1, 1])
        self.completed = []
        self.reference = None
        self.reset_action()

    def reset_action(self):
        self.baselines = []
        self.baseline = None
        self.closed = False
        self.hits = 0

    @property
    def challenge(self):
        return (
            self.challenges[len(self.completed)]
            if len(self.completed) < len(self.challenges)
            else None
        )

    def update(self, metrics):
        if not self.challenge:
            return self.public()
        if self.reference is None:
            self.reference = dict(metrics)
        # Return to a neutral face between actions. A turned head, shut eyes or
        # held smile must not become a new baseline for the next challenge.
        if self.baseline is None:
            neutral = (
                metrics["blink"] >= 0.22
                and abs(metrics["yaw"] - self.reference["yaw"]) < 0.08
                and metrics["smile"] <= self.reference["smile"] * 1.06
            )
            if not neutral:
                self.baselines = []
                return self.public()
            self.baselines.append(dict(metrics))
            if len(self.baselines) >= 3:
                self.baseline = {
                    k: statistics.median(m[k] for m in self.baselines) for k in metrics
                }
            return self.public()
        base = self.baseline
        challenge = self.challenge
        if challenge == "blink":
            if metrics["blink"] <= min(0.19, base["blink"] * 0.70):
                self.closed = True
            # Require a full open -> closed -> open cycle, not just a low EAR.
            detected = self.closed and metrics["blink"] >= max(
                0.22, base["blink"] * 0.85
            )
        elif challenge == "smile":
            detected = (
                metrics["smile"] >= base["smile"] * 1.10
                and metrics["smile"] - base["smile"] >= 0.06
            )
        else:
            detected = (metrics["yaw"] - base["yaw"]) * self.turn_direction >= 0.12
        self.hits = self.hits + 1 if detected else 0
        if self.hits >= 2:
            self.completed.append(
                {
                    "challenge": challenge,
                    "passed": True,
                    "baseline": base,
                    "evidence": dict(metrics),
                    "mode": "real",
                }
            )
            self.reset_action()
        return self.public()

    def public(self):
        passed = self.challenge is None
        return {
            "passed": passed,
            "challenge": self.challenge,
            "phase": "complete" if passed else "action" if self.baseline else "neutral",
            "completed": self.completed.copy(),
            "turn_direction": self.turn_direction,
            "neutral_samples": len(self.baselines),
            "blink_closed": self.closed,
        }


class LiveCapture:
    MAX_FRAMES = 360
    DEADLINE = 90

    def __init__(self, challenges):
        self.gestures = GestureTracker(challenges)
        self.started = time.monotonic()
        self.last_frame = 0.0
        self.sequence = 0
        self.hashes = set()
        self.reference_image = None
        self.reference_face = None
        self.selfie_hash = None
        self.selfie_seq = None
        self.pad_min = 1.0
        self.pad_samples = []
        self.pad_box_history = []
        self.pad_geometry = []
        self.pad_review_enabled = False
        self.cosine_min = 1.0
        self.spoof_strikes = 0
        self.rules = None
        self.evidence_images = []
        self.detection_missing_since = None
        self.detection_misses = 0

    def accept(self, digest, seq, now):
        if now - self.started > self.DEADLINE or self.sequence >= self.MAX_FRAMES:
            return "Waktu pemeriksaan habis. Ambil ulang liveness dan ikuti instruksi gerakan."
        if seq != self.sequence:
            return "Urutan frame berubah. Rekam ulang liveness."
        if self.last_frame and now - self.last_frame < 0.09:
            return "Frame terlalu cepat. Tunggu pemeriksaan frame sebelumnya."
        if digest in self.hashes:
            return "Frame identik berulang. Gunakan wajah langsung, bukan pengulangan foto."
        if self.last_frame and now - self.last_frame > 3:
            self.gestures.reset_action()
        self.last_frame = now
        self.hashes.add(digest)
        self.sequence += 1
        return None

    def pause_detection(self, now=None):
        """Brief detector misses pause evidence, never count as a valid frame."""
        now = time.monotonic() if now is None else now
        if self.detection_missing_since is None:
            self.detection_missing_since = now
        self.detection_misses += 1
        self.pad_box_history = []
        self.gestures.hits = 0  # Consecutive positive samples must remain real.
        if self.detection_misses > 2 or now - self.detection_missing_since > 1.0:
            self.gestures.reset_action()

    def resume_detection(self):
        self.detection_missing_since = None
        self.detection_misses = 0

    def stabilize_pad_face(self, face):
        """Median three nearby detector boxes, based only on geometry.

        Real movement, scale change or any missing face resets the history.
        No previous face may substitute for a detector miss; no score is used
        to pick a crop. Landmarks and recognition still use the current face.
        """
        box = [float(v) for v in face[:4]]
        if self.pad_box_history:
            previous = self.pad_box_history[-1]
            px, py, pw, ph = previous
            x, y, w, h = box
            nearby = (abs((x+w/2)-(px+pw/2)) <= .04*pw
                      and abs((y+h/2)-(py+ph/2)) <= .04*ph
                      and abs(w-pw) <= .08*pw and abs(h-ph) <= .08*ph)
            if not nearby:
                self.pad_box_history = []
        self.pad_box_history.append(box)
        self.pad_box_history = self.pad_box_history[-3:]
        stabilized = face.copy()
        stabilized[:4] = [statistics.median(b[i] for b in self.pad_box_history) for i in range(4)]
        return stabilized

    def record_pad(self, probability, geometry=None):
        # Validate before mutating the session; samples are bounded by MAX_FRAMES.
        summarize_pad([probability], (self.rules or {}).get('pad_probability', .8))
        if len(self.pad_samples) >= self.MAX_FRAMES:
            raise ValueError('Batas sampel PAD tercapai.')
        self.pad_samples.append(probability)
        self.pad_geometry.append(geometry)
        self.pad_min = min(self.pad_min, probability)

    def result(self, feedback, metrics=None):
        threshold = (self.rules or {}).get('pad_probability', .8)
        summary = summarize_pad(self.pad_samples or [self.pad_min], threshold,
                                demo=self.pad_review_enabled)
        summary['geometry_profile'] = 'nearby-box-median3-v1'
        summary['geometry'] = list(self.pad_geometry)
        if self.pad_review_enabled and summary['passed'] and self.pad_samples:
            # One low preview frame must not keep a historical warning alive.
            feedback = {**feedback, 'warnings': [w for w in feedback.get('warnings', [])
                                                 if w['code'] != 'pad_review'],
                        'pad_review_required': False}
        result = {
            **self.gestures.public(),
            "done": False,
            "feedback": feedback,
            "metrics": metrics,
            "frames": self.sequence,
            "selfie_seq": self.selfie_seq,
            "pad_probability": summary['score'],
            "pad_summary": summary,
            "pad_passed": summary['passed'],
            "pad_review_required": self.pad_review_enabled and not summary['passed'],
            "continuity": [self.cosine_min],
            "rules": self.rules,
            "stream": True,
            "mode": "real",
        }
        result["live"] = {
            "passed": result["passed"],
            "challenges": result["completed"],
            "model": "PIPNet 68 / ONNX CPU",
            "mode": "real",
        }
        # The proof may attest measured motion with PAD pending only under the
        # explicit demo review policy. Strict mode still requires PAD passing.
        motion_complete = result["passed"]
        result["passed"] = motion_complete and (
            result["pad_passed"] or result["pad_review_required"]
        )
        result["reason"] = (
            "Gerakan terbaca. Penilaian PAD memerlukan pemeriksaan manual; KYC belum disetujui."
            if result["passed"] and result["pad_review_required"]
            else (
                "Gerakan dan anti-spoof terpenuhi."
                if result["passed"]
                else "Ikuti instruksi gerakan di kamera."
            )
        )
        result["done"] = motion_complete
        if motion_complete and not result["passed"]:
            result["reason"] = (
                "Pemeriksaan anti-spoof belum memenuhi ambang; KYC belum disetujui."
            )
        return result
