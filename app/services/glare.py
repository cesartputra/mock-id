"""Conservative clipped-highlight check on a located card, before OCR.

A connected, near-white low-saturation region is a capture-quality heuristic,
not a determination of card authenticity. Apply to the card ROI, never a scene.
"""

import cv2
import numpy as np
from app.services.imaging import CaptureError

GLARE_MESSAGE = "KTP terkena pantulan cahaya. Miringkan sedikit kartu atau ubah posisi lampu sampai teks terlihat, lalu tahan posisi."


def card_glare(crop):
    if crop is None or not crop.size:
        raise CaptureError("Area KTP belum terlihat.")
    h, w = crop.shape[:2]
    # Ignore a thin outer border; webcam backgrounds must not enter this mask.
    px, py = max(1, int(w * 0.03)), max(1, int(h * 0.03))
    inner = crop[py : h - py, px : w - px]
    if not inner.size:
        return {"rejected": False, "white_fraction": 0.0, "largest_fraction": 0.0}
    hsv = cv2.cvtColor(inner, cv2.COLOR_BGR2HSV)
    clipped = (
        (hsv[:, :, 2] >= 250) & (hsv[:, :, 1] <= 25) & (inner.min(axis=2) >= 240)
    ).astype(np.uint8)
    count, _, stats, _ = cv2.connectedComponentsWithStats(clipped, 8)
    largest = int(stats[1:, cv2.CC_STAT_AREA].max()) if count > 1 else 0
    area = clipped.size
    total, patch = float(clipped.mean()), largest / area
    # Colored KTP stock is not white. Tiny text, hologram speckles and sensor
    # highlights alone do not reject; require a substantial contiguous patch.
    rejected = patch >= 0.025 and total >= 0.035
    return {
        "rejected": bool(rejected),
        "white_fraction": total,
        "largest_fraction": patch,
    }


def require_no_glare(crop):
    result = card_glare(crop)
    if result["rejected"]:
        raise CaptureError(GLARE_MESSAGE)
    return result
