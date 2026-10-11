# Copyright 2026 Yakhyokhuja Valikhujaev
# Author: Yakhyokhuja Valikhujaev
# GitHub: https://github.com/yakhyo

from __future__ import annotations

import cv2
import numpy as np
import onnxruntime as ort

from .meanface import get_meanface_info


class PIPNetONNX:
    """PIPNet facial landmark detector (ONNX Runtime)."""

    _IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32) * 255.0
    _IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32) * 255.0
    _NUM_NB = 10

    def __init__(self, weights_path: str, providers: list[str] | None = None) -> None:
        """Load a PIPNet ONNX model.

        Args:
            weights_path: Path to the ONNX file.
            providers: ONNX Runtime execution providers. Defaults to
                auto-detected (CUDA > CoreML > CPU).
        """
        if providers is None:
            available = ort.get_available_providers()
            preferred = ['CUDAExecutionProvider', 'CoreMLExecutionProvider', 'CPUExecutionProvider']
            providers = [p for p in preferred if p in available]

        self.session = ort.InferenceSession(weights_path, providers=providers)

        input_cfg = self.session.get_inputs()[0]
        self.input_name = input_cfg.name
        _, _, self.input_h, self.input_w = input_cfg.shape

        outputs = self.session.get_outputs()
        self.output_names = [o.name for o in outputs]

        cls_shape = outputs[0].shape
        self.num_lms = int(cls_shape[1])
        self.feat_h = int(cls_shape[2]) if isinstance(cls_shape[2], int) else self.input_h // 32
        self.feat_w = int(cls_shape[3]) if isinstance(cls_shape[3], int) else self.input_w // 32
        self.net_stride = self.input_h // self.feat_h

        self._reverse_index1, self._reverse_index2, self._max_len = get_meanface_info(self.num_lms, self._NUM_NB)

    def get_landmarks(self, image: np.ndarray, bbox: np.ndarray) -> np.ndarray:
        """Detect landmarks inside a face bounding box.

        Args:
            image: Full input image in BGR format, shape ``(H, W, 3)``.
            bbox: ``[x1, y1, x2, y2]`` in original-image pixel coordinates.

        Returns:
            Landmark coordinates as a ``(num_lms, 2)`` float32 array in
            original-image pixel space.
        """
        crop, (x1, y1, crop_w, crop_h) = self._crop_face(image, bbox)
        blob = self._preprocess(crop)

        cls_map, offset_x, offset_y, nb_x, nb_y = self.session.run(
            self.output_names, {self.input_name: blob}
        )

        lms = self._decode(cls_map, offset_x, offset_y, nb_x, nb_y)
        lms[:, 0] = lms[:, 0] * crop_w + x1
        lms[:, 1] = lms[:, 1] * crop_h + y1
        return lms.astype(np.float32)

    def _crop_face(self, image: np.ndarray, bbox: np.ndarray) -> tuple[np.ndarray, tuple[int, int, int, int]]:
        img_h, img_w = image.shape[:2]
        x1, y1, x2, y2 = map(float, bbox[:4])
        det_w = x2 - x1 + 1
        det_h = y2 - y1 + 1

        # Upstream asymmetric crop: +10% left/right/bottom, -10% top.
        pad = 0.1
        x1 -= int(det_w * pad)
        y1 += int(det_h * pad)
        x2 += int(det_w * pad)
        y2 += int(det_h * pad)

        x1 = max(int(x1), 0)
        y1 = max(int(y1), 0)
        x2 = min(int(x2), img_w - 1)
        y2 = min(int(y2), img_h - 1)
        crop_w = x2 - x1 + 1
        crop_h = y2 - y1 + 1

        crop = image[y1 : y2 + 1, x1 : x2 + 1, :]
        return crop, (x1, y1, crop_w, crop_h)

    def _preprocess(self, crop: np.ndarray) -> np.ndarray:
        resized = cv2.resize(crop, (self.input_w, self.input_h))
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB).astype(np.float32)
        rgb = (rgb - self._IMAGENET_MEAN) / self._IMAGENET_STD
        blob = np.transpose(rgb, (2, 0, 1))[None, ...]
        return np.ascontiguousarray(blob, dtype=np.float32)

    def _decode(
        self,
        cls_map: np.ndarray,
        offset_x: np.ndarray,
        offset_y: np.ndarray,
        nb_x: np.ndarray,
        nb_y: np.ndarray,
    ) -> np.ndarray:
        n = self.num_lms
        nb = self._NUM_NB
        h = self.feat_h
        w = self.feat_w

        cls_flat = cls_map.reshape(n, h * w)
        max_ids = np.argmax(cls_flat, axis=1)
        cols = (max_ids % w).astype(np.float32)
        rows = (max_ids // w).astype(np.float32)

        off_x_flat = offset_x.reshape(n, h * w)
        off_y_flat = offset_y.reshape(n, h * w)
        own_x = np.take_along_axis(off_x_flat, max_ids[:, None], axis=1).squeeze(1)
        own_y = np.take_along_axis(off_y_flat, max_ids[:, None], axis=1).squeeze(1)

        # Neighbor channels are ordered (num_nb * num_lms); reshape so axis 1 is neighbor index.
        nb_x_flat = nb_x.reshape(n, nb, h * w)
        nb_y_flat = nb_y.reshape(n, nb, h * w)
        nb_ids = np.broadcast_to(max_ids[:, None, None], (n, nb, 1))
        nb_own_x = np.take_along_axis(nb_x_flat, nb_ids, axis=2).squeeze(2)
        nb_own_y = np.take_along_axis(nb_y_flat, nb_ids, axis=2).squeeze(2)

        scale_x = self.input_w / self.net_stride
        scale_y = self.input_h / self.net_stride
        pred_x = (cols + own_x) / scale_x
        pred_y = (rows + own_y) / scale_y

        nb_pred_x = (cols[:, None] + nb_own_x) / scale_x
        nb_pred_y = (rows[:, None] + nb_own_y) / scale_y

        # Reverse gather: collect predictions about landmark i made by its neighbors,
        # then average with landmark i's own prediction.
        rev_x = nb_pred_x.reshape(-1)[self._reverse_index1 * nb + self._reverse_index2].reshape(n, self._max_len)
        rev_y = nb_pred_y.reshape(-1)[self._reverse_index1 * nb + self._reverse_index2].reshape(n, self._max_len)

        merged_x = np.mean(np.concatenate([pred_x[:, None], rev_x], axis=1), axis=1)
        merged_y = np.mean(np.concatenate([pred_y[:, None], rev_y], axis=1), axis=1)

        return np.stack([merged_x, merged_y], axis=1)
