from dataclasses import dataclass, field
import secrets
import time
import uuid

from app.config import MAX_ATTEMPTS, SESSION_TTL


@dataclass
class CaptureSession:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    nonce: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    created: float = field(default_factory=time.time)
    attempt: int = 1
    consumed: bool = False
    processing: bool = False
    revision: int = 0
    stream_state: object | None = None
    liveness_proof: str | None = None
    last_preview: float = 0.0
    liveness_nonce: str | None = None
    liveness_started: float = 0.0
    liveness_attempts: int = 0
    liveness_processing: bool = False
    liveness_result: dict | None = None
    liveness_hashes: list = field(default_factory=list)
    liveness_manifest: str | None = None
    liveness_selfie: str | None = None
    document: object | None = None
    document_result: dict | None = None
    last_result: dict | None = None
    challenges: list = field(default_factory=lambda: secrets.SystemRandom().sample(['blink', 'turn', 'smile'], 3))

    def public(self):
        return {'id': self.id, 'nonce': self.nonce, 'attempt': self.attempt,
                'max_attempts': MAX_ATTEMPTS, 'expires_at': self.created + SESSION_TTL,
                'challenges': self.challenges, 'revision': self.revision}
