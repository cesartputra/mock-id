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
        scale = min(1.0, 1920 / max(image.shape[:2]))
        return cv2.resize(image, None, fx=scale, fy=scale) if scale < 1 else image
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise CaptureError('Gambar tidak dapat dibaca.') from exc


def quality(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return {'blur': round(float(cv2.Laplacian(gray, cv2.CV_64F).var()), 2),
            'brightness': round(float(gray.mean()), 2), 'width': image.shape[1], 'height': image.shape[0]}


def warp_card(image, points):
    points = np.asarray(points, dtype=np.float32).reshape(4, 2)
    center = points.mean(axis=0)
    ordered = points[np.argsort(np.arctan2(points[:,1]-center[1], points[:,0]-center[0]))]
    ordered = np.roll(ordered, -np.argmin(ordered.sum(axis=1)), axis=0)
    # Keep the long side horizontal, including rotated landscape cards.
    if np.linalg.norm(ordered[1]-ordered[0]) < np.linalg.norm(ordered[3]-ordered[0]):
        ordered = np.roll(ordered, -1, axis=0)
    transform = cv2.getPerspectiveTransform(ordered, np.float32([[0,0],[855,0],[855,539],[0,539]]))
    return cv2.warpPerspective(image, transform, (856,540))


def card_region(image):
    """Rank geometric candidates; OCR/reference evidence decides card validity."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    area = image.shape[0]*image.shape[1]
    candidates = []
    edges = [cv2.Canny(cv2.GaussianBlur(gray,(3,3),0),low,high) for low,high in [(25,90),(60,160)]]
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    # Indonesian ID cards are commonly blue; this is only an ROI proposal.
    edges.append(cv2.inRange(hsv,np.array([75,25,45]),np.array([135,255,255])))
    for edge in edges:
        edge = cv2.morphologyEx(edge,cv2.MORPH_CLOSE,np.ones((5,5),np.uint8))
        contours,_ = cv2.findContours(edge,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            if cv2.contourArea(contour) < max(100,.003*area):
                continue
            hull = cv2.convexHull(contour)
            approx = cv2.approxPolyDP(hull,.035*cv2.arcLength(hull,True),True)
            if len(approx)==4 and cv2.isContourConvex(approx):
                points=approx.reshape(4,2).astype(np.float32)
            else:
                rect=cv2.minAreaRect(hull)
                rect_area=rect[1][0]*rect[1][1]
                if rect_area<=0 or cv2.contourArea(hull)/rect_area<.68:
                    continue
                points=cv2.boxPoints(rect)
            a=abs(cv2.contourArea(points))
            rect=cv2.minAreaRect(points);short,long=sorted(rect[1])
            if not .004*area<a<.90*area or short<55 or long<125 or not 1.15<long/max(short,1)<2.5:
                continue
            box=list(cv2.boundingRect(points.astype(np.int32)))
            x,y,w,h=box
            if x<0 or y<0 or x+w>image.shape[1]+2 or y+h>image.shape[0]+2:
                continue
            if any(abs(x-b[0])+abs(y-b[1])+abs(w-b[2])+abs(h-b[3])<30 for _,_,b in candidates):
                continue
            candidates.append((a,warp_card(image,points),box))
    if not candidates:
        raise CaptureError('Bingkai kartu belum ditemukan.')
    return sorted(candidates,key=lambda v:v[0],reverse=True)[:12]
