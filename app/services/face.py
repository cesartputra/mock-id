import cv2
import numpy as np
import onnxruntime as ort
from app.config import WEIGHTS
from app.services.antispoof import options
from app.services.imaging import CaptureError

FACE_MODEL_ID = "insightface-buffalo-l-w600k-r50"
FACE_MODEL = "InsightFace ArcFace ResNet50"
# Standard 112-pixel ArcFace reference (InsightFace face_align.py).
REFERENCE = np.array(
    [
        [38.2946, 51.6963],
        [73.5318, 51.5014],
        [56.0252, 71.7366],
        [41.5493, 92.3655],
        [70.7299, 92.2041],
    ],
    dtype=np.float64,
)


def align_face(image, face):
    points = np.asarray(face[4:14], dtype=np.float64).reshape(5, 2)
    if not np.isfinite(points).all() or np.linalg.norm(points[0] - points[1]) < 2:
        raise CaptureError("Landmark wajah belum cukup jelas untuk pencocokan.")
    # Fit a rotation, uniform scale and translation by least squares; no shear.
    matrix = np.zeros((10, 4), dtype=np.float64)
    matrix[0::2] = np.column_stack(
        (points[:, 0], -points[:, 1], np.ones(5), np.zeros(5))
    )
    matrix[1::2] = np.column_stack(
        (points[:, 1], points[:, 0], np.zeros(5), np.ones(5))
    )
    if np.linalg.matrix_rank(matrix) < 4:
        raise CaptureError("Landmark wajah tidak valid.")
    a, b, tx, ty = np.linalg.lstsq(matrix, REFERENCE.reshape(-1), rcond=None)[0]
    transform = np.array([[a, -b, tx], [b, a, ty]], dtype=np.float32)
    return cv2.warpAffine(
        image, transform, (112, 112), flags=cv2.INTER_LINEAR, borderValue=0
    )


class FaceService:
    def __init__(self):
        self.detector = cv2.FaceDetectorYN.create(
            str(WEIGHTS / "yunet.onnx"), "", (320, 320), 0.75, 0.3, 5000
        )
        self.recognizer = ort.InferenceSession(
            str(WEIGHTS / "arcface_r50.onnx"),
            options(),
            providers=["CPUExecutionProvider"],
        )
        self.input = self.recognizer.get_inputs()[0].name
        if self.recognizer.get_inputs()[0].shape[1:] != [3, 112, 112]:
            raise ValueError("Input ArcFace harus RGB 112 × 112.")

    def faces(self, image):
        found = []
        used = set()
        for target in [640, 320, 1280]:
            scale = min(1.0, target / max(image.shape[:2]))
            if scale in used:
                continue
            used.add(scale)
            sample = cv2.resize(image, None, fx=scale, fy=scale) if scale < 1 else image
            self.detector.setInputSize((sample.shape[1], sample.shape[0]))
            _, faces = self.detector.detect(sample)
            for face in ([] if faces is None else faces):
                face = face.copy()
                face[:14] /= scale
                x, y, w, h = face[:4]
                duplicate = False
                for other in found:
                    ox, oy, ow, oh = other[:4]
                    overlap = max(0, min(x + w, ox + ow) - max(x, ox)) * max(
                        0, min(y + h, oy + oh) - max(y, oy)
                    )
                    if overlap / max(w * h + ow * oh - overlap, 1) > 0.4:
                        duplicate = True
                        break
                if not duplicate:
                    found.append(face)
        return sorted(found, key=lambda f: float(f[2] * f[3]), reverse=True)

    def one(self, image, allow_small_extra=False):
        faces = self.faces(image)
        if not faces:
            raise CaptureError(
                "Wajah tidak ditemukan. Gunakan foto yang terang dan wajah terlihat utuh."
            )
        # A card portrait may also be detected in the holding photo.
        relevant = [f for f in faces if f[2] * f[3] > faces[0][2] * faces[0][3] * 0.35]
        if not allow_small_extra and len(relevant) != 1:
            raise CaptureError("Gunakan satu wajah dalam foto selfie.")
        return faces[0]

    def feature(self, image, face):
        aligned = align_face(image, face)
        tensor = cv2.dnn.blobFromImage(
            aligned, 1 / 127.5, (112, 112), (127.5, 127.5, 127.5), swapRB=True
        )
        feature = np.asarray(
            self.recognizer.run(None, {self.input: tensor})[0], dtype=np.float32
        ).reshape(-1)
        norm = float(np.linalg.norm(feature))
        if (
            feature.size != 512
            or not np.isfinite(feature).all()
            or not np.isfinite(norm)
            or norm < 1e-8
        ):
            raise ValueError("Embedding ArcFace tidak valid.")
        return feature / norm, aligned

    def compare(self, a, face_a, b, face_b):
        fa, _ = self.feature(a, face_a)
        fb, _ = self.feature(b, face_b)
        return float(np.clip(np.dot(fa, fb), -1, 1))
