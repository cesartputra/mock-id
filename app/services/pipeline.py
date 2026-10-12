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
from app.services.card import HoldingCardService
from app.services.visibility import FaceVisibilityService

log = logging.getLogger(__name__)


class ModelUnavailable(RuntimeError):
    pass


MODEL_FILES = ['yunet.onnx', 'sface.onnx', 'minifasnet.onnx', 'deepfake.onnx', 'pipnet.onnx', 'palm.onnx', 'handpose.onnx', 'face_attrib.onnx']


class VerificationService:
    def __init__(self, repository):
        self.repository = repository
        self.lock = threading.RLock()
        self.ocr = OCRService()
        self.face = self.pad = self.deepfake = self.landmarks = self.visibility = None
        self.dukcapil = DukcapilService()
        self.last_error = None
        self.assets_verified = False

    def availability(self):
        files = {f: (WEIGHTS / f).is_file() for f in MODEL_FILES}
        files['ocr'] = len(list((WEIGHTS / 'ocr').glob('*.onnx'))) >= 3
        return {'ready': all(files.values()), 'files': files, 'loaded': all(v is not None for v in [self.face,self.pad,self.deepfake,self.landmarks,self.visibility]),
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
        if self.deepfake is None:
            face = self.face or FaceService()
            pad = self.pad or AntiSpoofService()
            deepfake = DeepfakeService()
            landmarks = self.landmarks or LandmarkService(face)
            visibility = self.visibility or FaceVisibilityService(face, landmarks)
            self.ocr.load()
            self.face, self.pad, self.deepfake, self.landmarks, self.visibility = face, pad, deepfake, landmarks, visibility

    def inspect_capture(self, image, holding=False):
        # Nonblocking lock: preview must not queue behind a full verification.
        if not self.lock.acquire(blocking=False):
            return {'ready':False,'warnings':[{'code':'inference_busy','message':'Model sedang memproses capture lain. Tunggu pemeriksaan kamera berikutnya.'}],'mode':'real'}
        try:
            if self.visibility is None:
                invalid=verify_assets()
                if invalid:
                    raise ModelUnavailable('Model hilang/berubah: '+', '.join(invalid)+'. Jalankan npm run setup.')
                face=self.face or FaceService()
                landmarks=self.landmarks or LandmarkService(face)
                visibility=FaceVisibilityService(face,landmarks)
                self.face,self.landmarks,self.visibility=face,landmarks,visibility
            result=self.visibility.inspect(image,holding)
            if result.get('face_box') is not None:
                self.pad=self.pad or AntiSpoofService()
                face=self.face.faces(image)[0]
                pad=self.pad.score(image,face)
                result['pad']=pad
                if pad['live_probability']<self.repository.settings()['pad_probability']:
                    result['warnings'].append({'code':'spoof_risk','message':'Model mendeteksi risiko foto/layar. Gunakan wajah langsung di depan kamera, bukan foto atau video pada perangkat.'})
                    result['ready']=False
            return result
        finally:
            self.lock.release()

    def evaluate_liveness(self, session, selfie, frames, manifest):
        with self.lock:
            self.load()
            rules=self.repository.settings()
            visible=self.visibility.inspect(selfie)
            if not visible['ready']:
                return {'passed':False,'reason':visible['warnings'][0]['message'],'visibility':visible,'mode':'real'}
            self_face=self.face.one(selfie)
            live=self.landmarks.challenges(frames,manifest,session.challenges)
            continuity=[]
            pad_samples=[self.pad.score(selfie,self_face)]
            for challenge in session.challenges:
                group=[f for f,m in zip(frames,manifest) if m['challenge']==challenge]
                frame=group[min(2,len(group)-1)]
                face=self.face.one(frame)
                continuity.append(self.face.compare(selfie,self_face,frame,face))
                pad_samples.append(self.pad.score(frame,face))
            minimum=min(s['live_probability'] for s in pad_samples)
            same_face=min(continuity)>=rules['face_cosine']
            passed=live['passed'] and same_face and minimum>=rules['pad_probability']
            reason='Gerakan dan anti-spoof terpenuhi.' if passed else ('Risiko foto/layar terdeteksi. Gunakan wajah langsung di kamera.' if minimum<rules['pad_probability'] else 'Gerakan wajah belum memenuhi tantangan. Foto statis atau gerakan kartu tidak menggantikan kedipan, senyum, dan putaran kepala.' if not live['passed'] else 'Wajah pada rekaman tidak konsisten. Rekam ulang dengan satu pemohon.')
            return {'passed':bool(passed),'reason':reason,'live':live,'pad_samples':pad_samples,
                    'pad_probability':minimum,'continuity':continuity,'rules':rules,'mode':'real'}

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
                proof=session.liveness_result
                if not proof or not proof.get('passed'):
                    raise CaptureError('Rekam dan lolos pemeriksaan liveness sebelum foto KTP.')
                add('Liveness saat rekaman',True,proof)
                scores['liveness']=proof['pad_probability']
                doc = session.document
                ref_face = self.face.one(doc, allow_small_extra=True)
                self_face = self.face.one(selfie)
                holding_face = self.face.one(holding, allow_small_extra=True)
                add('OCR KTP', True, {'confidence': session.document_result['confidence'], 'engine': session.document_result['engine']})
                scores['ocr'] = session.document_result['confidence']
                q = quality(selfie)
                if q['blur'] < rules['blur_min'] or not 35 < q['brightness'] < 235:
                    raise CaptureError('Selfie terlalu buram, gelap, atau silau.')
                for label,image in [('Selfie',selfie),('Foto KYC',holding)]:
                    visible=self.visibility.inspect(image,holding=label=='Foto KYC')
                    add(label+' tanpa penutup wajah',visible['ready'],visible)
                    if not visible['ready']:
                        raise CaptureError(label+': '+visible['warnings'][0]['message'])
                card=HoldingCardService(self.ocr).read(holding,reference=doc,expected_nik=identity['nik'])
                held_ocr,card_box=card['reading'],card['box']
                same_card = held_ocr['fields']['nik'] == identity['nik']
                hand = self.landmarks.hand_near_card(holding, card_box)
                add('KTP dalam foto KYC', True, {'box': card_box, 'ocr_confidence': held_ocr['confidence'], 'method': card['method']})
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
