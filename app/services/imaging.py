import io
import cv2
import numpy as np
from PIL import Image, UnidentifiedImageError


class CaptureError(ValueError):
    pass


def decode_image(content):
    try:
        with Image.open(io.BytesIO(content)) as source:
            if source.format not in ['JPEG', 'PNG', 'WEBP']:
                raise CaptureError('Gunakan gambar JPG, PNG, atau WebP.')
            w, h = source.size
            if min(w, h) < 80 or w * h > 16_000_000:
                raise CaptureError('Resolusi gambar harus minimal 80 px dan maksimal 16 megapiksel.')
            from PIL import ImageOps
            rgb = np.asarray(ImageOps.exif_transpose(source).convert('RGB'))
        image = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        scale = min(1.0, 1600 / max(image.shape[:2]))
        return cv2.resize(image, None, fx=scale, fy=scale) if scale < 1 else image
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise CaptureError('Gambar tidak dapat dibaca.') from exc


def quality(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return {'blur': round(float(cv2.Laplacian(gray, cv2.CV_64F).var()), 2),
            'brightness': round(float(gray.mean()), 2), 'width': image.shape[1], 'height': image.shape[0]}


def card_region(image):
    """Find a card-sized quadrilateral; no learned document authenticity claim."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    edge = cv2.Canny(cv2.GaussianBlur(gray, (5, 5), 0), 45, 140)
    edge = cv2.morphologyEx(edge, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    contours, _ = cv2.findContours(edge, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    area = image.shape[0] * image.shape[1]
    candidates = []
    for contour in contours:
        approx = cv2.approxPolyDP(contour, .035 * cv2.arcLength(contour, True), True)
        a = cv2.contourArea(approx)
        if len(approx) != 4 or not cv2.isContourConvex(approx) or not .025 * area < a < .65 * area:
            continue
        points = approx.reshape(4, 2).astype(np.float32)
        sums, diffs = points.sum(axis=1), np.diff(points, axis=1).ravel()
        ordered = np.array([points[sums.argmin()], points[diffs.argmin()], points[sums.argmax()], points[diffs.argmax()]])
        width = max(np.linalg.norm(ordered[0]-ordered[1]), np.linalg.norm(ordered[2]-ordered[3]))
        height = max(np.linalg.norm(ordered[0]-ordered[3]), np.linalg.norm(ordered[1]-ordered[2]))
        if height < 40 or not 1.25 < width / height < 2.0:
            continue
        transform = cv2.getPerspectiveTransform(ordered, np.float32([[0, 0], [855, 0], [855, 539], [0, 539]]))
        crop = cv2.warpPerspective(image, transform, (856, 540))
        x, y, w, h = cv2.boundingRect(approx)
        candidates.append((a, crop, [x, y, w, h]))
    if not candidates:
        raise CaptureError('Bingkai KTP pada foto bersama KTP tidak ditemukan. Tampilkan kartu lebih besar, utuh, dan kontras dengan latar.')
    return sorted(candidates, key=lambda x: x[0], reverse=True)
