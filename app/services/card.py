"""Locate the held card using geometry, reference features, or OCR text layout.

All paths require a fresh NIK reading from the holding photo. A reference NIK
is only used to rank candidates; it is never copied into an OCR result.
"""
import cv2
import numpy as np
from app.services.imaging import CaptureError, card_region, warp_card
from app.services.ocr import nik_match


class HoldingCardService:
    def __init__(self, ocr):
        self.ocr = ocr

    def template_region(self, image, reference):
        if reference is None:
            return None
        sift = cv2.SIFT_create(nfeatures=1600)
        a, da = sift.detectAndCompute(cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY), None)
        b, db = sift.detectAndCompute(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), None)
        if da is None or db is None or len(a) < 12 or len(b) < 12:
            return None
        pairs = cv2.BFMatcher().knnMatch(da, db, k=2)
        matches = [m for pair in pairs if len(pair) == 2 for m, n in [pair] if m.distance < .70*n.distance]
        if len(matches) < 12:
            return None
        src = np.float32([a[m.queryIdx].pt for m in matches])
        dst = np.float32([b[m.trainIdx].pt for m in matches])
        matrix, inliers = cv2.findHomography(src, dst, cv2.RANSAC, 4.0)
        if matrix is None or inliers is None or inliers.sum() < 10 or inliers.mean() < .45:
            return None
        # Require feature evidence spread over the reference, not a tiny logo.
        supported = src[inliers.ravel().astype(bool)]
        if np.ptp(supported[:, 0]) < reference.shape[1]*.25 or np.ptp(supported[:, 1]) < reference.shape[0]*.20:
            return None
        rh, rw = reference.shape[:2]
        corners = cv2.perspectiveTransform(np.float32([[[0,0],[rw-1,0],[rw-1,rh-1],[0,rh-1]]]), matrix)[0]
        ih, iw = image.shape[:2]
        if not np.isfinite(corners).all() or not cv2.isContourConvex(corners.astype(np.int32)):
            return None
        if (corners[:,0] < -iw*.03).any() or (corners[:,0] > iw*1.03).any() or (corners[:,1] < -ih*.03).any() or (corners[:,1] > ih*1.03).any():
            return None
        area = abs(cv2.contourArea(corners))
        if not .004*iw*ih < area < .85*iw*ih:
            return None
        return area, warp_card(image, corners), list(cv2.boundingRect(corners.astype(np.int32)))

    def text_region(self, image, reading):
        boxes, lines = reading['boxes'], reading['lines']
        for i, line in enumerate(lines):
            if not nik_match(line) or i >= len(boxes):
                continue
            anchor = np.asarray(boxes[i], dtype=np.float32)
            # Rectify local text orientation; collect nearby KTP labels only.
            center = anchor.mean(axis=0)
            width = max(float(np.linalg.norm(anchor[1]-anchor[0])), 80)
            nearby = [(text, np.asarray(box, dtype=np.float32)) for text, box in zip(lines, boxes)
                      if abs(np.asarray(box).mean(axis=0)[0]-center[0]) < width*1.2
                      and center[1]-width*.55 < np.asarray(box).mean(axis=0)[1] < center[1]+width*.85]
            labels = ['NIK', 'NAMA', 'ALAMAT', 'PROVINSI', 'KABUPATEN', 'KECAMATAN', 'LAHIR', 'BERLAKU', 'JENIS', 'KARTU']
            found = {label for text, _ in nearby for label in labels if label in text.upper()}
            if len(found) < 2:
                continue
            points = np.concatenate([box for _, box in nearby])
            x, y, w, h = cv2.boundingRect(points.astype(np.int32))
            # Extend the text block to the card's portrait/right edge and border.
            pad = width*.08
            x1, y1 = max(0,int(x-pad)), max(0,int(y-pad))
            x2, y2 = min(image.shape[1],int(x+w+width*.38)), min(image.shape[0],int(y+h+pad))
            if x2-x1 < 120 or y2-y1 < 60:
                continue
            return (image[y1:y2,x1:x2].copy(), [x1,y1,x2-x1,y2-y1])
        return None

    def read(self, image, reference=None, expected_nik=None):
        try:
            candidates = card_region(image)
        except CaptureError:
            candidates = []
        matched = self.template_region(image, reference)
        if matched:
            candidates.insert(0, matched)
        mismatch = None
        for _, crop, box in candidates[:6]:
            reading = self.ocr.read(crop)
            if not reading['fields']['nik']:
                gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
                enhanced = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8)).apply(gray)
                reading = self.ocr.read(cv2.cvtColor(enhanced, cv2.COLOR_GRAY2BGR))
            if reading['fields']['nik']:
                result = {'reading': reading, 'box': box, 'method': 'reference_features' if matched and box == matched[2] else 'card_geometry'}
                if not expected_nik or reading['fields']['nik'] == expected_nik:
                    return result
                mismatch = mismatch or result
        # OCR can work even when fingers break all four border contours.
        full = self.ocr.read(image)
        region = self.text_region(image, full)
        if region:
            crop, box = region
            reading = self.ocr.read(crop)
            if reading['fields']['nik']:
                result = {'reading': reading, 'box': box, 'method': 'ocr_text_layout'}
                if not expected_nik or reading['fields']['nik'] == expected_nik:
                    return result
                mismatch = mismatch or result
        if mismatch:
            return mismatch
        if candidates or region:
            raise CaptureError('Area KTP ditemukan, tetapi NIK belum terbaca. Dekatkan kartu, gunakan resolusi asli, dan hindari silau atau jari pada teks.')
        raise CaptureError('KTP belum ditemukan pada foto bersama KTP. Tampilkan kartu lebih besar di bawah dagu, tanpa menutup teks. Bingkai atau susunan teks kartu harus terlihat.')
