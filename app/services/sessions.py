import secrets
import threading
import time

from fastapi import HTTPException
from app.config import MAX_ATTEMPTS, SESSION_TTL
from app.model.entities import CaptureSession


class SessionService:
    def __init__(self):
        self.items = {}
        self.lock = threading.RLock()

    def purge(self):
        with self.lock:
            cutoff = time.time() - SESSION_TTL
            self.items = {k: v for k, v in self.items.items() if v.created > cutoff or v.processing or v.liveness_processing}

    def create(self):
        with self.lock:
            self.purge()
            if len(self.items) >= 20:
                raise HTTPException(429, 'Terlalu banyak sesi aktif. Tunggu sesi kedaluwarsa.')
            session = CaptureSession()
            self.items[session.id] = session
            return session

    def get(self, session_id):
        with self.lock:
            session = self.items.get(session_id)
            if not session or time.time() - session.created > SESSION_TTL:
                if session and not session.processing and not session.liveness_processing:
                    self.items.pop(session_id, None)
                raise HTTPException(410, 'Sesi kedaluwarsa atau server dimulai ulang. Buat sesi baru.')
            return session

    def consume(self, session_id, nonce):
        with self.lock:
            s = self.get(session_id)
            if not secrets.compare_digest(s.nonce, nonce) or s.consumed or s.processing or s.liveness_processing:
                raise HTTPException(409, 'Nonce tidak valid atau sudah digunakan.')
            if s.document is None:
                raise HTTPException(422, 'Unggah dan baca KTP sebelum verifikasi.')
            s.consumed = True
            s.processing = True
            return s

    def retry(self, session_id):
        with self.lock:
            s = self.get(session_id)
            if s.processing or s.liveness_processing or not s.last_result or s.last_result['status'] not in ['capture', 'technical']:
                raise HTTPException(409, 'Sesi ini belum dapat dicoba ulang.')
            if s.attempt >= MAX_ATTEMPTS:
                raise HTTPException(429, 'Batas percobaan tercapai. Buat sesi baru.')
            return self.reset(session_id, self.retry_plan(s)['stage'], s.nonce)

    def retry_plan(self, s):
        if s.last_result and s.last_result.get('retry'):
            return dict(s.last_result['retry'])
        # Older persisted results have no stage metadata. Prefer the unfinished
        # held photo when document and server liveness proof are still present.
        stage = ('verify' if s.last_result and s.last_result['status'] == 'technical'
                 else 'holding' if s.document is not None and s.liveness_result and s.liveness_result.get('passed')
                 else 'liveness' if s.document is not None else 'document')
        return {'stage': stage, 'label': {'verify': 'Jalankan pemeriksaan ulang',
                'holding': 'Ulangi foto bersama KTP', 'liveness': 'Ulangi liveness',
                'document': 'Ulangi foto KTP'}[stage],
                'reason': (s.last_result or {}).get('reason', 'Perbaiki tahap yang belum terpenuhi.')}

    def clear_liveness(self, s):
        s.liveness_result = None
        s.liveness_hashes = []
        s.liveness_nonce = None
        s.liveness_manifest = None
        s.liveness_selfie = None
        s.liveness_proof = None
        s.stream_state = None
        s.liveness_started = 0.0
        s.challenges = secrets.SystemRandom().sample(['blink', 'turn', 'smile'], 3)

    def check_revision(self, s, request):
        revision = request.headers.get('X-Capture-Revision')
        # Legacy batch clients without this header remain supported. Updated
        # clients bind every asynchronous request to a capture generation.
        if revision is not None and revision != str(s.revision):
            raise HTTPException(409, 'Capture lama sudah dibersihkan. Gunakan pengambilan terbaru.')

    def reset(self, session_id, stage, nonce):
        with self.lock:
            s = self.get(session_id)
            if stage not in ['document', 'liveness', 'holding', 'verify']:
                raise HTTPException(422, 'Tahap capture tidak valid.')
            if not secrets.compare_digest(s.nonce, nonce):
                raise HTTPException(409, 'Token reset sudah berubah. Gunakan sesi terbaru.')
            if s.processing or s.liveness_processing:
                raise HTTPException(409, 'Pemeriksaan masih berjalan. Tunggu sebelum mengambil ulang.')
            if s.consumed:
                if s.attempt >= MAX_ATTEMPTS:
                    raise HTTPException(429, 'Batas percobaan tercapai. Buat sesi baru.')
                s.attempt += 1
                s.liveness_attempts = 0
            s.revision += 1
            s.consumed = False
            s.nonce = secrets.token_urlsafe(32)
            s.last_preview = 0.0
            s.last_result = None
            if stage == 'liveness' or not (s.liveness_result and s.liveness_result.get('passed')):
                self.clear_liveness(s)
            if stage == 'document':
                s.document = None
                s.document_result = None
            return s
