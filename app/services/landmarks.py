"""CPU-only ONNX landmarks: PIPNet face and OpenCV Zoo MediaPipe hands."""
import numpy as np
from app.config import WEIGHTS
from app.services.vendor.pipnet.pipnet_onnx import PIPNetONNX
from app.services.vendor.mp_palmdet import MPPalmDet
from app.services.vendor.mp_handpose import MPHandPose
from app.services.imaging import CaptureError


def distance(a, b):
    return float(np.linalg.norm(a-b))


def eye_ratio(points):
    return (distance(points[1], points[5])+distance(points[2], points[4])) / max(2*distance(points[0], points[3]), 1)


class LandmarkService:
    def __init__(self, face_service):
        self.detector = face_service
        self.face = PIPNetONNX(str(WEIGHTS / 'pipnet.onnx'), providers=['CPUExecutionProvider'])
        self.palm = MPPalmDet(str(WEIGHTS / 'palm.onnx'), scoreThreshold=.70)
        self.hand = MPHandPose(str(WEIGHTS / 'handpose.onnx'), confThreshold=.70)

    def metrics(self, image):
        face = self.detector.one(image)
        x, y, w, h = face[:4]
        points = self.face.get_landmarks(image, np.array([x, y, x+w, y+h]))
        ear = (eye_ratio(points[36:42])+eye_ratio(points[42:48]))/2
        # Mouth width relative to distance between outer eye corners; baseline is
        # measured from the neutral frames, never supplied by a demo scenario.
        smile = distance(points[48], points[54]) / max(distance(points[36], points[45]), 1)
        yaw = (points[30, 0]-(points[0, 0]+points[16, 0])/2) / max(abs(points[16, 0]-points[0, 0]), 1)
        return {'blink': float(ear), 'smile': float(smile), 'yaw': float(yaw)}

    def challenges(self, frames, manifest, required):
        output = []
        for challenge in required:
            group = [self.metrics(frame) for frame, info in zip(frames, manifest) if info['challenge'] == challenge]
            if len(group) < 8:
                raise CaptureError('Rekam minimal delapan frame untuk setiap tantangan.')
            key = 'yaw' if challenge == 'turn' else challenge
            values = np.array([m[key] for m in group])
            baseline = float(np.median(values[:4]))
            action = values[4:]
            if challenge == 'blink':
                passed = baseline >= .22 and float(action.min()) <= min(.19, baseline*.70)
                rule = {'neutral_ear_min': .22, 'closed_ear_max': .19, 'closed_ratio_max': .70}
            elif challenge == 'smile':
                passed = float(action.max()) >= baseline*1.10 and float(action.max()-baseline) >= .06
                rule = {'width_ratio_min': 1.10, 'width_change_min': .06}
            else:
                passed = float(np.max(np.abs(action-baseline))) >= .12
                rule = {'yaw_change_min': .12}
            output.append({'challenge': challenge, 'passed': bool(passed), 'baseline': round(baseline, 4),
                           'min': round(float(values.min()), 4), 'max': round(float(values.max()), 4),
                           'frames': len(group), 'rule': rule, 'mode': 'real'})
        return {'passed': all(v['passed'] for v in output), 'challenges': output,
                'model': 'PIPNet 68 / ONNX CPU', 'mode': 'real',
                'scope': 'Gerakan landmark dengan baseline netral; ambang perlu kalibrasi kamera dan populasi.'}

    def hands(self, image):
        found = []
        for palm in self.palm.infer(image)[:4]:
            result = self.hand.infer(image, palm)
            if result is not None:
                found.append(result[4:67].reshape(21,3))
        return found

    def hand_near_card(self, image, box):
        hands = self.hands(image)
        x, y, w, h = box
        margin = max(w,h)*.16
        close = sum(sum(x-margin <= p[0] <= x+w+margin and y-margin <= p[1] <= y+h+margin for p in points) >= 3 for points in hands)
        return {'passed':close>0,'hands_detected':len(hands),'hands_near_card':int(close),
                'model':'OpenCV Zoo MediaPipe Palm + Hand ONNX CPU','mode':'real',
                'scope':'Kedekatan landmark tangan dengan bingkai kartu; bukan bukti keaslian fisik dokumen.'}
