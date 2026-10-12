import hashlib
import hmac
import secrets
import os
import logging
import threading
import time
import uuid
from pathlib import Path

from app.config import WEIGHTS
from app.model.repository import utcnow
from app.services.imaging import CaptureError, card_region, quality
from app.services.ocr import OCRService
from app.services.face import FaceService, FACE_MODEL_ID, FACE_MODEL
from app.services.antispoof import AntiSpoofService, create_pad_service, PAD_FILE, PAD_MODEL
from app.services.deepfake import DeepfakeService
from app.services.landmarks import LandmarkService
from app.services.dukcapil import DukcapilService
from app.services.assets import verify_assets
from app.services.card import HoldingCardService
from app.services.visibility import FaceVisibilityService
from app.services.inference import pad_policy
from app.services.score_policy import ScoreCalibrator
from app.services.document import read_document, capture_warning

log = logging.getLogger(__name__)


class ModelUnavailable(RuntimeError):
    pass


MODEL_FILES = ['yunet.onnx', 'arcface_r50.onnx', PAD_FILE, 'deepfake.onnx', 'pipnet.onnx', 'palm.onnx', 'handpose.onnx', 'face_attrib.onnx']


class VerificationService:
    def __init__(self, repository):
        self.repository = repository
        self.lock = threading.RLock()
        self.ocr = OCRService()
        self.face = self.pad = self.deepfake = self.landmarks = self.visibility = None
        self.dukcapil = DukcapilService()
        self.last_error = None
        self.assets_verified = False
        self.subject_key = secrets.token_bytes(32)
        # An uncalibrated PAD signal in the local demo requires human review,
        # never automatic approval. Production keeps strict capture rejection.
        self.pad_review_enabled = (
            os.getenv("MOCK_ID_MODE", "demo") == "demo"
            and not ScoreCalibrator().calibrated
        )

    def availability(self):
        files = {f: (WEIGHTS / f).is_file() for f in MODEL_FILES}
        files['ocr'] = len(list((WEIGHTS / 'ocr').glob('*.onnx'))) >= 3
        return {'ready': all(files.values()), 'files': files, 'loaded': all(v is not None for v in [self.face,self.pad,self.deepfake,self.landmarks,self.visibility]),
                'last_error': self.last_error, 'dukcapil': 'mock' if os.getenv('MOCK_ID_MODE','demo')=='demo' else 'official_not_configured', 'inference': 'real', 'pad_model': PAD_MODEL, 'face_model': FACE_MODEL, 'face_model_id': FACE_MODEL_ID,
                'pad_runtime': dict(self.pad.model.status) if self.pad else ({'requested':'remote','selected':'remote','runtime':'Remote PAD · menunggu respons worker','fallback_reason':None,'loaded':False,'providers':[]} if os.getenv('MOCK_ID_PAD_WORKER_URL') else {**pad_policy(), 'loaded': False, 'providers': []}),
                'other_runtime': 'CPU (OCR, wajah, landmark, tangan, penutup wajah, diagnostik)'}

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
            pad = self.pad or create_pad_service()
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
            if result.get("face_box") is not None:
                self.pad=self.pad or create_pad_service()
                face=self.face.faces(image)[0]
                pad=self.pad.score(image,face)
                result['pad']=pad
                if (
                    pad["live_probability"]
                    < self.repository.settings()["pad_probability"]
                ):
                    if self.pad_review_enabled:
                        result["pad_review_required"] = True
                        result["warnings"].append(
                            {
                                "code": "pad_review",
                                "message": "Wajah terdeteksi, tetapi penilaian anti-spoof belum meyakinkan. Ikuti tantangan gerakan; hasil memerlukan pemeriksaan manual sebelum disetujui.",
                            }
                        )
                    else:
                        result["warnings"].append(
                            {
                                "code": "spoof_risk",
                                "message": "Pemeriksaan anti-spoof belum memenuhi ambang. Ini bukan bukti pasti penggunaan foto atau layar.",
                            }
                        )
                        result["ready"] = False
            return result
        finally:
            self.lock.release()

    def inspect_auto_capture(self, image, context, document=None, identity=None):
        # Serial inference with backpressure. A clean face alone must never
        # trigger a held-card capture: its NIK, hand and face match are required.
        if not self.lock.acquire(blocking=False):
            return {'ready': False, 'complete': False, 'context': context,
                    'warnings': [{'code': 'inference_busy', 'message': 'Pemeriksaan sedang berjalan. Tahan posisi sebentar.'}], 'mode': 'real'}
        try:
            def blocked(code, message, feedback=None):
                return {**(feedback or {}), 'ready': False, 'complete': False,
                        'context': context, 'warnings': [{'code': code, 'message': message}], 'mode': 'real'}
            if context == 'document':
                try:
                    reading = self.document(image)
                except CaptureError as exc:
                    return blocked('document_unreadable', str(exc))
                self.face = self.face or FaceService()
                try:
                    face = self.face.one(image, allow_small_extra=True)
                except CaptureError:
                    return blocked('portrait_missing', 'Potret wajah pada KTP belum terdeteksi. Dekatkan kartu dan tampilkan seluruh potret dengan jelas.')
                return {'ready': True, 'complete': False, 'context': context,
                        '_document_reading':reading,
                        'warnings': [], 'nik_readable': True,
                        'subject_key': hmac.new(self.subject_key, reading['fields']['nik'].encode(), hashlib.sha256).hexdigest(),
                        'ocr_confidence': reading['confidence'], 'face_box': [round(float(v)) for v in face[:4]], 'mode': 'real'}
            feedback = self.inspect_capture(image, holding=True)
            if not feedback['ready']:
                return {**feedback, 'complete': False, 'context': context}
            try:
                card = HoldingCardService(self.ocr).read(image, reference=document, expected_nik=identity['nik'])
                hand = self.landmarks.hand_near_card(image, card['box'])
                if card['reading']['fields']['nik'] != identity['nik']:
                    return blocked('card_mismatch', 'Gunakan KTP yang sama dengan foto KTP sebelumnya.', feedback)
                if not hand['passed']:
                    return blocked('hand_missing', 'Tangan yang memegang KTP belum terlihat. Tampilkan tangan dan kartu secara utuh.', feedback)
                ref_face = self.face.one(document, allow_small_extra=True)
                held_face = self.face.one(image, allow_small_extra=True)
                cosine = self.face.compare(document, ref_face, image, held_face)
                if cosine < self.repository.settings()['face_cosine']:
                    return blocked('face_mismatch', 'Wajah belum cocok dengan foto pada KTP. Tatap kamera dengan wajah terang dan tidak tertutup.', feedback)
                return {**feedback, 'complete': True, 'context': context,
                        'nik_readable': True, 'nik_matches': True, 'hand_detected': True,
                        'card_box': card['box'], 'face_cosine': cosine,
                        'subject_key': hmac.new(self.subject_key, identity['nik'].encode(), hashlib.sha256).hexdigest()}
            except CaptureError as exc:
                return blocked('holding_unreadable', str(exc), feedback)
        finally:
            self.lock.release()

    def inspect_liveness_frame(self, capture, image, digest, seq):
        with self.lock:
            feedback = self.inspect_capture(image)
            capture.rules = self.repository.settings()
            capture.pad_review_enabled = self.pad_review_enabled
            if not feedback['ready']:
                codes = {w['code'] for w in feedback['warnings']}
                if codes and codes <= {'face_missing', 'inference_busy'}:
                    capture.pause_detection()
                else:
                    capture.resume_detection()
                    capture.gestures.reset_action()
                spoof = any(w['code'] == 'spoof_risk' for w in feedback['warnings'])
                capture.spoof_strikes = capture.spoof_strikes+1 if spoof else 0
                result = capture.result(feedback)
                if capture.spoof_strikes >= 2:
                    result.update(done=True, passed=False, reason='Risiko foto/layar terdeteksi. Rekam ulang dengan wajah langsung.')
                return result
            capture.spoof_strikes = 0
            # A prolonged gap must establish fresh neutral evidence.
            if capture.detection_missing_since is not None and time.monotonic() - capture.detection_missing_since > 1.0:
                capture.gestures.reset_action()
            capture.resume_detection()
            face = self.face.one(image)
            metrics = self.landmarks.metrics(image)
            if capture.reference_image is None:
                if metrics['blink'] < .22 or abs(metrics['yaw']) >= .10:
                    return capture.result(feedback, metrics)
                capture.reference_image = image
                capture.reference_face = face
                capture.selfie_hash = digest
                capture.selfie_seq = seq
            cosine = self.face.compare(capture.reference_image, capture.reference_face, image, face)
            if cosine < capture.rules['face_cosine']:
                result = capture.result(feedback, metrics)
                result.update(done=True, passed=False, reason='Wajah pada rekaman berubah atau tidak konsisten. Rekam ulang dengan satu pemohon.')
                return result
            capture.cosine_min = min(capture.cosine_min, cosine)
            capture.pad_min = min(capture.pad_min, feedback['pad']['live_probability'])
            before = len(capture.gestures.completed)
            capture.gestures.update(metrics)
            if len(capture.gestures.completed) > before:
                capture.evidence_images.append(image.copy())
            return capture.result(feedback, metrics)

    def evaluate_liveness(self, session, selfie, frames, manifest):
        with self.lock:
            self.load()
            rules = self.repository.settings()
            visible=self.visibility.inspect(selfie)
            if not visible['ready']:
                return {'passed':False,'reason':visible['warnings'][0]['message'],'visibility':visible,'mode':'real'}
            self_face = self.face.one(selfie)
            live = self.landmarks.challenges(frames, manifest, session.challenges)
            continuity = []
            pad_samples=[self.pad.score(selfie,self_face)]
            for challenge in session.challenges:
                group=[f for f,m in zip(frames,manifest) if m['challenge']==challenge]
                frame=group[min(2,len(group)-1)]
                face=self.face.one(frame)
                continuity.append(self.face.compare(selfie,self_face,frame,face))
                pad_samples.append(self.pad.score(frame,face))
            minimum=min(s['live_probability'] for s in pad_samples)
            same_face = min(continuity) >= rules["face_cosine"]
            passed=live['passed'] and same_face and minimum>=rules['pad_probability']
            review_required = (
                self.pad_review_enabled and minimum < rules["pad_probability"]
            )
            if review_required:
                passed = live["passed"] and same_face
            reason='Gerakan dan anti-spoof terpenuhi.' if passed else ('Risiko foto/layar terdeteksi. Gunakan wajah langsung di kamera.' if minimum<rules['pad_probability'] else 'Gerakan wajah belum memenuhi tantangan. Foto statis atau gerakan kartu tidak menggantikan kedipan, senyum, dan putaran kepala.' if not live['passed'] else 'Wajah pada rekaman tidak konsisten. Rekam ulang dengan satu pemohon.')
            if passed and review_required:
                reason = "Gerakan terbaca. Penilaian PAD memerlukan pemeriksaan manual; KYC belum disetujui."
            return {
                "passed": bool(passed),
                "reason": reason,
                "live": live,
                "pad_samples": pad_samples,
                "pad_probability": minimum,
                "pad_review_required": review_required,
                "pad_passed": minimum >= rules["pad_probability"],
                "continuity": continuity,
                "rules": rules,
                "mode": "real",
            }

    def document(self, image):
        with self.lock:
            if not self.availability()['files']['ocr']:
                raise ModelUnavailable('Model OCR belum diunduh. Jalankan python scripts/setup_models.py.')
            if not self.assets_verified:
                invalid = verify_assets()
                if invalid:
                    raise ModelUnavailable('Model hilang/berubah: '+', '.join(invalid))
                self.assets_verified = True
            result = read_document(image, self.ocr)
            if not result['fields']['nik']:
                raise CaptureError('NIK 16 digit belum terbaca dari KTP. Ambil gambar yang lebih jelas; data tidak diisi otomatis dengan contoh.')
            warning = capture_warning(result)
            if warning:
                raise CaptureError(warning[1])
            return result

    def run(self, session, selfie, holding, frames, manifest):
        started = time.perf_counter()
        checks = []
        identity = session.document_result['fields']
        rules = self.repository.settings()
        scores = {}
        stage = "verify"
        retry = None
        status, reason = 'pass', 'Seluruh kontrol KYC utama terpenuhi. Pengecekan identitas resmi Dukcapil belum dilakukan.'

        def add(name, passed, detail, mode='real'):
            checks.append({'name': name, 'status': 'passed' if passed else 'failed', 'detail': detail, 'mode': mode, 'stage': stage})

        try:
            with self.lock:
                self.load()
                stage = "liveness"
                proof=session.liveness_result
                if not proof or not proof.get('passed'):
                    raise CaptureError('Rekam dan lolos pemeriksaan liveness sebelum foto KTP.')
                add('Liveness saat rekaman',True,proof)
                scores['liveness']=proof['pad_probability']
                doc = session.document
                stage = "document"
                ref_face = self.face.one(doc, allow_small_extra=True)
                stage = "liveness"
                self_face = self.face.one(selfie)
                stage = "holding"
                holding_face = self.face.one(holding, allow_small_extra=True)
                stage = "document"
                add('OCR KTP', True, {'confidence': session.document_result['confidence'], 'engine': session.document_result['engine']})
                scores['ocr'] = session.document_result['confidence']
                stage = "liveness"
                q = quality(selfie)
                if q['blur'] < rules['blur_min'] or not 35 < q['brightness'] < 235:
                    raise CaptureError('Selfie terlalu buram, gelap, atau silau.')
                for label,image in [('Selfie',selfie),('Foto KYC',holding)]:
                    stage = 'liveness' if label == 'Selfie' else 'holding'
                    visible=self.visibility.inspect(image,holding=label=='Foto KYC')
                    add(label+' tanpa penutup wajah',visible['ready'],visible)
                    if not visible['ready']:
                        raise CaptureError(label+': '+visible['warnings'][0]['message'])
                face_score = self.face.compare(doc, ref_face, selfie, self_face)
                kyc_face_score = self.face.compare(selfie, self_face, holding, holding_face)
                scores['face_cosine'], scores['kyc_face_cosine'] = face_score, kyc_face_score
                add('Wajah KTP ↔ selfie', face_score >= rules['face_cosine'], {'cosine': face_score, 'threshold': rules['face_cosine'], 'model': FACE_MODEL, 'model_id': FACE_MODEL_ID})
                add('Wajah selfie ↔ foto KYC', kyc_face_score >= rules['face_cosine'], {'cosine': kyc_face_score, 'threshold': rules['face_cosine'], 'model': FACE_MODEL, 'model_id': FACE_MODEL_ID})
                stage = "holding"
                card=HoldingCardService(self.ocr).read(holding,reference=doc,expected_nik=identity['nik'])
                held_ocr,card_box=card['reading'],card['box']
                same_card = held_ocr['fields']['nik'] == identity['nik']
                hand = self.landmarks.hand_near_card(holding, card_box)
                add('KTP dalam foto KYC', True, {'box': card_box, 'ocr_confidence': held_ocr['confidence'], 'method': card['method']})
                add('Kesesuaian NIK kedua foto KTP', same_card, {'same_nik': same_card})
                add('Tangan dekat KTP', hand['passed'], hand)
                if not hand['passed']:
                    raise CaptureError('Tangan yang memegang KTP belum terdeteksi. Tampilkan tangan dan kartu secara utuh dalam foto.')
                stage = "liveness"
                if proof.get("stream"):
                    live = proof['live']
                    continuity = proof['continuity']
                    pad_scores = [
                        self.pad.score(selfie, self_face),
                        self.pad.score(holding, holding_face),
                    ]
                    pad_score = min(
                        proof["pad_probability"],
                        *(s["live_probability"] for s in pad_scores),
                    )
                else:
                    live = self.landmarks.challenges(
                        frames, manifest, session.challenges
                    )
                    continuity = []
                    pad_scores = [
                        self.pad.score(selfie, self_face),
                        self.pad.score(holding, holding_face),
                    ]
                    for challenge in session.challenges:
                        frame = next(f for f, m in zip(frames, manifest) if m['challenge'] == challenge)
                        frame_face = self.face.one(frame)
                        continuity.append(self.face.compare(selfie, self_face, frame, frame_face))
                        pad_scores.append(self.pad.score(frame, frame_face))
                    pad_score = min(s['live_probability'] for s in pad_scores)
                add('Tantangan liveness', live['passed'], live)
                same_face = min(continuity) >= rules["face_cosine"]
                add('Kontinuitas wajah capture', same_face, {'cosines': continuity, 'threshold': rules['face_cosine'], 'scope': 'Pencocokan frame; bukan attestation kamera atau deteksi seluruh injection.'})
                scores['liveness'] = pad_score
                add('Anti-spoof / PAD', pad_score >= rules['pad_probability'], {'samples': pad_scores, 'minimum_live_probability': pad_score, 'threshold': rules['pad_probability']})
                stage = "verify"
                # This generic AI-image classifier is not calibrated for KYC
                # face crops. Keep its real output for diagnostics, but never
                # let it declare an attack or invalidate otherwise valid KYC.
                diagnostic = {'name': 'Classifier gambar AI (diagnostik)', 'mode': 'real',
                              'effect': 'advisory', 'stage': stage, 'calibrated': False}
                try:
                    _, aligned = self.face.feature(selfie, self_face)
                    fake = self.deepfake.score(aligned)
                    _, held_aligned = self.face.feature(holding, holding_face)
                    held_fake = self.deepfake.score(held_aligned)
                    fake_risk = max(fake['fake_probability'], held_fake['fake_probability'])
                    scores['deepfake'] = fake_risk
                    diagnostic.update(status='informational', detail={
                        'selfie': fake, 'kyc': held_fake, 'maximum_fake_probability': fake_risk,
                        'reference_threshold': rules['deepfake_risk'],
                        'message': 'Classifier belum dikalibrasi untuk capture KYC. Skor disimpan sebagai diagnostik dan tidak menentukan kelulusan.'})
                except Exception:
                    log.error('Image diagnostic unavailable for session %s', session.id)
                    diagnostic.update(status='unavailable', detail={
                        'message': 'Analisis gambar tambahan tidak tersedia; keputusan memakai kontrol KYC utama.'})
                checks.append(diagnostic)
                if not live["passed"]:
                    status, reason = 'capture', 'Gerakan tantangan belum terbaca. Ulangi capture dengan wajah terang dan gerakan lebih jelas.'
                    stage = "liveness"
                    retry = {'stage': stage, 'label': 'Ulangi liveness', 'reason': reason}
                elif pad_score < rules["pad_probability"]:
                    if self.pad_review_enabled:
                        status, reason = (
                            "manual",
                            "Penilaian anti-spoof belum meyakinkan. Model belum dikalibrasi untuk webcam lokal; diperlukan pemeriksaan manual sebelum KYC disetujui.",
                        )
                    else:
                        status, reason = (
                            "attack",
                            "Model anti-spoof / PAD memberi sinyal risiko foto atau layar. Perlu tinjauan keamanan; skor bukan bukti pasti serangan.",
                        )
                elif not same_card or face_score < rules['face_cosine'] or kyc_face_score < rules['face_cosine'] or not same_face:
                    status, reason = 'manual', 'Kesesuaian dokumen atau wajah belum memenuhi ambang. Perlu pemeriksaan petugas.'
        except CaptureError as exc:
            status, reason = 'capture', str(exc)
            label = {'document': 'Kualitas foto KTP', 'liveness': 'Kualitas selfie / liveness', 'holding': 'Kualitas foto bersama KTP'}.get(stage, 'Kualitas capture')
            retry = {'stage': stage, 'label': {'document': 'Ulangi foto KTP', 'liveness': 'Ulangi liveness', 'holding': 'Ulangi foto bersama KTP'}.get(stage, 'Periksa kembali'), 'reason': reason}
            checks.append({'name': label, 'status': 'failed', 'detail': {'message': reason}, 'mode': 'real', 'stage': stage})
        except Exception as exc:
            status = 'technical'
            reason = str(exc) if isinstance(exc, ModelUnavailable) else 'Pemrosesan model mengalami gangguan. Lihat log server dan coba ulang.'
            retry = {'stage': 'verify', 'label': 'Jalankan pemeriksaan ulang', 'reason': reason}
            self.last_error = reason
            log.error('Inference failed for session %s; type %s', session.id, type(exc).__name__)
            checks.append({'name': 'Ketersediaan inference', 'status': 'unavailable', 'detail': {'message': reason}, 'mode': 'real'})
        dukcapil = self.dukcapil.check(identity)
        identity_demo_passed = bool(
            dukcapil['mode'] == 'mock' and dukcapil.get('simulated') is True
            and dukcapil.get('status') == 'passed'
        )
        checks.append({'name': 'Dukcapil', 'status': 'passed' if dukcapil['identity_verified'] or identity_demo_passed else 'not_verified', 'detail': dukcapil, 'mode': dukcapil['mode']})
        if status == 'pass' and identity_demo_passed:
            reason = 'Seluruh kontrol KYC utama terpenuhi. Dukcapil lolos simulasi (MOCK).'
        if not dukcapil.get('source_available',True):
            status,reason='technical',dukcapil['message']
            retry={'stage':'verify','label':'Tunggu adapter identitas berwenang','reason':reason}
        result = {'id': 'VRF-'+uuid.uuid4().hex[:10].upper(), 'session_id': session.id,
                  'name': identity.get('name') or 'Pemohon', 'nik_masked': '•••• •••• •••• '+identity['nik'][-4:],
                  'status': status, 'reason': reason, 'created': utcnow(), 'attempt': session.attempt,
                  'duration_ms': round((time.perf_counter()-started)*1000), 'scores': scores, 'checks': checks,
                  'rules': rules, 'retry': retry, 'identity_verified': bool(dukcapil['identity_verified']), 'dukcapil': dukcapil, 'inference': 'real',
                  'decision_policy': 'kyc-core-v1-ai-image-diagnostic'}
        result["pad_review_required"] = bool(
            self.pad_review_enabled
            and status == "manual"
            and scores.get("liveness", 1) < rules["pad_probability"]
        )
        result['identity_demo_passed'] = identity_demo_passed
        self.repository.save_result(result)
        self.repository.audit('Verifikasi selesai', f'{status}: {reason}', result['id'])
        return result
