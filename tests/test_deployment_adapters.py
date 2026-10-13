"""Deployment interfaces; external services are not contacted by default."""

import base64
import json
import os
import secrets
import sys
from types import SimpleNamespace
import pytest
from app.model.database import Connection
from app.services.evidence import S3PrivateStorage
from app.services.capture_registry import RedisCaptureRegistry


def test_postgres_parameter_and_schema_translation():
    queries = []
    raw = SimpleNamespace(execute=lambda sql, params: queries.append((sql, params)))
    connection = Connection(raw, "postgres")
    connection.execute("SELECT * FROM test WHERE id=?", ("id",))
    connection.executescript(
        "CREATE TABLE demo (id INTEGER PRIMARY KEY AUTOINCREMENT, expires REAL);"
    )
    assert queries[0] == ("SELECT * FROM test WHERE id=%s", ("id",))
    assert "BIGSERIAL PRIMARY KEY" in queries[1][0]
    assert (
        "DOUBLE PRECISION" in queries[1][0]
    )  # AEAD expiry must not lose precision in PostgreSQL.


def test_private_object_storage_enforces_public_access_block(monkeypatch):
    block = {"value": False}
    objects = {}

    class Client:
        def get_public_access_block(self, **kwargs):
            return {
                "PublicAccessBlockConfiguration": {
                    k: block["value"]
                    for k in [
                        "BlockPublicAcls",
                        "IgnorePublicAcls",
                        "BlockPublicPolicy",
                        "RestrictPublicBuckets",
                    ]
                }
            }

        def put_object(self, **kwargs):
            assert kwargs["ServerSideEncryption"] == "AES256"
            objects[kwargs["Key"]] = kwargs["Body"]

        def get_object(self, **kwargs):
            return {"Body": SimpleNamespace(read=lambda: objects[kwargs["Key"]])}

        def delete_object(self, **kwargs):
            objects.pop(kwargs["Key"])

    monkeypatch.setitem(
        sys.modules, "boto3", SimpleNamespace(client=lambda *_args, **_kwargs: Client())
    )
    with pytest.raises(ValueError):
        S3PrivateStorage("fixture")
    block["value"] = True
    storage = S3PrivateStorage("fixture", "https://private-storage.example")
    storage.put("opaque", "encrypted-fixture-only")
    assert storage.get("opaque") == "encrypted-fixture-only"
    storage.delete("opaque")
    assert not objects
    with pytest.raises(ValueError):
        S3PrivateStorage("fixture", "http://remote.example")


def test_redis_owner_registry_and_tls_rejects_hostname_prefix_trick(monkeypatch):
    values = {}

    class FakeRedis:
        @classmethod
        def from_url(cls, *_args, **_kwargs):
            return cls()

        def set(self, key, value, nx, ex):
            if key in values:
                return False
            values[key] = value
            assert nx and ex == 900
            return True

        def get(self, key):
            return values.get(key)

    monkeypatch.setitem(sys.modules, "redis", SimpleNamespace(Redis=FakeRedis))
    with pytest.raises(ValueError):
        RedisCaptureRegistry("redis://localhost.evil.example", "gateway")
    registry = RedisCaptureRegistry("rediss://trusted.example", "gateway-1")
    registry.register("session-fixture", 900)
    assert registry.owner("session-fixture") == "gateway-1"
    with pytest.raises(RuntimeError):
        registry.register("session-fixture", 900)


@pytest.mark.skipif(
    not os.getenv("MOCK_ID_POSTGRES_TEST_URL"),
    reason="PostgreSQL test server/DSN tidak tersedia; SQLite race diuji nyata.",
)
def test_native_postgres_migrations_auth_and_workflow(monkeypatch, tmp_path):
    psycopg = pytest.importorskip("psycopg")
    from urllib.parse import urlsplit, urlunsplit, quote
    from app.model.repository import Repository
    from app.services.auth import AuthService
    from app.services.workflow import WorkflowService
    from app.services.evidence import EvidenceStore

    url = os.environ["MOCK_ID_POSTGRES_TEST_URL"]
    schema = "mock_id_test_" + secrets.token_hex(6)
    with psycopg.connect(url, autocommit=True) as con:
        con.execute("CREATE SCHEMA " + schema)
    try:
        parsed = urlsplit(url)
        query = (
            parsed.query
            + ("&" if parsed.query else "")
            + "options="
            + quote("-csearch_path=" + schema)
        )
        monkeypatch.setenv(
            "MOCK_ID_DATABASE_URL",
            urlunsplit((parsed.scheme, parsed.netloc, parsed.path, query, "")),
        )
        monkeypatch.setenv(
            "MOCK_ID_ENCRYPTION_KEY", base64.b64encode(secrets.token_bytes(32)).decode()
        )
        repo = Repository(tmp_path)
        repo.migrate()
        repo.migrate()
        auth = AuthService(repo)
        owner = auth.create_user("pg-fixture-user", "fixture-password-123")
        token, _ = auth.login("pg-fixture-user", "fixture-password-123")
        assert auth.principal(token)["id"] == owner["id"]
        workflow = WorkflowService(repo, repo.box, EvidenceStore(repo, repo.box))
        application = workflow.create(owner)
        assert workflow.snapshot(application["id"], owner)["state"] == "VERIFYING"
    finally:
        with psycopg.connect(url, autocommit=True) as con:
            con.execute("DROP SCHEMA " + schema + " CASCADE")
