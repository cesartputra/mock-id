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

    def score(self, image):
        # Independent image diagnostic: never reuse the 112px ArcFace alignment.
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        rgb = np.asarray(Image.fromarray(rgb).resize((224, 224), Image.Resampling.BILINEAR), dtype=np.float32)
        tensor = ((rgb / 255.0 - .5) / .5).transpose(2, 0, 1)[None]
        probs = softmax(self.model.run(None, {self.input: tensor})[0])
        return {'fake_probability': round(float(probs[1]), 5), 'real_probability': round(float(probs[0]), 5),
                'model': 'dima806 ViT / ONNX quantized', 'mode': 'real',
                'input_scope': 'full_camera_image', 'calibrated': False,
                'input_size': [int(image.shape[1]), int(image.shape[0])],
                'scope': 'Image classifier; bukan detektor seluruh jenis manipulasi video atau injection.'}
