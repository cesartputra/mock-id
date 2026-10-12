"""Worker isolates tensor inference from identity storage and application decisions."""

import json
from pathlib import Path
from fastapi.testclient import TestClient
import numpy as np
import pytest
from app.worker import create_worker
from app.services.antispoof import PAD_MODEL, PAD_REVISION, face_tensor
from app.services.tier2_remote import RemoteAntiSpoofService


def test_worker_auth_input_contract_and_real_cpu_score(
    monkeypatch, real_models, face_image
):
    monkeypatch.setenv("MOCK_ID_WORKER_TOKEN", "w" * 40)
    with TestClient(create_worker()) as client:
        client.app.state.pad = real_models.pad
        assert client.get("/health").status_code == 401
        headers = {
            "Authorization": "Bearer " + "w" * 40,
            "Content-Type": "application/octet-stream",
        }
        assert (
            client.post("/v1/pad", headers=headers, content=b"bad").status_code == 422
        )
        assert (
            client.post(
                "/v1/pad",
                headers=headers,
                content=np.full((1, 3, 224, 224), np.nan, np.float32).tobytes(),
            ).status_code
            == 422
        )
        tensor = face_tensor(face_image, real_models.face.one(face_image))
        response = client.post("/v1/pad", headers=headers, content=tensor.tobytes())
        assert response.status_code == 200, response.text
        result = response.json()
        assert (
            result["model"] == PAD_MODEL and result["source_revision"] == PAD_REVISION
        )
        assert (
            result["live_probability"]
            == real_models.pad.score_tensor(tensor)["live_probability"]
        )
        assert result["runtime_details"]["selected"] == "cpu"
        assert not hasattr(client.app.state, "repository")


def test_remote_worker_requires_tls_and_contract(monkeypatch, face_image):
    with pytest.raises(ValueError):
        RemoteAntiSpoofService("http://remote.example", "w" * 40)
    remote = RemoteAntiSpoofService("http://127.0.0.1:4181", "w" * 40)

    def payload(sha):
        return {
            "model_sha256": sha,
            "model": PAD_MODEL,
            "source_revision": PAD_REVISION,
            "class_labels": ["live", "spoof"],
            "live_probability": 0.9,
            "spoof_probability": 0.1,
            "runtime": "ONNX / CUDA + CPU",
            "runtime_details": {
                "selected": "cuda",
                "loaded": True,
                "providers": ["CUDAExecutionProvider", "CPUExecutionProvider"],
            },
        }

    class Response:
        def __init__(self, data):
            self.data = data

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, *args):
            return json.dumps(self.data).encode()

    reply = {"data": payload("wrong-checksum")}

    class Opener:
        def open(self, request, timeout):
            assert "identity" not in request.header_items()
            assert len(request.data) == 1 * 3 * 224 * 224 * 4
            return Response(reply["data"])

    monkeypatch.setattr(
        "app.services.tier2_remote.urllib.request.build_opener", lambda *_args: Opener()
    )
    with pytest.raises(RuntimeError):
        remote.score(face_image, [20, 20, 100, 100])
    reply["data"] = payload(remote.digest)
    assert (
        remote.score(face_image, [20, 20, 100, 100])["runtime_details"]["remote"]
        is True
    )
    assert remote.model.status["selected"] == "cuda"
