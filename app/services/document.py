"""Native-resolution document crops and quality measured on observed text."""

import cv2
import numpy as np
from app.services.glare import require_no_glare, GLARE_MESSAGE
from app.services.imaging import CaptureError, card_region, quality
from app.services.ocr import REQUIRED_FIELDS, FIELD_THRESHOLD, valid_field


def document_crop(image, reading):
    """Recover the selected native perspective crop; never label a full scene as a card."""
    box = reading.get("card_box")
    method = reading.get("crop_method")
    if method == "card_geometry" and box:
        try:
            for _, crop, candidate in card_region(image):
                if np.allclose(candidate, box, atol=1):
                    return crop.copy(), {"method": method, "source_box": list(candidate)}
        except CaptureError:
            pass
    return None


def read_document(image, ocr):
    candidates = []
    try:
        for _, crop, box in card_region(image)[:2]:
            candidates.append((crop, box, "card_geometry"))
    except CaptureError:
        pass
    candidates.append((image, [0, 0, image.shape[1], image.shape[0]], "full_frame"))
    best = None
    glare_seen = False
    for crop, box, method in candidates:
        if method == "full_frame" and glare_seen:
            continue
        if method == "card_geometry":
            try:
                glare = require_no_glare(crop)
            except CaptureError:
                glare_seen = True
                continue
        else:
            glare = None  # No located card: background is not a glare test.
        reading = ocr.read(crop)
        if hasattr(ocr, "refine"):
            reading = ocr.refine(crop, reading)
        reading["glare"] = glare
        rank = (
            bool(reading["fields"]["nik"]),
            sum(valid_field(k, reading["fields"].get(k, "")) for k in REQUIRED_FIELDS),
            min(
                (
                    reading.get("field_meta", {}).get(k, {}).get("confidence", 0.0)
                    for k in REQUIRED_FIELDS
                ),
                default=0.0,
            ),
        )
        if best is None or rank > best[0]:
            best = (rank, reading, crop, box, method)
        if rank[0] and rank[1] == len(REQUIRED_FIELDS) and rank[2] >= FIELD_THRESHOLD:
            break
    if best is None or (glare_seen and not best[0][0]):
        raise CaptureError(GLARE_MESSAGE)
    _, reading, crop, box, method = best
    reading["card_box"] = list(box)
    reading["crop_method"] = method
    reading["ocr_image_size"] = [crop.shape[1], crop.shape[0]]
    reading["quality"] = quality(crop)
    text_quality = {}
    for key in REQUIRED_FIELDS:
        area = reading.get("field_meta", {}).get(key, {}).get("box")
        if not area:
            continue
        x1, y1, x2, y2 = area
        h, w = crop.shape[:2]
        region = crop[
            max(0, int(y1)) : min(h, int(y2) + 1), max(0, int(x1)) : min(w, int(x2) + 1)
        ]
        if not region.size:
            continue
        text_quality[key] = quality(region)
    reading["text_quality"] = text_quality
    return reading


def capture_warning(reading):
    for key, metrics in reading.get("text_quality", {}).items():
        if metrics["height"] < 9:
            return (
                "text_small",
                "Tulisan KTP masih terlalu kecil. Geser sedikit lebih dekat selama teks tetap fokus.",
            )
        if metrics["brightness"] <= 35 or metrics["brightness"] >= 235:
            return (
                "text_lighting",
                "Area teks KTP gelap atau silau. Ubah sudut kartu dan pencahayaan.",
            )
        if metrics["blur"] < 25:
            return (
                "text_blur",
                "Teks KTP belum fokus. Mundurkan sedikit bila terlalu dekat, lalu tahan posisi.",
            )
    if not reading.get("text_quality"):
        q = reading["quality"]
        if q["blur"] < 25 or not 35 < q["brightness"] < 235:
            return (
                "document_quality",
                "KTP belum cukup tajam. Sesuaikan jarak sampai tulisan fokus dan hindari silau.",
            )
    return None
