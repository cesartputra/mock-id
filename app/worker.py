"""Standalone Tier 2 PAD worker. Has no repository, auth DB, SLIK or NIK input."""

import hashlib
import json
import os
import secrets
from contextlib import asynccontextmanager
import numpy as np
from fastapi import FastAPI, Request, HTTPException
from app.config import ROOT, WEIGHTS
from app.services.antispoof import AntiSpoofService, PAD_FILE
from app.services.inference_queue import InferenceQueue


def create_worker():
    @asynccontextmanager
    async def lifespan(app):
        token = os.getenv("MOCK_ID_WORKER_TOKEN")
        if not token or len(token) < 32:
            raise RuntimeError(
                "Worker membutuhkan MOCK_ID_WORKER_TOKEN minimal 32 karakter."
            )
        manifest = json.loads((ROOT / "model-manifest.json").read_text())
        expected = next(x for x in manifest if x["file"] == PAD_FILE)
        digest = hashlib.sha256()
        with (WEIGHTS / PAD_FILE).open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
        if digest.hexdigest() != expected["sha256"]:
            raise RuntimeError("Checksum model worker tidak sesuai.")
        app.state.digest = digest.hexdigest()
        app.state.token = token
        app.state.pad = AntiSpoofService()
        app.state.queue = InferenceQueue(capacity=4, timeout=20)
        try:
            yield
        finally:
            app.state.queue.close()

    app = FastAPI(
        title="mock-id Tier 2 PAD worker",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    def auth(request):
        if not secrets.compare_digest(
            request.headers.get("Authorization", ""), "Bearer " + app.state.token
        ):
            raise HTTPException(401, "Worker authorization required.")

    @app.get("/health")
    def health(request: Request):
        auth(request)
        return {"runtime": app.state.pad.model.status, "model_sha256": app.state.digest}

    @app.post("/v1/pad")
    async def pad(request: Request):
        auth(request)
        chunks = []
        length = 0
        expected = 1 * 3 * 224 * 224 * 4
        async for chunk in request.stream():
            length += len(chunk)
            if length > expected:
                raise HTTPException(413, "Tensor exceeds fixed contract.")
            chunks.append(chunk)
        if length != expected:
            raise HTTPException(422, "Expected float32 NCHW [1,3,224,224].")
        tensor = np.frombuffer(b"".join(chunks), dtype=np.float32).reshape(
            1, 3, 224, 224
        )
        if not np.isfinite(tensor).all() or np.abs(tensor).max() > 10:
            raise HTTPException(422, "Tensor values invalid.")
        try:
            result = await app.state.queue.run(app.state.pad.score_tensor, tensor)
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(503, "PAD inference unavailable.")
        return {**result, "model_sha256": app.state.digest}

    return app


app = create_worker()
