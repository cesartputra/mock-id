"""Cheap exposure preflight; no face model, image enhancement or identity claim."""
import cv2

from app.services.imaging import CaptureError

DARK_MESSAGE = 'Ruangan terlalu gelap, pindah ke tempat terang'
MIN_LUMINANCE = 35
# Normalized native-video regions, shared with LuminanceCheck in quality-gate.js.
# Sample the guide area rather than letting a bright window dominate the mean.
REGIONS = {
    'selfie': (.35, .20, .65, .80),
    'holding': (.35, .10, .65, .55),
    'document': (.20, .15, .80, .85),
}


def luminance_check(image, context='selfie', *, face_box=None):
    if image is None or image.ndim != 3 or image.shape[2] != 3 or not image.size:
        raise CaptureError('Gambar kamera belum tersedia.')
    height, width = image.shape[:2]
    if face_box is None:
        left, top, right, bottom = REGIONS[context]
        x1, y1 = int(width * left), int(height * top)
        x2, y2 = max(x1 + 1, int(width * right)), max(y1 + 1, int(height * bottom))
        scope = 'guide_region'
    else:
        x, y, w, h = face_box
        x1, y1 = max(0, int(x)), max(0, int(y))
        x2, y2 = min(width, int(x + w)), min(height, int(y + h))
        scope = 'detected_face'
    region = image[y1:y2, x1:x2]
    if not region.size:
        raise CaptureError('Area pemeriksaan kamera belum tersedia.')
    # OpenCV BGR2GRAY uses Y = .299 R + .587 G + .114 B, on a 0–255 scale.
    mean = float(cv2.cvtColor(region, cv2.COLOR_BGR2GRAY).mean())
    ready = mean > MIN_LUMINANCE
    return {'ready': ready, 'brightness': round(mean, 2),
            'minimum': MIN_LUMINANCE, 'scope': scope, 'mode': 'exposure_precheck',
            'warnings': [] if ready else [{'code': 'too_dark', 'message': DARK_MESSAGE}]}


def dark_feedback(light):
    return {'ready': False, 'warnings': light['warnings'], 'face_box': None,
            'attributes': {}, 'luminance': light, 'mode': 'exposure_precheck'}


def require_luminance(image, context='selfie'):
    light = luminance_check(image, context)
    if not light['ready']:
        raise CaptureError(DARK_MESSAGE)
    return light
