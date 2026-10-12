"""CVPR 2024 Swin V2-B face PAD, exported from the official checkpoint."""
import cv2
import numpy as np
import onnxruntime as ort
from app.config import WEIGHTS
from app.services.imaging import CaptureError

PAD_FILE = 'cvpr2024_swin_v2_face.onnx'
PAD_MODEL = 'CVPR 2024 Swin V2-B (face)'
PAD_SOURCE = 'https://github.com/Xianhua-He/cvpr2024-face-anti-spoofing-challenge'
PAD_REVISION = '2b7e9d2f6af93e33806c11ad48f735f1c1810dad'


def options():
    opt = ort.SessionOptions()
    opt.intra_op_num_threads = 2
    opt.inter_op_num_threads = 1
    return opt


def softmax(logits):
    values = np.asarray(logits, dtype=np.float64).reshape(-1)
    if not np.isfinite(values).all():
        raise ValueError('Output model tidak valid.')
    values = np.exp(values-values.max())
    return values / values.sum()


def face_tensor(image, face):
    """Face-area checkpoint: 20 px margin, RGB 224², ImageNet normalization."""
    x, y, w, h = [float(v) for v in face[:4]]
    if not np.isfinite([x, y, w, h]).all() or w <= 0 or h <= 0:
        raise CaptureError('Bingkai wajah tidak valid untuk anti-spoof.')
    ih, iw = image.shape[:2]
    left, top = max(0, int(x)-20), max(0, int(y)-20)
    right, bottom = min(iw, int(x+w)+20), min(ih, int(y+h)+20)
    if right <= left or bottom <= top:
        raise CaptureError('Area wajah tidak tersedia untuk anti-spoof.')
    crop = image[top:bottom, left:right]
    rgb = cv2.cvtColor(cv2.resize(crop, (224, 224), interpolation=cv2.INTER_LINEAR), cv2.COLOR_BGR2RGB)
    mean = np.array([.485, .456, .406], dtype=np.float32)
    std = np.array([.229, .224, .225], dtype=np.float32)
    normalized = (rgb.astype(np.float32)/np.float32(255)-mean)/std
    return np.ascontiguousarray(normalized.transpose(2, 0, 1)[None], dtype=np.float32)


class AntiSpoofService:
    def __init__(self):
        self.model = ort.InferenceSession(str(WEIGHTS / PAD_FILE), options(), providers=['CPUExecutionProvider'])
        model_input = self.model.get_inputs()[0]
        output = self.model.get_outputs()[0]
        if model_input.shape != [1, 3, 224, 224] or output.shape != [1, 2]:
            raise ValueError('Kontrak model Swin V2 anti-spoof tidak sesuai.')
        self.input = model_input.name

    def score(self, image, face):
        logits = self.model.run(None, {self.input: face_tensor(image, face)})[0]
        probs = softmax(logits)
        if len(probs) != 2:
            raise ValueError('Model anti-spoof harus memiliki dua kelas.')
        # Official CVPR checkpoint labels are LIVE=0, SPOOF=1. MiniFASNet's
        # previous live index was 1 and must not be reused for this model.
        return {'live_probability': round(float(probs[0]), 5),
                'spoof_probability': round(float(probs[1]), 5),
                'class_probabilities': probs.tolist(), 'class_labels': ['live', 'spoof'],
                'model': PAD_MODEL, 'checkpoint': 'face_swin_v2_base.pth',
                'source_revision': PAD_REVISION, 'runtime': 'ONNX / CPU', 'mode': 'real',
                'scope': 'Model PAD physical/digital; skor dan ambang belum dikalibrasi untuk kamera KYC lokal.'}
