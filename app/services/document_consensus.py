"""Bounded, server-owned OCR observations; no character guessing or voting digits."""

from collections import Counter, deque
from copy import deepcopy
from app.services.ocr import (
    REQUIRED_FIELDS,
    FIELD_THRESHOLD,
    valid_field,
    field_feedback,
)


class DocumentConsensus:
    WINDOW = 5
    MAX_AGE = 20.0
    REQUIRED = 3

    def __init__(self):
        self.readings = deque(maxlen=self.WINDOW)
        self.subject = None

    def observe(self, reading, digest, now):
        self.readings = deque(
            (row for row in self.readings if now - row[0] <= self.MAX_AGE),
            maxlen=self.WINDOW,
        )
        nik = reading["fields"].get("nik", "")
        if not valid_field("nik", nik):
            return None, [], 0
        if self.subject != nik:
            self.subject = nik
            self.readings.clear()
        if not any(row[1] == digest for row in self.readings):
            self.readings.append((now, digest, deepcopy(reading)))
        merged = deepcopy(reading)
        pending = []
        for key in REQUIRED_FIELDS:
            eligible = [
                row
                for row in self.readings
                if valid_field(key, row[2]["fields"].get(key, ""))
                and row[2].get("field_meta", {}).get(key, {}).get("confidence", 0)
                >= FIELD_THRESHOLD
            ]
            votes = Counter(row[2]["fields"][key] for row in eligible)
            if not votes:
                pending.append(key)
                continue
            value, count = votes.most_common(1)[0]
            current = reading["fields"].get(key, "")
            # Latest frame must itself support the chosen value. Never merge a
            # previous applicant's name into a new/conflicting card observation.
            if (
                count < self.REQUIRED
                or current != value
                or reading["field_meta"][key]["confidence"] < FIELD_THRESHOLD
            ):
                pending.append(key)
                continue
            merged["fields"][key] = value
            merged["field_meta"][key]["support_hashes"] = [
                row[1] for row in eligible if row[2]["fields"][key] == value
            ]
        if pending:
            return None, pending, len(self.readings)
        merged["field_feedback"] = field_feedback(merged)
        for key in REQUIRED_FIELDS:
            merged["field_feedback"][key] = {
                "status": "consistent",
                "message": "Terbaca konsisten pada beberapa frame; periksa ejaannya.",
                "samples": len(merged["field_meta"][key]["support_hashes"]),
            }
        merged["capture_method"] = "server_multiframe"
        merged["verified_frames"] = len(self.readings)
        return merged, [], len(self.readings)
