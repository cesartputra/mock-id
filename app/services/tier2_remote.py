"""Trusted server-to-worker PAD transport: fixed tensor, no identity or nonce."""

import json
import math
import os
import urllib.error
import urllib.request
from types import SimpleNamespace
from urllib.parse import urlparse
from app.config import ROOT
from app.services.antispoof import face_tensor, PAD_FILE, PAD_MODEL, PAD_REVISION


class RemoteAntiSpoofService:
    def __init__(self, url, token):
        parsed = urlparse(url)
        local = parsed.hostname in ["localhost", "127.0.0.1"]
        if parsed.scheme != "https" and not (
            local
            and parsed.scheme == "http"
            and os.getenv("MOCK_ID_MODE", "demo") == "demo"
        ):
            raise ValueError("Worker eksternal membutuhkan TLS.")
        if (
            parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or not token
            or len(token) < 32
        ):
            raise ValueError(
                "Konfigurasi worker tidak valid; token minimal 32 karakter diperlukan."
            )
        self.url, self.token = url.rstrip("/"), token
        self.model = SimpleNamespace(
            status={
                "requested": "remote",
                "selected": "remote",
                "runtime": "Remote PAD · menunggu respons worker",
                "loaded": False,
                "providers": [],
                "fallback_reason": None,
            }
        )
        manifest = json.loads((ROOT / "model-manifest.json").read_text())
        self.digest = next(m["sha256"] for m in manifest if m["file"] == PAD_FILE)

    def score(self, image, face):
        tensor = face_tensor(image, face)
        request = urllib.request.Request(
            self.url + "/v1/pad",
            data=tensor.tobytes(),
            headers={
                "Authorization": "Bearer " + self.token,
                "Content-Type": "application/octet-stream",
            },
            method="POST",
        )

        # No automatic credential-bearing redirects to another host.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None

        with urllib.request.build_opener(NoRedirect).open(
            request, timeout=20
        ) as response:
            raw = response.read(64 * 1024 + 1)
        if len(raw) > 64 * 1024:
            raise RuntimeError("Respons worker terlalu besar.")
        result = json.loads(raw)
        if (
            result.get("model_sha256") != self.digest
            or result.get("model") != PAD_MODEL
            or result.get("source_revision") != PAD_REVISION
            or result.get("class_labels") != ["live", "spoof"]
        ):
            raise RuntimeError("Kontrak model worker tidak sesuai.")
        values = [result.get("live_probability"), result.get("spoof_probability")]
        if (
            any(
                type(v) not in [float, int] or not math.isfinite(v) or not 0 <= v <= 1
                for v in values
            )
            or abs(sum(values) - 1) > 0.00001
        ):
            raise RuntimeError("Probabilitas worker tidak valid.")
        details = result.get("runtime_details", {})
        if (
            details.get("selected") not in ["cpu", "cuda", "coreml"]
            or not details.get("loaded")
            or not isinstance(details.get("providers"), list)
        ):
            raise RuntimeError("Metadata runtime worker tidak sesuai.")
        self.model.status = {**details, "remote": True, "runtime": result["runtime"]}
        return {**result, "runtime_details": dict(self.model.status)}
