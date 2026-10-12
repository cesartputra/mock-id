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
            s.attempt += 1
            s.consumed = False
            s.nonce = secrets.token_urlsafe(32)
            s.liveness_result = None
            s.liveness_hashes = []
            s.liveness_nonce = None
            s.liveness_attempts = 0
            s.challenges = secrets.SystemRandom().sample(['blink', 'turn', 'smile'], 3)
            return s
