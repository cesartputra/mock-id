import cv2
import numpy as np
from app.config import WEIGHTS
from app.services.imaging import CaptureError


class FaceService:
    def __init__(self):
        self.detector = cv2.FaceDetectorYN.create(str(WEIGHTS / 'yunet.onnx'), '', (320, 320), .75, .3, 5000)
        self.recognizer = cv2.FaceRecognizerSF.create(str(WEIGHTS / 'sface.onnx'), '')

    def faces(self, image):
        found=[]
        used=set()
        for target in [640,320,1280]:
            scale=min(1.0,target/max(image.shape[:2]))
            if scale in used:
                continue
            used.add(scale)
            sample=cv2.resize(image,None,fx=scale,fy=scale) if scale<1 else image
            self.detector.setInputSize((sample.shape[1],sample.shape[0]))
            _,faces=self.detector.detect(sample)
            for face in ([] if faces is None else faces):
                face=face.copy();face[:14]/=scale
                x,y,w,h=face[:4]
                duplicate=False
                for other in found:
                    ox,oy,ow,oh=other[:4]
                    overlap=max(0,min(x+w,ox+ow)-max(x,ox))*max(0,min(y+h,oy+oh)-max(y,oy))
                    if overlap/max(w*h+ow*oh-overlap,1)>.4:
                        duplicate=True
                        break
                if not duplicate:
                    found.append(face)
        return sorted(found,key=lambda f:float(f[2]*f[3]),reverse=True)

    def one(self, image, allow_small_extra=False):
        faces = self.faces(image)
        if not faces:
            raise CaptureError('Wajah tidak ditemukan. Gunakan foto yang terang dan wajah terlihat utuh.')
        # A card portrait may also be detected in the holding photo.
        relevant = [f for f in faces if f[2]*f[3] > faces[0][2]*faces[0][3]*.35]
        if not allow_small_extra and len(relevant) != 1:
            raise CaptureError('Gunakan satu wajah dalam foto selfie.')
        return faces[0]

    def feature(self, image, face):
        aligned = self.recognizer.alignCrop(image, face)
        return self.recognizer.feature(aligned), aligned

    def compare(self, a, face_a, b, face_b):
        fa, _ = self.feature(a, face_a)
        fb, _ = self.feature(b, face_b)
        return float(self.recognizer.match(fa, fb, cv2.FaceRecognizerSF_FR_COSINE))
