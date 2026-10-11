import cv2
import numpy as np
import onnxruntime as ort
from PIL import Image
from app.config import WEIGHTS
from app.services.antispoof import options, softmax


class DeepfakeService:
    def __init__(self):
        self.model = ort.InferenceSession(str(WEIGHTS / 'deepfake.onnx'), options(), providers=['CPUExecutionProvider'])
        self.input = self.model.get_inputs()[0].name

    def score(self, face_crop):
        rgb = cv2.cvtColor(face_crop, cv2.COLOR_BGR2RGB)
        rgb = np.asarray(Image.fromarray(rgb).resize((224, 224), Image.Resampling.BILINEAR), dtype=np.float32)
        tensor = ((rgb / 255.0 - .5) / .5).transpose(2, 0, 1)[None]
        probs = softmax(self.model.run(None, {self.input: tensor})[0])
        return {'fake_probability': round(float(probs[1]), 5), 'real_probability': round(float(probs[0]), 5),
                'model': 'dima806 ViT / ONNX quantized', 'mode': 'real',
                'scope': 'Image classifier; bukan detektor seluruh jenis manipulasi video atau injection.'}
