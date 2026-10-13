"""Model/capture regressions with public or synthetic fixtures only."""

import hashlib
import json
import zipfile
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import cv2
import numpy as np
import pytest
from app.config import DEFAULT_SETTINGS
from app.model.repository import Repository
from app.services.face import align_face, REFERENCE, FACE_MODEL_ID, FaceService
from app.services.glare import card_glare
from app.services.imaging import CaptureError
from app.services.document import read_document
from app.services.card import HoldingCardService
from app.services.score_policy import ScoreCalibrator, DEMO_POINTS
from scripts.setup_models import extract_model


def test_arcface_similarity_alignment_and_invalid_landmarks():
    # Inverting a known similarity transform should recover canonical points.
    points = (REFERENCE - [12, 9]) / 1.5
    face = np.r_[np.zeros(4), points.reshape(-1), 1]
    image = np.zeros((112, 112, 3), np.uint8)
    for x, y in points:
        cv2.circle(image, (round(x), round(y)), 2, (255, 255, 255), -1)
    aligned = align_face(image, face)
    for x, y in REFERENCE:
        assert aligned[round(y), round(x)].max() > 150
    for invalid in [np.zeros(15), np.full(15, np.nan)]:
        with pytest.raises(CaptureError):
            align_face(image, invalid)


def test_arcface_preprocessing_is_rgb_normalized_and_bad_embedding_rejected():
    captured = []
    face = np.r_[np.zeros(4), REFERENCE.reshape(-1), 1]
    service = FaceService.__new__(FaceService)
    service.input = "input"

    def run(_, inputs):
        captured.append(inputs["input"])
        return [np.ones((1, 512), np.float32)]

    service.recognizer = SimpleNamespace(run=run)
    vector, aligned = service.feature(
        np.full((112, 112, 3), (0, 127, 255), np.uint8), face
    )
    assert aligned.shape == (112, 112, 3) and vector.shape == (512,)
    assert np.linalg.norm(vector) == pytest.approx(1)
    assert captured[0].shape == (1, 3, 112, 112)
    assert captured[0][0, :, 50, 50] == pytest.approx([1, (127 - 127.5) / 127.5, -1])
    service.recognizer = SimpleNamespace(run=lambda *_: [np.zeros((1, 512))])
    with pytest.raises(ValueError):
        service.feature(aligned, face)


def test_actual_arcface_handles_public_face_variants(real_models, face_image):
    original = real_models.face.one(face_image)
    feature, aligned = real_models.face.feature(face_image, original)
    assert feature.size == 512 and aligned.shape == (112, 112, 3)
    scores = []
    for sample in [
        cv2.GaussianBlur(face_image, (5, 5), 0),
        cv2.resize(face_image, (256, 256)),
    ]:
        detected = real_models.face.one(sample)
        scores.append(real_models.face.compare(face_image, original, sample, detected))
    assert all(0.4 < score <= 1 for score in scores)
    # A different public fixture face must not share the same embedding.
    other = cv2.imread(
        str(Path(__file__).parent / "fixtures/face_attributes/eyeglasses.jpg")
    )
    negative = real_models.face.compare(
        face_image, original, other, real_models.face.one(other)
    )
    assert negative < min(scores)


def test_sface_setting_is_migrated_once_and_custom_arcface_setting_persists(tmp_path):
    repo = Repository(tmp_path)
    with repo.connect() as con:
        con.execute(
            "UPDATE settings SET payload=? WHERE id=1",
            (json.dumps({**DEFAULT_SETTINGS, "face_cosine": 0.363}),),
        )
    repo = Repository(tmp_path)
    assert repo.settings()["face_cosine"] == 0.4
    repo.set_settings({**DEFAULT_SETTINGS, "face_cosine": 0.51})
    assert Repository(tmp_path).settings()["face_cosine"] == 0.51


def test_old_face_calibration_cannot_be_reused(monkeypatch, tmp_path):
    artifact = {
        "schema": 1,
        "version": "fixture",
        "approved_by": "fixture",
        "evaluation_report": "fixture",
        "points": DEMO_POINTS,
        "weights": {"face": 0.45, "pad": 0.35, "ocr": 0.20},
        "face_model": "sface",
    }
    path = tmp_path / "calibration.json"
    monkeypatch.setenv("MOCK_ID_CALIBRATION_FILE", str(path))
    for model, valid in [("sface", False), (FACE_MODEL_ID, True)]:
        artifact["face_model"] = model
        path.write_text(json.dumps(artifact))
        monkeypatch.setenv(
            "MOCK_ID_CALIBRATION_SHA256", hashlib.sha256(path.read_bytes()).hexdigest()
        )
        if valid:
            assert ScoreCalibrator().calibrated
        else:
            with pytest.raises(ValueError):
                ScoreCalibrator()


def test_glare_detects_large_patch_but_not_small_highlights_or_colored_stock(ktp_image):
    assert not card_glare(ktp_image)["rejected"]
    small = ktp_image.copy()
    cv2.circle(small, (300, 250), 5, (255, 255, 255), -1)
    assert not card_glare(small)["rejected"]
    glare = ktp_image.copy()
    cv2.ellipse(glare, (300, 250), (95, 75), 0, 0, 360, (255, 255, 255), -1)
    assert card_glare(glare)["rejected"]
    assert not card_glare(np.full((200, 300, 3), (245, 220, 180), np.uint8))["rejected"]


def test_glare_is_rejected_before_document_and_holding_ocr(monkeypatch, ktp_image):
    crop = ktp_image.copy()
    cv2.rectangle(crop, (160, 120), (480, 280), (255, 255, 255), -1)
    candidate = [(1, crop, [20, 30, 856, 540])]
    monkeypatch.setattr("app.services.document.card_region", lambda _: candidate)
    monkeypatch.setattr("app.services.card.card_region", lambda _: candidate)
    ocr = SimpleNamespace(read=lambda _: pytest.fail("Glare must reject before OCR"))
    with pytest.raises(CaptureError, match="pantulan"):
        read_document(crop, ocr)
    with pytest.raises(CaptureError, match="pantulan"):
        HoldingCardService(ocr).read(crop)


def test_bright_scene_background_is_not_card_glare(monkeypatch, ktp_image):
    scene = np.full((900, 1300, 3), 255, np.uint8)
    scene[100:640, 100:956] = ktp_image
    monkeypatch.setattr(
        "app.services.document.card_region",
        lambda _: [(1, ktp_image, [100, 100, 856, 540])],
    )
    from test_document_reader import reading

    r = reading()
    ocr = SimpleNamespace(read=lambda _: deepcopy(r))
    result = read_document(scene, ocr)
    assert result["crop_method"] == "card_geometry" and not result["glare"]["rejected"]


def test_archive_extracts_only_pinned_member_and_rejects_tampering(tmp_path):
    archive = tmp_path / "weights.zip"
    target = tmp_path / "out.onnx"
    payload = b"fixture-model"
    with zipfile.ZipFile(archive, "w") as source:
        source.writestr("model.onnx", payload)
        source.writestr("../unexpected", b"no")
    item = {
        "file": "out.onnx",
        "archive_member": "model.onnx",
        "bytes": len(payload),
        "archive_bytes": archive.stat().st_size,
        "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
    extract_model(archive, target, item)
    assert (
        target.read_bytes() == payload and not (tmp_path.parent / "unexpected").exists()
    )
    item["sha256"] = "0" * 64
    with pytest.raises(RuntimeError):
        extract_model(archive, target, item)
    item["archive_sha256"] = "0" * 64
    with pytest.raises(RuntimeError):
        extract_model(archive, target, item)
