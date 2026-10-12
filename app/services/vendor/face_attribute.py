# Copyright 2026 Yakhyokhuja Valikhujaev
# Author: Yakhyokhuja Valikhujaev
# GitHub: https://github.com/yakhyo

"""FaceAttribNet ONNX Runtime inference and shared preprocessing.

FaceAttribNet expects a 128x128 RGB tensor in NCHW layout with values in [0, 1].
Mean/std normalization is baked into the graph itself (`(x - 0.5) / 0.50196078`
inside `forward_intermediate`), so callers must *not* normalize a second time.
The preprocessing helpers here are shared by the PyTorch demo (`main.py`) and
the ONNX exporter; this module itself stays torch-free.
"""

from __future__ import annotations

from dataclasses import astuple, dataclass

import cv2
import numpy as np
import onnxruntime as ort

ATTRIBUTE_NAMES = (
    'left_eye_open',
    'right_eye_open',
    'eyeglasses',
    'mask',
    'sunglasses',
)

INPUT_SIZE = (128, 128)


def resize_pad(image: np.ndarray, size: tuple[int, int] = INPUT_SIZE) -> np.ndarray:
    """Resize preserving aspect ratio, then zero-pad to `size` with the image centered.

    Mirrors `qai_hub_models.utils.image_processing.resize_pad`, which the upstream
    demo uses. A square input degenerates to a plain resize.

    Args:
        image: Input image, shape (H, W, C).
        size: Target (height, width).

    Returns:
        Letterboxed image of shape (size[0], size[1], C).
    """
    dst_h, dst_w = size
    h, w = image.shape[:2]

    scale = min(dst_h / h, dst_w / w)
    new_h, new_w = int(np.floor(h * scale)), int(np.floor(w * scale))
    # Whichever dimension is the binding constraint lands exactly on target.
    if dst_h / h < dst_w / w:
        new_h = dst_h
    else:
        new_w = dst_w

    interpolation = cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR
    resized = cv2.resize(image, (new_w, new_h), interpolation=interpolation)

    canvas = np.zeros((dst_h, dst_w, image.shape[2]), dtype=image.dtype)
    top, left = (dst_h - new_h) // 2, (dst_w - new_w) // 2
    canvas[top : top + new_h, left : left + new_w] = resized
    return canvas


def crop_face(image: np.ndarray, bbox: np.ndarray, margin: float = 0.0) -> np.ndarray:
    """Crop a face region out of a full image, clamped to the image bounds.

    Args:
        image: Full image, shape (H, W, C).
        bbox: Bounding box as (x1, y1, x2, y2).
        margin: Fraction of box size to expand the crop by on each side.

    Returns:
        The cropped region.

    Raises:
        ValueError: If `image` or `bbox` is None, or the box lies outside the image.
    """
    if image is None or bbox is None:
        raise ValueError('Image and bbox must not be None')

    h, w = image.shape[:2]
    x1, y1, x2, y2 = (float(v) for v in bbox[:4])

    if margin:
        dw, dh = (x2 - x1) * margin, (y2 - y1) * margin
        x1, y1, x2, y2 = x1 - dw, y1 - dh, x2 + dw, y2 + dh

    x1, y1 = max(0, int(round(x1))), max(0, int(round(y1)))
    x2, y2 = min(w, int(round(x2))), min(h, int(round(y2)))

    if x2 <= x1 or y2 <= y1:
        raise ValueError(f'Bounding box {bbox[:4]} does not overlap the {w}x{h} image')

    return image[y1:y2, x1:x2]


def to_blob(face_image: np.ndarray, size: tuple[int, int] = INPUT_SIZE) -> np.ndarray:
    """Convert a BGR face crop into the model's input blob.

    Args:
        face_image: BGR face crop, shape (H, W, 3).
        size: Target (height, width).

    Returns:
        Blob of shape (1, 3, H, W), float32, values in [0, 1], RGB channel order.
    """
    padded = resize_pad(face_image, size)
    rgb = cv2.cvtColor(padded, cv2.COLOR_BGR2RGB)
    blob = rgb.astype(np.float32) / 255.0
    return np.transpose(blob, (2, 0, 1))[np.newaxis, ...]


@dataclass
class FaceAttributeResult:
    """Per-attribute probabilities in [0, 1].

    Each attribute comes from its own independent binary classifier head, so the
    five values do not sum to 1 and several can be high at once (a face can wear
    both sunglasses and a mask). Threshold each one separately; never argmax.

    Attributes:
        left_eye_open: Probability the left eye is open.
        right_eye_open: Probability the right eye is open.
        eyeglasses: Probability eyeglasses are present.
        mask: Probability a face mask is present.
        sunglasses: Probability sunglasses are present.
    """

    left_eye_open: float
    right_eye_open: float
    eyeglasses: float
    mask: float
    sunglasses: float

    def as_dict(self) -> dict[str, float]:
        """Return the attributes as a name -> probability mapping."""
        return dict(zip(ATTRIBUTE_NAMES, astuple(self), strict=True))

    def labels(self, threshold: float = 0.5) -> list[str]:
        """Return the names of attributes whose probability exceeds `threshold`."""
        return [name for name, value in self.as_dict().items() if value > threshold]

    def __repr__(self) -> str:
        body = ', '.join(f'{name}={value:.4f}' for name, value in self.as_dict().items())
        return f'FaceAttributeResult({body})'


class FaceAttribute:
    """FaceAttribNet ONNX Runtime inference.

    Predicts eye openness, eyeglasses, face mask, and sunglasses from a 128x128
    face crop.

    Source: https://github.com/qualcomm/ai-hub-models/tree/main/src/qai_hub_models/models/face_attrib_net
    """

    def __init__(self, model_path: str, providers: list[str] | None = None) -> None:
        self.model_path = model_path

        if providers is None:
            available = ort.get_available_providers()
            preferred = ['CUDAExecutionProvider', 'CoreMLExecutionProvider', 'CPUExecutionProvider']
            providers = [p for p in preferred if p in available]

        self.session = ort.InferenceSession(model_path, providers=providers)

        input_config = self.session.get_inputs()[0]
        self.input_name = input_config.name
        # (H, W) — the released graph is fixed at 128x128.
        self.input_size = tuple(input_config.shape[2:4])
        self.output_name = self.session.get_outputs()[0].name

    def predict(self, image: np.ndarray, bbox: np.ndarray, margin: float = 0.0) -> FaceAttributeResult:
        """Crop a face out of a full image by bounding box, then run inference.

        Args:
            image: Full BGR image, shape (H, W, 3).
            bbox: Bounding box as (x1, y1, x2, y2).
            margin: Fraction of box size to expand the crop by on each side.

        Returns:
            Predicted attribute probabilities.
        """
        blob = to_blob(crop_face(image, bbox, margin), self.input_size)
        output = self.session.run([self.output_name], {self.input_name: blob})[0]
        return FaceAttributeResult(*np.squeeze(output).astype(float).tolist())
