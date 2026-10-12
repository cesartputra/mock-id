"""AEAD local sealing and separate keyed identity index; no key in Git."""

import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class SecretBox:
    def __init__(self, directory):
        configured = os.getenv("MOCK_ID_ENCRYPTION_KEY")
        if configured:
            self.key = base64.b64decode(configured, validate=True)
        elif os.getenv("MOCK_ID_MODE", "demo") == "production":
            raise RuntimeError(
                "Production membutuhkan MOCK_ID_ENCRYPTION_KEY dari secret manager."
            )
        else:
            path = Path(directory) / ".local.key"
            try:
                descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                pass
            else:
                with os.fdopen(descriptor, "wb") as target:
                    target.write(os.urandom(32))
            self.key = path.read_bytes()
        if len(self.key) != 32:
            raise ValueError("Kunci enkripsi harus 32 byte base64.")
        self.aead = AESGCM(self.key)
        self.index_key = hmac.new(
            self.key, b"mock-id:subject-index:v1", hashlib.sha256
        ).digest()

    def subject(self, nik):
        return hmac.new(self.index_key, nik.encode(), hashlib.sha256).hexdigest()

    def seal(self, content, binding):
        nonce = os.urandom(12)
        return base64.b64encode(
            nonce + self.aead.encrypt(nonce, content, binding.encode())
        ).decode()

    def open(self, ciphertext, binding):
        sealed = base64.b64decode(ciphertext, validate=True)
        return self.aead.decrypt(sealed[:12], sealed[12:], binding.encode())

    def seal_json(self, value, binding):
        return self.seal(
            json.dumps(value, ensure_ascii=False, allow_nan=False).encode(), binding
        )

    def open_json(self, ciphertext, binding):
        return json.loads(self.open(ciphertext, binding))
