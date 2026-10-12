"""Real face attribute inference and conservative capture-visibility feedback."""
import numpy as np
from app.config import WEIGHTS
from app.services.vendor.face_attribute import FaceAttribute
from app.services.imaging import quality


class FaceVisibilityService:
    def __init__(self, face_service, landmarks):
        self.face = face_service
        self.landmarks = landmarks
        self.attributes = FaceAttribute(str(WEIGHTS/'face_attrib.onnx'), providers=['CPUExecutionProvider'])

    def inspect(self, image, holding=False):
        warnings = []
        def warn(code, message):
            warnings.append({'code':code,'message':message})
        faces = self.face.faces(image)
        if not faces:
            warn('face_missing', 'Wajah belum terlihat utuh. Singkirkan penutup wajah dan posisikan wajah di depan kamera.')
            return {'ready':False,'warnings':warnings,'attributes':{},'face_box':None,'mode':'real'}
        face = faces[0]
        relevant = [f for f in faces if f[2]*f[3] > face[2]*face[3]*.35]
        if len(relevant) > 1 and not holding:
            warn('multiple_faces','Tampilkan hanya satu wajah pemohon di kamera.')
        x,y,w,h = [float(v) for v in face[:4]]
        ih,iw = image.shape[:2]
        if min(w,h) < 70:
            warn('face_small','Dekatkan wajah ke kamera agar mata, hidung, dan mulut terlihat jelas.')
        if x < 2 or y < 2 or x+w > iw-2 or y+h > ih-2:
            warn('face_cropped','Seluruh wajah harus masuk bingkai; jangan memotong dahi atau dagu.')
        box=np.array([x,y,x+w,y+h])
        attributes = self.attributes.predict(image,box).as_dict()
        if attributes['mask'] >= .60:
            warn('mask','Lepaskan masker atau penutup mulut dan hidung sebelum melanjutkan.')
        if attributes['sunglasses'] >= .60:
            warn('sunglasses','Lepaskan kacamata hitam agar kedua mata terlihat jelas.')
        elif attributes['eyeglasses'] >= .60:
            warn('eyeglasses','Lepaskan kacamata untuk pemeriksaan wajah; hindari pantulan pada mata.')
        # Eye openness is feedback only; a blink challenge must remain possible.
        q=quality(image[max(0,int(y)):min(ih,int(y+h)),max(0,int(x)):min(iw,int(x+w))])
        if not 35 < q['brightness'] < 235:
            warn('lighting','Perbaiki pencahayaan wajah; hindari gelap dan silau.')
        if q['blur'] < 25:
            warn('blur','Wajah tampak buram. Diam sejenak dan bersihkan lensa kamera.')
        # Detect a physical hand overlapping the central face; does not classify
        # every possible object. Unrecognized occluders can still cause no-face.
        hands = self.landmarks.hands(image)
        for points in hands:
            inside=((points[:,0]>x+w*.12)&(points[:,0]<x+w*.88)&(points[:,1]>y+h*.15)&(points[:,1]<y+h*.88))
            if int(inside.sum()) >= 4:
                warn('hand_on_face','Jauhkan tangan atau benda yang menutupi mata, hidung, dan mulut.')
                break
        return {'ready':not warnings,'warnings':warnings,'attributes':{k:round(v,4) for k,v in attributes.items()},
                'face_box':[round(x),round(y),round(w),round(h)],'quality':q,'mode':'real',
                'model':'FaceAttribNet / ONNX CPU',
                'scope':'Model kacamata/masker, deteksi wajah dan tangan; tidak menjamin seluruh jenis penutup terdeteksi.'}
