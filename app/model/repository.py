import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone

from app.config import DATA, DEFAULT_SETTINGS
from app.services.face import FACE_MODEL_ID
from app.model.database import Database
from app.services.secrets_store import SecretBox
from pathlib import Path


def utcnow():
    return datetime.now(timezone.utc).isoformat()


class Repository:
    def __init__(self, directory=DATA):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.box = SecretBox(directory)
        self.path = directory / "workspace.sqlite3"
        self.lock = threading.RLock()
        self.database = Database(self.path)
        self.transactions = threading.local()
        with self.connect(write=True) as con:
            con.executescript(
                """CREATE TABLE IF NOT EXISTS results (id TEXT PRIMARY KEY, created TEXT, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY AUTOINCREMENT, created TEXT, type TEXT, ref TEXT, detail TEXT);
            CREATE TABLE IF NOT EXISTS registrations (id TEXT PRIMARY KEY, created TEXT, verification_id TEXT UNIQUE, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL);"""
            )
            con.execute(
                "INSERT INTO settings VALUES (1, ?) ON CONFLICT(id) DO NOTHING",
                (json.dumps({**DEFAULT_SETTINGS, "face_model": FACE_MODEL_ID}),),
            )

            stored = json.loads(
                con.execute("SELECT payload FROM settings WHERE id=1").fetchone()[
                    "payload"
                ]
            )
            if stored.get("face_model") != FACE_MODEL_ID:
                # Old SFace threshold is not transferable to the new embedding space.
                stored.update(
                    face_model=FACE_MODEL_ID,
                    face_cosine=DEFAULT_SETTINGS["face_cosine"],
                )
                con.execute(
                    "UPDATE settings SET payload=? WHERE id=1", (json.dumps(stored),)
                )

    @contextmanager
    def connect(self, write=False):
        existing = getattr(self.transactions, "connection", None)
        if existing is not None:
            yield existing
            return
        with self.database.connect(write) as con:
            if write:
                self.transactions.connection = con
            try:
                yield con
            finally:
                if write:
                    del self.transactions.connection

    def migrate(self):
        legacy_resealed = False
        with self.connect(write=True) as con:
            con.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, applied TEXT NOT NULL)"
            )
            for path in sorted((Path(__file__).parent / "migrations").glob("*.sql")):
                if con.execute(
                    "SELECT version FROM schema_migrations WHERE version=?",
                    (path.stem,),
                ).fetchone():
                    continue
                con.executescript(path.read_text())
                con.execute(
                    "INSERT INTO schema_migrations VALUES (?,?) ON CONFLICT(version) DO NOTHING",
                    (path.stem, utcnow()),
                )
            check = self.box.subject("vault-key-check:v1")
            existing = con.execute(
                "SELECT key_check FROM vault_metadata WHERE id=1"
            ).fetchone()
            if existing and existing["key_check"] != check:
                raise RuntimeError(
                    "Kunci enkripsi tidak sesuai data. Pulihkan key dari backup; jangan mengganti key tanpa migrasi."
                )
            con.execute(
                "INSERT INTO vault_metadata VALUES (1,?) ON CONFLICT(id) DO NOTHING",
                (check,),
            )
            for table in ["results", "registrations", "applications"]:
                for row in con.execute("SELECT id,payload FROM " + table).fetchall():
                    value = json.loads(row["payload"])
                    if "__sealed__" not in value:
                        legacy_resealed = True
                        con.execute(
                            "UPDATE " + table + " SET payload=? WHERE id=?",
                            (self.encode(value, table + ":" + row["id"]), row["id"]),
                        )
            for row in con.execute(
                "SELECT owner_id,key,response FROM idempotency"
            ).fetchall():
                if "__sealed__" not in json.loads(row["response"]):
                    con.execute(
                        "UPDATE idempotency SET response=? WHERE owner_id=? AND key=?",
                        (
                            self.encode(
                                json.loads(row["response"]),
                                "idempotency:" + row["owner_id"] + ":" + row["key"],
                            ),
                            row["owner_id"],
                            row["key"],
                        ),
                    )
                    legacy_resealed = True
            for row in con.execute(
                "SELECT id,login FROM principals WHERE display_login IS NULL"
            ).fetchall():
                con.execute(
                    "UPDATE principals SET login=?,display_login=? WHERE id=?",
                    (
                        self.box.subject("account:" + row["login"]),
                        self.box.seal(row["login"].encode(), "login:" + row["id"]),
                        row["id"],
                    ),
                )
                legacy_resealed = True
        if legacy_resealed:
            self.database.compact_legacy()

    def encode(self, value, binding):
        return json.dumps(
            {"__sealed__": self.box.seal_json(value, binding), "schema": 1}
        )

    def decode(self, value, binding):
        packed = json.loads(value)
        return (
            self.box.open_json(packed["__sealed__"], binding)
            if "__sealed__" in packed
            else packed
        )

    def audit(self, event, detail, ref="SYSTEM"):
        with self.lock, self.connect() as con:
            con.execute(
                "INSERT INTO audit(created,type,ref,detail) VALUES(?,?,?,?)",
                (utcnow(), event, ref, detail),
            )

    def events(self):
        with self.connect() as con:
            return [
                dict(r)
                for r in con.execute("SELECT * FROM audit ORDER BY id DESC LIMIT 500")
            ]

    def results(self):
        with self.connect() as con:
            return [
                self.decode(r["payload"], "results:" + r["id"])
                for r in con.execute(
                    "SELECT id,payload FROM results ORDER BY created DESC LIMIT 500"
                )
            ]

    def result(self, result_id):
        with self.connect() as con:
            r = con.execute(
                "SELECT payload FROM results WHERE id=?", (result_id,)
            ).fetchone()
            return self.decode(r["payload"], "results:" + result_id) if r else None

    def save_result(self, result):
        with self.lock, self.connect() as con:
            con.execute(
                "INSERT INTO results VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET created=excluded.created,payload=excluded.payload",
                (
                    result["id"],
                    result["created"],
                    self.encode(result, "results:" + result["id"]),
                ),
            )

    def update_result(self, result_id, changes):
        with self.lock:
            result = self.result(result_id)
            if not result:
                raise ValueError("Permohonan tidak ditemukan.")
            if result["status"] not in ["manual", "scheduled"]:
                raise ValueError("Permohonan sudah selesai atau bukan antrean manual.")
            result.update(changes)
            self.save_result(result)
            return result

    def settings(self):
        with self.connect() as con:
            stored = json.loads(
                con.execute("SELECT payload FROM settings WHERE id=1").fetchone()[
                    "payload"
                ]
            )
            return {key: stored[key] for key in DEFAULT_SETTINGS}

    def set_settings(self, settings):
        with self.lock, self.connect() as con:
            con.execute(
                "UPDATE settings SET payload=? WHERE id=1",
                (json.dumps({**settings, "face_model": FACE_MODEL_ID}),),
            )
        self.audit("Konfigurasi diperbarui", json.dumps(settings))

    def save_registration(self, record):
        with self.lock, self.connect() as con:
            con.execute(
                "INSERT INTO registrations VALUES (?,?,?,?)",
                (
                    record["id"],
                    record["created"],
                    record["verification_id"],
                    self.encode(record, "registrations:" + record["id"]),
                ),
            )

    def registration(self, registration_id):
        with self.connect() as con:
            row = con.execute(
                "SELECT payload FROM registrations WHERE id=?", (registration_id,)
            ).fetchone()
            return (
                self.decode(row["payload"], "registrations:" + registration_id)
                if row
                else None
            )

    def registration_for_verification(self, verification_id):
        with self.connect() as con:
            row = con.execute(
                "SELECT id,payload FROM registrations WHERE verification_id=?",
                (verification_id,),
            ).fetchone()
            return (
                self.decode(row["payload"], "registrations:" + row["id"])
                if row
                else None
            )
