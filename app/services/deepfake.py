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


    def assess(self, image, face):
        """Domain sensitivity is uncertainty, never proof of fraud.

        Fixed views are chosen before scoring; do not select a crop to maximize
        "real". The experimental disagreement limit is metadata, not calibration.
        """
        full = self.score(image)
        x, y, w, h = [float(v) for v in face[:4]]
        if not np.isfinite([x,y,w,h]).all() or w <= 0 or h <= 0:
            raise ValueError('Crop classifier tidak valid.')
        ih, iw = image.shape[:2]
        left, top = max(0, int(x)-20), max(0, int(y)-20)
        right, bottom = min(iw, int(x+w)+20), min(ih, int(y+h)+20)
        if not np.isfinite([x,y,w,h]).all() or right <= left or bottom <= top:
            raise ValueError('Crop classifier tidak valid.')
        context = self.score(image[top:bottom, left:right])
        gap = abs(full['fake_probability'] - context['fake_probability'])
        return {**full, 'reliable': bool(gap <= .25),
                'context_fake_probability': context['fake_probability'],
                'context_input_scope': 'native_face_region_plus_20px',
                'disagreement': gap, 'disagreement_threshold': .25,
                'assessment_profile': 'full-vs-native-context-v1',
                'scope': 'Experimental image evidence; disagreement requires review, not an AI/fraud verdict.'}
