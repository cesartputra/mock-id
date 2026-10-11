import cv2
import numpy as np
import onnxruntime as ort
from app.config import WEIGHTS


def options():
    opt = ort.SessionOptions()
    opt.intra_op_num_threads = 2
    opt.inter_op_num_threads = 1
    return opt


def softmax(logits):
    values = np.asarray(logits, dtype=np.float64).reshape(-1)
    values = np.exp(values-values.max())
    return values / values.sum()


class AntiSpoofService:
    def __init__(self):
        self.model = ort.InferenceSession(str(WEIGHTS / 'minifasnet.onnx'), options(), providers=['CPUExecutionProvider'])
        self.input = self.model.get_inputs()[0].name

    def score(self, image, face):
        x, y, w, h = [float(v) for v in face[:4]]
        ih, iw = image.shape[:2]
        scale = min((ih-1)/h, (iw-1)/w, 2.7)
        cx, cy = x+w/2, y+h/2
        nw, nh = w*scale, h*scale
        # Translate the scaled crop inside the image, preserving its training aspect.
        left, top = max(0, cx-nw/2), max(0, cy-nh/2)
        left, top = min(left, iw-nw-1), min(top, ih-nh-1)
        crop = image[int(top):int(top+nh)+1, int(left):int(left+nw)+1]
        tensor = cv2.resize(crop, (80, 80)).astype(np.float32).transpose(2, 0, 1)[None]
        # Upstream MiniFASNetV2 expects BGR 0..255, real class index 1.
        probs = softmax(self.model.run(None, {self.input: tensor})[0])
        return {'live_probability': round(float(probs[1]), 5), 'class_probabilities': probs.tolist(), 'model': 'MiniFASNetV2', 'mode': 'real'}
