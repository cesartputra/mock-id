"""Layout/consensus protocols use synthetic values, never user identity fixtures."""

from copy import deepcopy
from types import SimpleNamespace
import cv2
import numpy as np
import pytest
from app.services.ocr import parse_identity, extract_identity, OCRService
from app.services.document_consensus import DocumentConsensus
from app.services.document import capture_warning
from app.services.imaging import warp_card
from conftest import encoded


def reading(
    name="PEMOHON TEST", birth="1990-01-01", nik="1234567890123456", score=0.96
):
    return {
        "fields": {"nik": nik, "name": name, "birth": birth, "address": "JALAN UJI"},
        "field_meta": {
            key: {"confidence": score, "raw": value, "source": "protocol fixture"}
            for key, value in [("nik", nik), ("name", name), ("birth", birth)]
        },
        "lines": ["protocol fixture"],
        "confidence": score,
        "mode": "protocol fixture",
    }


def test_damaged_labels_do_not_change_personal_values_or_invent_birth():
    fields = parse_identity(
        [
            "PROVINSI DKI JAKARTA",
            "NI<",
            ":1234567890123456",
            "N",
            "PEMOHON TXST",
            "Tempa/Tgi Lanw",
            "JAKARTA S-",
            "Alarnat",
            "JALAN XYZ",
            "RT/RW",
            "000/012",
            "Berlaku Hingga",
            "24-04-2017",
        ]
    )
    assert fields == {
        "nik": "1234567890123456",
        "name": "PEMOHON TXST",
        "birth": "",
        "address": "JALAN XYZ",
    }
    assert parse_identity(["NIK:123456789012345O"])["nik"] == ""


def test_birth_requires_its_field_and_valid_calendar_date():
    assert (
        parse_identity(["Lahir:01-01-1990", "Berlaku Hingga:24-04-2017"])["birth"]
        == "1990-01-01"
    )
    assert (
        parse_identity(["Lahir:31-02-1990", "Berlaku Hingga:24-04-2017"])["birth"] == ""
    )
    assert parse_identity(["24-04-2017"])["birth"] == ""


def test_spatial_rows_pair_labels_and_values_even_when_ocr_order_is_shuffled():
    lines = [
        "JALAN UJI",
        "PEMOHON TEST",
        "Alarnat",
        "NAMA",
        "NIK:1234567890123456",
        "Lahir:01-01-1990",
    ]

    def box(x, y, w):
        return [[x, y], [x + w, y], [x + w, y + 20], [x, y + 20]]

    boxes = [
        box(120, 120, 160),
        box(120, 60, 160),
        box(10, 120, 70),
        box(10, 60, 70),
        box(10, 20, 290),
        box(10, 90, 290),
    ]
    fields, meta = extract_identity(lines, boxes, [0.98, 0.97, 0.45, 0.48, 0.99, 0.98])
    assert fields["name"] == "PEMOHON TEST" and fields["address"] == "JALAN UJI"
    assert fields["birth"] == "1990-01-01"
    assert meta["name"]["confidence"] == 0.97 and meta["address"]["confidence"] == 0.98


def test_card_warp_preserves_native_detail_and_never_upscales_small_cards():
    image = np.zeros((1100, 1700, 3), np.uint8)
    large = warp_card(image, [[10, 10], [1610, 10], [1610, 1010], [10, 1010]])
    small = warp_card(image, [[10, 10], [310, 10], [310, 190], [10, 190]])
    assert large.shape[:2] == (1000, 1600)
    assert small.shape[:2] == (180, 300)


def test_roi_refine_is_bounded_and_preserves_observed_name(monkeypatch):
    ocr = OCRService()
    r = reading(name="PEMOHON TXST", score=0.60)
    for value in r["field_meta"].values():
        value.update(box=[10, 10, 130, 35], region=[5, 5, 140, 40])
    calls = []

    def retry(image):
        calls.append(image.shape)
        result = reading(name="PEMOHON TXST", score=0.97)
        result.update(scores=[0.97], lines=["PEMOHON TXST"])
        return result

    monkeypatch.setattr(ocr, "read", retry)
    result = ocr.refine(np.full((100, 200, 3), 140, np.uint8), r)
    assert len(calls) == 2 and all(shape[1] < 200 for shape in calls)
    assert result["fields"]["name"] == "PEMOHON TXST"


def test_consensus_requires_distinct_observations_and_all_critical_fields():
    c = DocumentConsensus()
    for n in range(4):
        assert c.observe(reading(), "same", n)[0] is None
    assert c.observe(reading(), "other", 4)[0] is None
    complete, pending, count = c.observe(reading(), "third", 5)
    assert complete and not pending and count == 3
    assert complete["field_feedback"]["birth"]["samples"] == 3
    c = DocumentConsensus()
    for n in range(5):
        assert c.observe(reading(birth=""), str(n), n)[0] is None


def test_consensus_rejects_conflicts_low_confidence_expiry_and_card_switch():
    c = DocumentConsensus()
    for n in range(2):
        c.observe(reading(), str(n), n)
    assert c.observe(reading(name="OTHER PERSON"), "conflict", 3)[0] is None
    assert c.observe(reading(score=0.4), "uncertain", 4)[0] is None
    assert c.observe(reading(nik="9999999999999999"), "new-card", 5)[2] == 1
    assert c.observe(reading(nik="9999999999999999"), "expired", 30)[2] == 1


def test_quality_guidance_uses_text_not_background():
    r = {
        "quality": {"blur": 1000, "brightness": 120},
        "text_quality": {"name": {"blur": 2, "height": 20, "brightness": 120}},
    }
    assert capture_warning(r)[0] == "text_blur"
    r["text_quality"]["name"].update(blur=1000, height=5)
    assert capture_warning(r)[0] == "text_small"


def test_bound_auto_document_snapshot_rejects_changed_photo_and_reuses_server_reading(
    client, face_image, monkeypatch
):
    clock = [100.0]
    monkeypatch.setattr(
        "app.controller.verification.time", SimpleNamespace(monotonic=lambda: clock[0])
    )
    verifier = client.app.state.verifier
    monkeypatch.setattr(
        verifier,
        "inspect_auto_capture",
        lambda *args: {
            "ready": True,
            "complete": False,
            "context": "document",
            "nik_readable": True,
            "subject_key": "protocol-key",
            "_document_reading": reading(),
        },
    )
    sid = client.post("/api/sessions").json()["id"]
    route = f"/api/sessions/{sid}/auto-capture/check"
    for n in range(3):
        clock[0] += 1
        image = face_image.copy()
        cv2.circle(image, (2, 2), 1, (n * 70, 30, 10), -1)
        file = {"image": ("frame.jpg", encoded(image), "image/jpeg")}
        result = client.post(route, data={"context": "document"}, files=file)
        assert result.status_code == 200
        assert result.json()["complete"] == (n == 2)
    token = result.json()["document_capture_token"]
    wrong = {"image": ("different.jpg", encoded(face_image), "image/jpeg")}
    assert (
        client.post(
            f"/api/sessions/{sid}/document", data={"capture_token": token}, files=wrong
        ).status_code
        == 409
    )
    assert client.app.state.sessions.get(sid).document_attempts == 0
    monkeypatch.setattr(
        verifier,
        "document",
        lambda *args: pytest.fail("Bound consensus must not re-run whole OCR"),
    )
    accepted = client.post(
        f"/api/sessions/{sid}/document", data={"capture_token": token}, files=file
    )
    assert accepted.status_code == 200 and accepted.json()["verified_frames"] == 3
    assert accepted.json()["fields"]["name"] == "PEMOHON TEST"
    assert (
        client.post(
            f"/api/sessions/{sid}/document", data={"capture_token": token}, files=file
        ).status_code
        == 409
    )


def test_retake_discards_ocr_consensus_and_tokens(client, face_image, monkeypatch):
    from app.services.document_consensus import DocumentConsensus

    public = client.post("/api/sessions").json()
    session = client.app.state.sessions.get(public["id"])
    session.document_consensus = DocumentConsensus()
    session.document_probe = {"token": "old", "digest": "old"}
    response = client.post(
        f"/api/sessions/{session.id}/retake",
        json={"stage": "document", "nonce": public["nonce"]},
    )
    assert response.status_code == 200
    assert session.document_consensus is None and session.document_probe is None


@pytest.mark.parametrize("change", ["expired", "wrong_token", "old_revision"])
def test_auto_document_proof_rejects_expiry_token_or_revision_before_attempt(
    client, face_image, monkeypatch, change
):
    import hashlib

    monkeypatch.setattr(
        "app.controller.verification.time", SimpleNamespace(monotonic=lambda: 100.0)
    )
    public = client.post("/api/sessions").json()
    session = client.app.state.sessions.get(public["id"])
    blob = encoded(face_image)
    session.document_probe = {
        "token": "proof",
        "digest": hashlib.sha256(blob).hexdigest(),
        "revision": session.revision,
        "created": 99.0,
        "reading": reading(),
    }
    if change == "expired":
        session.document_probe["created"] = 79.0
    if change == "old_revision":
        session.document_probe["revision"] -= 1
    token = "different" if change == "wrong_token" else "proof"
    response = client.post(
        f"/api/sessions/{session.id}/document",
        data={"capture_token": token},
        files={"image": ("frame.jpg", blob, "image/jpeg")},
    )
    assert response.status_code == 409 and session.document_attempts == 0
    assert session.document_result is None
