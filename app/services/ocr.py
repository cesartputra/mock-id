"""OCR observations, layout-aware field extraction and bounded ROI retries.

Fuzzy matching is restricted to printed labels. Personal values are never
spell-corrected, derived from NIK, or copied from a reference identity.
"""

import re
import math
from datetime import date
from difflib import SequenceMatcher

import cv2
import numpy as np
from rapidocr import RapidOCR
from app.config import WEIGHTS

REQUIRED_FIELDS = ("nik", "name", "birth")
FIELD_THRESHOLD = 0.80  # Demo capture heuristic; not identity probability.
ALIASES = {
    "nik": ["NIK"],
    "name": ["NAMA"],
    "address": ["ALAMAT"],
    "birth": [
        "TEMPAT/TGL LAHIR",
        "TEMPAT TGL LAHIR",
        "TEMPAT TANGGAL LAHIR",
        "TGL LAHIR",
        "LAHIR",
    ],
    "stop": [
        "PROVINSI",
        "KABUPATEN",
        "KOTA",
        "JENIS KELAMIN",
        "GOL DARAH",
        "RT RW",
        "RT/RW",
        "KEL/DESA",
        "KEL DESA",
        "KECAMATAN",
        "AGAMA",
        "STATUS PERKAWINAN",
        "PEKERJAAN",
        "KEWARGANEGARAAN",
        "BERLAKU HINGGA",
    ],
}
LABELS = [(key, value) for key, values in ALIASES.items() for value in values]


def nik_match(line):
    compact = re.sub(r"(?<=\d)[ \t-]+(?=\d)", "", line)
    return re.search(r"(?<!\d)\d{16}(?!\d)", compact)


def _letters(text):
    return re.sub(r"[^A-Z]", "", text.upper())


def _label(text):
    """Return field/label length, tolerating label typos without fixing values."""
    label_text = text.split(":", 1)[0] if ":" in text and text.index(":") < 30 else text
    words = list(re.finditer(r"\S+", label_text))
    options = []
    for key, alias in LABELS:
        count = len(alias.split())
        if len(words) < count:
            continue
        end = words[count - 1].end()
        prefix = text[:end].rstrip(":")
        a, b = _letters(prefix), _letters(alias)
        if not a or abs(len(a) - len(b)) > max(2, len(b) * 0.35):
            continue
        ratio = SequenceMatcher(None, a, b).ratio()
        # Short NIK must not fuzzy-match arbitrary names/three-letter values.
        valid = a == b if len(b) < 4 else ratio >= 0.74
        if key == "nik":
            valid = a in ["NIK", "NI"]
        if valid:
            options.append((ratio, len(b), key, end))
    if not options:
        return None
    _, _, key, end = max(options)
    return key, end


def _rows(lines, boxes, scores):
    items = []
    for i, text in enumerate(lines):
        box = (
            np.asarray(boxes[i], dtype=float)
            if boxes is not None and i < len(boxes)
            else None
        )
        if box is not None and (box.shape != (4, 2) or not np.isfinite(box).all()):
            box = None
        items.append(
            {
                "text": str(text).strip(),
                "score": (
                    float(scores[i]) if scores is not None and i < len(scores) else 0.0
                ),
                "box": box,
                "index": i,
            }
        )
    if not items or any(v["box"] is None for v in items):
        return [[v] for v in items]
    rows = []
    for item in sorted(items, key=lambda v: v["box"][:, 1].mean()):
        y1, y2 = item["box"][:, 1].min(), item["box"][:, 1].max()
        found = None
        for row in rows:
            other = row[0]["box"]
            a, b = other[:, 1].min(), other[:, 1].max()
            if min(y2, b) - max(y1, a) > 0.5 * min(y2 - y1, b - a):
                found = row
                break
        if found is None:
            rows.append([item])
        else:
            found.append(item)
    return [sorted(row, key=lambda v: v["box"][:, 0].min()) for row in rows]


def _birthday(text):
    found = []
    for m in re.finditer(
        r"(?<!\d)(\d{2})\s*[-/]\s*(\d{2})\s*[-/]\s*(\d{4})(?!\d)", text
    ):
        try:
            value = date(int(m[3]), int(m[2]), int(m[1]))
            if date(1900, 1, 1) <= value <= date.today():
                found.append(value.isoformat())
        except ValueError:
            pass
    return found[0] if len(set(found)) == 1 else ""


def valid_field(key, value):
    if not isinstance(value, str):
        return False
    if key == "nik":
        return bool(re.fullmatch(r"\d{16}", value))
    if key == "birth":
        try:
            return date(1900, 1, 1) <= date.fromisoformat(value) <= date.today()
        except ValueError:
            return False
    if key == "name":
        return (
            2 <= len(value) <= 80
            and bool(re.search(r"[^\W\d_]", value, re.UNICODE))
            and not re.search(r"\d", value)
        )
    return bool(value.strip())


def extract_identity(lines, boxes=None, scores=None):
    rows = _rows(lines, boxes, scores)
    texts = [" ".join(v["text"] for v in row) for row in rows]
    labels = [_label(text) for text in texts]
    nik_row = next((i for i, text in enumerate(texts) if nik_match(text)), None)
    # Damaged single-letter name label is accepted only immediately after NIK,
    # with a following value row, never as a general alias for any letter N.
    if nik_row is not None:
        for i in range(nik_row + 1, min(nik_row + 3, len(rows) - 1)):
            if texts[i].strip(": ").upper() == "N":
                labels[i] = ("name", len(texts[i]))
    fields = {key: "" for key in ["nik", "name", "birth", "address"]}
    meta = {}

    def observe(key, value, support, region=None):
        tokens = [v for row in support for v in row]
        boxes_used = [v["box"] for v in tokens if v["box"] is not None]
        # Prefer an exact, already valid observation over another candidate.
        confidence = min((v["score"] for v in tokens), default=0.0)
        if key in meta and meta[key]["confidence"] >= confidence and fields[key]:
            return
        fields[key] = value if valid_field(key, value) else ""
        points = np.concatenate(boxes_used) if boxes_used else None
        bounds = (
            [
                float(points[:, 0].min()),
                float(points[:, 1].min()),
                float(points[:, 0].max()),
                float(points[:, 1].max()),
            ]
            if points is not None
            else None
        )
        meta[key] = {
            "confidence": confidence,
            "raw": " ".join(v["text"] for v in tokens),
            "box": bounds,
            "region": region or bounds,
            "source": "ocr",
            "indices": [v["index"] for v in tokens],
        }

    if nik_row is not None:
        match = nik_match(texts[nik_row])
        observe("nik", match.group(), [rows[nik_row]])
    for i, label in enumerate(labels):
        if not label or label[0] not in ["nik", "name", "birth", "address"]:
            continue
        key, end = label
        value = texts[i][end:].strip(" :")
        support = [rows[i]]
        # Separate label/value boxes on a shared row: label confidence must not
        # become the personal value's confidence when the label is damaged.
        consumed = 0
        value_tokens = []
        for token in rows[i]:
            consumed += len(token["text"]) + 1
            if consumed > end + 1:
                value_tokens.append(token)
        if value_tokens:
            support = [value_tokens]
        j = i + 1
        if not value and j < len(rows) and labels[j] is None:
            value = texts[j].strip(" :")
            support = [rows[j]]
            j += 1
        if (
            key == "birth"
            and not _birthday(value)
            and j < len(rows)
            and labels[j] is None
        ):
            value += " " + texts[j]
            support.append(rows[j])
        if key == "address":
            # Wrapped address stays within its block; never includes RT/RW or
            # another known label. Do not fill/correct street names.
            while j < min(i + 3, len(rows)) and labels[j] is None:
                value += " " + texts[j]
                support.append(rows[j])
                j += 1
        all_boxes = [
            v["box"] for row in [rows[i], *support] for v in row if v["box"] is not None
        ]
        points = np.concatenate(all_boxes) if all_boxes else None
        region = (
            [
                float(points[:, 0].min()),
                float(points[:, 1].min()),
                float(points[:, 0].max()),
                float(points[:, 1].max()),
            ]
            if points is not None
            else None
        )
        candidate = (
            (nik_match(value).group() if nik_match(value) else "")
            if key == "nik"
            else (
                _birthday(value)
                if key == "birth"
                else re.sub(r"\s+", " ", value).strip()
            )
        )
        observe(key, candidate, support, region)
    for key in fields:
        meta.setdefault(
            key,
            {
                "confidence": 0.0,
                "raw": "",
                "box": None,
                "region": None,
                "source": "unreadable",
                "indices": [],
            },
        )
    return fields, meta


def parse_identity(lines, boxes=None, scores=None):
    return extract_identity(lines, boxes, scores)[0]


def field_feedback(reading):
    return {
        key: {
            "status": (
                "observed"
                if valid_field(key, value)
                and reading.get("field_meta", {}).get(key, {}).get("confidence", 0)
                >= FIELD_THRESHOLD
                else "needs_review"
            ),
            "message": (
                "Terbaca; periksa ejaannya."
                if value
                else "Belum terbaca; ambil frame yang lebih tajam."
            ),
        }
        for key, value in reading["fields"].items()
    }


class OCRService:
    def __init__(self):
        self.engine = None

    def load(self):
        if self.engine is None:
            self.engine = RapidOCR(
                params={
                    "Global.model_root_dir": str(WEIGHTS / "ocr"),
                    "Rec.lang_type": "en",
                    "Global.text_score": 0.40,
                }
            )
        return self.engine

    def read(self, image):
        result = self.load()(image)
        lines = list(result.txts or [])
        scores = [float(v) for v in (result.scores or [])]
        scores = [v if math.isfinite(v) and 0 <= v <= 1 else 0.0 for v in scores]
        boxes = result.boxes.tolist() if result.boxes is not None else []
        fields, meta = extract_identity(lines, boxes, scores)
        reading = {
            "fields": fields,
            "field_meta": meta,
            "lines": lines,
            "scores": scores,
            "boxes": boxes,
            "confidence": float(np.mean(scores)) if scores else 0.0,
            "engine": "RapidOCR / PaddleOCR ONNX",
            "mode": "real",
        }
        reading["field_feedback"] = field_feedback(reading)
        return reading

    def refine(self, image, reading):
        """At most two low-confidence critical text regions, never whole-frame loops."""
        for key in sorted(
            REQUIRED_FIELDS, key=lambda k: reading["field_meta"][k]["confidence"]
        )[:2]:
            old = reading["field_meta"][key]
            if reading["fields"][key] and old["confidence"] >= FIELD_THRESHOLD:
                continue
            box = old.get("region")
            if not box:
                continue
            h, w = image.shape[:2]
            x1, y1, x2, y2 = box
            x1, y1 = max(0, int(x1) - 6), max(0, int(y1) - 5)
            x2, y2 = min(w, int(x2) + 6), min(h, int(y2) + 5)
            if x2 - x1 < 10 or y2 - y1 < 8:
                continue
            roi = image[y1:y2, x1:x2]
            gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
            enhanced = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4)).apply(gray)
            retry = self.read(cv2.cvtColor(enhanced, cv2.COLOR_GRAY2BGR))
            candidate = retry["fields"][key]
            evidence = retry["field_meta"][key]
            # A name-only ROI is read in its established field context. Preserve
            # exact observed letters; require one text line, no label/date/NIK.
            if (
                key == "name"
                and not candidate
                and len(retry["lines"]) == 1
                and not _label(retry["lines"][0])
            ):
                candidate = retry["lines"][0].strip()
                evidence = {
                    **evidence,
                    "confidence": min(retry["scores"], default=0.0),
                    "raw": candidate,
                }
            if (
                valid_field(key, candidate)
                and evidence["confidence"] >= FIELD_THRESHOLD
                and evidence["confidence"] > old["confidence"] + 0.05
            ):
                reading["fields"][key] = candidate
                reading["field_meta"][key] = {
                    **evidence,
                    "box": box,
                    "region": box,
                    "source": "roi_retry",
                }
        reading["field_feedback"] = field_feedback(reading)
        return reading
