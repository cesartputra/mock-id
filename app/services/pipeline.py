import hashlib
import logging
import threading
import time
import uuid
from pathlib import Path

from app.config import WEIGHTS
from app.model.repository import utcnow
from app.services.imaging import CaptureError, card_region, quality
from app.services.ocr import OCRService
from app.services.face import FaceService
from app.services.antispoof import AntiSpoofService
from app.services.deepfake import DeepfakeService
from app.services.landmarks import LandmarkService
from app.services.dukcapil import DukcapilService
from app.services.assets import verify_assets

log = logging.getLogger(__name__)


class ModelUnavailable(RuntimeError):
    pass


MODEL_FILES = ['yunet.onnx', 'sface.onnx', 'minifasnet.onnx', 'deepfake.onnx', 'pipnet.onnx', 'palm.onnx', 'handpose.onnx']


class VerificationService:
    def __init__(self, repository):
        self.repository = repository
        self.lock = threading.RLock()
        self.ocr = OCRService()
        self.face = self.pad = self.deepfake = self.landmarks = None
        self.dukcapil = DukcapilService()
        self.last_error = None
        self.assets_verified = False

    def availability(self):
        files = {f: (WEIGHTS / f).is_file() for f in MODEL_FILES}
        files['ocr'] = len(list((WEIGHTS / 'ocr').glob('*.onnx'))) >= 3
        return {'ready': all(files.values()), 'files': files, 'loaded': self.face is not None,
                'last_error': self.last_error, 'dukcapil': 'mock', 'inference': 'real'}

    def load(self):
        missing = [name for name, exists in self.availability()['files'].items() if not exists]
        if missing:
            raise ModelUnavailable('Model belum tersedia: '+', '.join(missing)+'. Jalankan python scripts/setup_models.py.')
        if not self.assets_verified:
            invalid = verify_assets()
            if invalid:
                raise ModelUnavailable('Checksum model tidak cocok: '+', '.join(invalid))
            self.assets_verified = True
        if self.face is None:
            face = FaceService()
            pad = AntiSpoofService()
            deepfake = DeepfakeService()
            landmarks = LandmarkService(face)
            self.ocr.load()
            self.face, self.pad, self.deepfake, self.landmarks = face, pad, deepfake, landmarks

    def document(self, image):
        with self.lock:
            if not self.availability()['files']['ocr']:
                raise ModelUnavailable('Model OCR belum diunduh. Jalankan python scripts/setup_models.py.')
            if not self.assets_verified:
                invalid = verify_assets()
                if invalid:
                    raise ModelUnavailable('Model hilang/berubah: '+', '.join(invalid))
                self.assets_verified = True
            q = quality(image)
            result = self.ocr.read(image)
            result['quality'] = q
            if not result['fields']['nik']:
                raise CaptureError('NIK 16 digit belum terbaca dari KTP. Ambil gambar yang lebih jelas; data tidak diisi otomatis dengan contoh.')
            if q['blur'] < self.repository.settings()['blur_min'] or not 35 < q['brightness'] < 235:
                raise CaptureError('Gambar KTP terlalu buram, gelap, atau silau. Ambil ulang foto.')
            return result

    def run(self, session, selfie, holding, frames, manifest):
        started = time.perf_counter()
        checks = []
        identity = session.document_result['fields']
        rules = self.repository.settings()
        scores = {}
        status, reason = 'pass', 'Seluruh pemeriksaan lokal terpenuhi. Pengecekan identitas resmi Dukcapil belum dilakukan.'

        def add(name, passed, detail, mode='real'):
            checks.append({'name': name, 'status': 'passed' if passed else 'failed', 'detail': detail, 'mode': mode})

        try:
            with self.lock:
                self.load()
                doc = session.document
                ref_face = self.face.one(doc, allow_small_extra=True)
                self_face = self.face.one(selfie)
                holding_face = self.face.one(holding, allow_small_extra=True)
                add('OCR KTP', True, {'confidence': session.document_result['confidence'], 'engine': session.document_result['engine']})
                scores['ocr'] = session.document_result['confidence']
                q = quality(selfie)
                if q['blur'] < rules['blur_min'] or not 35 < q['brightness'] < 235:
                    raise CaptureError('Selfie terlalu buram, gelap, atau silau.')
                candidates = card_region(holding)
                held_ocr = None
                for _, crop, box in candidates[:4]:
                    candidate = self.ocr.read(crop)
                    if candidate['fields']['nik']:
                        held_ocr, card_box = candidate, box
                        break
                if held_ocr is None:
                    raise CaptureError('NIK pada KTP yang dipegang belum terbaca. Dekatkan KTP dan hindari menutup teks dengan jari.')
                same_card = held_ocr['fields']['nik'] == identity['nik']
                hand = self.landmarks.hand_near_card(holding, card_box)
                add('KTP dalam foto KYC', True, {'box': card_box, 'ocr_confidence': held_ocr['confidence']})
                add('Kesesuaian NIK kedua foto KTP', same_card, {'same_nik': same_card})
                add('Tangan dekat KTP', hand['passed'], hand)
                if not hand['passed']:
                    raise CaptureError('Tangan yang memegang KTP belum terdeteksi. Tampilkan tangan dan kartu secara utuh dalam foto.')
                face_score = self.face.compare(doc, ref_face, selfie, self_face)
                kyc_face_score = self.face.compare(selfie, self_face, holding, holding_face)
                scores['face_cosine'], scores['kyc_face_cosine'] = face_score, kyc_face_score
                add('Wajah KTP ↔ selfie', face_score >= rules['face_cosine'], {'cosine': face_score, 'threshold': rules['face_cosine'], 'model': 'SFace'})
                add('Wajah selfie ↔ foto KYC', kyc_face_score >= rules['face_cosine'], {'cosine': kyc_face_score, 'threshold': rules['face_cosine'], 'model': 'SFace'})
                live = self.landmarks.challenges(frames, manifest, session.challenges)
                add('Tantangan liveness', live['passed'], live)
                continuity = []
                pad_scores = [self.pad.score(selfie, self_face)]
                for challenge in session.challenges:
                    frame = next(f for f, m in zip(frames, manifest) if m['challenge'] == challenge)
                    frame_face = self.face.one(frame)
                    continuity.append(self.face.compare(selfie, self_face, frame, frame_face))
                    pad_scores.append(self.pad.score(frame, frame_face))
                same_face = min(continuity) >= rules['face_cosine']
                add('Kontinuitas wajah capture', same_face, {'cosines': continuity, 'threshold': rules['face_cosine'], 'scope': 'Pencocokan frame; bukan attestation kamera atau deteksi seluruh injection.'})
                pad_score = min(s['live_probability'] for s in pad_scores)
                scores['liveness'] = pad_score
                add('Anti-spoof / PAD', pad_score >= rules['pad_probability'], {'samples': pad_scores, 'minimum_live_probability': pad_score, 'threshold': rules['pad_probability']})
                _, aligned = self.face.feature(selfie, self_face)
                fake = self.deepfake.score(aligned)
                _, held_aligned = self.face.feature(holding, holding_face)
                held_fake = self.deepfake.score(held_aligned)
                fake_risk = max(fake['fake_probability'], held_fake['fake_probability'])
                scores['deepfake'] = fake_risk
                add('Risiko manipulasi gambar', fake_risk < rules['deepfake_risk'], {'selfie': fake, 'kyc': held_fake, 'maximum_fake_probability': fake_risk, 'threshold': rules['deepfake_risk']})
                if pad_score < rules['pad_probability'] or fake_risk >= rules['deepfake_risk']:
                    status, reason = 'attack', 'Model memberi sinyal risiko spoof/manipulasi. Perlu tinjauan keamanan; skor bukan bukti pasti serangan.'
                elif not live['passed']:
                    status, reason = 'capture', 'Gerakan tantangan belum terbaca. Ulangi capture dengan wajah terang dan gerakan lebih jelas.'
                elif not same_card or face_score < rules['face_cosine'] or kyc_face_score < rules['face_cosine'] or not same_face:
                    status, reason = 'manual', 'Kesesuaian dokumen atau wajah belum memenuhi ambang. Perlu pemeriksaan petugas.'
        except CaptureError as exc:
            status, reason = 'capture', str(exc)
            checks.append({'name': 'Kualitas capture', 'status': 'failed', 'detail': {'message': reason}, 'mode': 'real'})
        except Exception as exc:
            status = 'technical'
            reason = str(exc) if isinstance(exc, ModelUnavailable) else 'Pemrosesan model mengalami gangguan. Lihat log server dan coba ulang.'
            self.last_error = reason
            log.exception('Inference failed for session %s', session.id)
            checks.append({'name': 'Ketersediaan inference', 'status': 'unavailable', 'detail': {'message': reason}, 'mode': 'real'})
        dukcapil = self.dukcapil.check(identity)
        checks.append({'name': 'Dukcapil', 'status': 'not_verified', 'detail': dukcapil, 'mode': 'mock'})
        result = {'id': 'VRF-'+uuid.uuid4().hex[:10].upper(), 'session_id': session.id,
                  'name': identity.get('name') or 'Pemohon', 'nik_masked': '•••• •••• •••• '+identity['nik'][-4:],
                  'status': status, 'reason': reason, 'created': utcnow(), 'attempt': session.attempt,
                  'duration_ms': round((time.perf_counter()-started)*1000), 'scores': scores, 'checks': checks,
                  'rules': rules, 'identity_verified': False, 'dukcapil': dukcapil, 'inference': 'real'}
        self.repository.save_result(result)
        self.repository.audit('Verifikasi selesai', f'{status}: {reason}', result['id'])
        return result
