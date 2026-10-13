"""Persistent opaque sessions. X-Local-Client is only an origin/CSRF marker."""

import hashlib
import secrets
import time
import uuid
from fastapi import HTTPException
from app.model.repository import utcnow
from app.services.secrets_store import SecretBox


class AuthService:
    def __init__(self, repository, box=None):
        self.repository = repository
        self.box = box or SecretBox(repository.path.parent)

    def create_user(self, login, password, role="applicant"):
        if role not in {"applicant", "helpdesk", "admin", "integration"}:
            raise ValueError("Peran tidak valid.")
        if not 3 <= len(login.strip()) <= 80 or not 10 <= len(password) <= 200:
            raise HTTPException(
                422, "Nama akun 3–80 karakter dan sandi minimal 10 karakter."
            )
        salt = secrets.token_bytes(16)
        digest = hashlib.scrypt(
            password.encode(), salt=salt, n=16384, r=8, p=1, dklen=32
        ).hex()
        principal = {
            "id": str(uuid.uuid4()),
            "login": login.strip().lower(),
            "role": role,
        }
        with self.repository.connect(write=True) as con:
            if con.execute(
                "SELECT id FROM principals WHERE login=?",
                (self.box.subject("account:" + principal["login"]),),
            ).fetchone():
                raise HTTPException(409, "Nama akun sudah digunakan.")
            con.execute(
                "INSERT INTO principals (id,login,password_hash,role,enabled,display_login) VALUES (?,?,?,?,1,?)",
                (
                    principal["id"],
                    self.box.subject("account:" + principal["login"]),
                    salt.hex() + ":" + digest,
                    role,
                    self.box.seal(
                        principal["login"].encode(), "login:" + principal["id"]
                    ),
                ),
            )
        return principal

    def set_password(self, login, password):
        """Local administrator CLI only; preserve identity/role and revoke sessions."""
        normalized = login.strip().lower()
        if not 3 <= len(normalized) <= 80 or not 10 <= len(password) <= 200:
            raise HTTPException(
                422, "Nama akun 3–80 karakter dan password baru 10–200 karakter."
            )
        salt = secrets.token_bytes(16)
        digest = hashlib.scrypt(
            password.encode(), salt=salt, n=16384, r=8, p=1, dklen=32
        ).hex()
        with self.repository.connect(write=True) as con:
            row = con.execute(
                "SELECT id,role,enabled,auth_kind FROM principals WHERE login=?",
                (self.box.subject("account:" + normalized),),
            ).fetchone()
            if not row:
                raise HTTPException(
                    404,
                    "Akun tidak ditemukan. Gunakan nama akun yang dibuat sebelumnya.",
                )
            if row["auth_kind"] == "browser" or not row["enabled"]:
                raise HTTPException(
                    403, "Password hanya dapat diganti untuk akun password yang aktif."
                )
            con.execute(
                "UPDATE principals SET password_hash=? WHERE id=?",
                (salt.hex() + ":" + digest, row["id"]),
            )
            con.execute("DELETE FROM auth_sessions WHERE principal_id=?", (row["id"],))
            con.execute(
                "DELETE FROM rate_limits WHERE bucket=?",
                ("login:" + self.box.subject("login:" + normalized),),
            )
            con.execute(
                "INSERT INTO audit(created,type,ref,detail) VALUES (?,?,?,?)",
                (
                    utcnow(),
                    "Password akun diperbarui",
                    row["id"],
                    "Reset melalui administrator lokal; semua sesi akun dicabut.",
                ),
            )
        return {"id": row["id"], "login": normalized, "role": row["role"]}

    def guest(self, token=None):
        """A browser capability owns demo requests, without an applicant login."""
        if token:
            try:
                who = self.principal(token)
                if who.get("guest"):
                    return token, who
            except HTTPException:
                pass
        uid = str(uuid.uuid4())
        login = "browser-" + secrets.token_hex(16)
        token = secrets.token_urlsafe(32)
        with self.repository.connect(write=True) as con:
            con.execute(
                "INSERT INTO principals (id,login,password_hash,role,enabled,display_login,auth_kind) VALUES (?,?,?,'applicant',1,?,'browser')",
                (
                    uid,
                    self.box.subject("account:" + login),
                    "disabled",
                    self.box.seal(b"Pemohon", "login:" + uid),
                ),
            )
            con.execute(
                "INSERT INTO auth_sessions VALUES (?,?,?)",
                (
                    hashlib.sha256(token.encode()).hexdigest(),
                    uid,
                    time.time() + 30 * 86400,
                ),
            )
        return token, {
            "id": uid,
            "login": "Pemohon",
            "role": "applicant",
            "guest": True,
        }

    def limit(self, bucket, maximum, seconds=60):
        now = time.time()
        with self.repository.connect(write=True) as con:
            row = con.execute(
                "SELECT * FROM rate_limits WHERE bucket=?", (bucket,)
            ).fetchone()
            starts, count = (
                (row["starts"], row["count"])
                if row and now - row["starts"] < seconds
                else (now, 0)
            )
            if count >= maximum:
                raise HTTPException(
                    429,
                    "Batas permintaan tercapai. Tunggu lalu coba kembali.",
                    headers={"Retry-After": str(seconds)},
                )
            con.execute(
                "INSERT INTO rate_limits VALUES (?,?,?) ON CONFLICT(bucket) DO UPDATE SET starts=excluded.starts,count=excluded.count",
                (bucket, starts, count + 1),
            )

    def login(self, login, password):
        self.limit(
            "login:" + self.box.subject("login:" + login.strip().lower()), 10, 300
        )
        # Unknown accounts still perform the same expensive password hash.
        with self.repository.connect() as con:
            row = con.execute(
                "SELECT * FROM principals WHERE login=?",
                (self.box.subject("account:" + login.strip().lower()),),
            ).fetchone()
        packed = (
            row["password_hash"]
            if row and row["auth_kind"] != "browser"
            else "00" * 16 + ":" + "00" * 32
        )
        salt, expected = packed.split(":")
        actual = hashlib.scrypt(
            password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1, dklen=32
        ).hex()
        if (
            not row
            or not row["enabled"]
            or row["auth_kind"] == "browser"
            or not secrets.compare_digest(actual, expected)
        ):
            raise HTTPException(401, "Akun atau sandi tidak sesuai.")
        token = secrets.token_urlsafe(32)
        with self.repository.connect(write=True) as con:
            # A reset may have happened while scrypt ran outside the transaction.
            # Recheck under the write lock so old credentials cannot issue a new
            # valid token after reset has revoked the previous sessions.
            current = con.execute(
                "SELECT password_hash,enabled,auth_kind FROM principals WHERE id=?",
                (row["id"],),
            ).fetchone()
            if (
                not current
                or not current["enabled"]
                or current["auth_kind"] == "browser"
                or not secrets.compare_digest(current["password_hash"], packed)
            ):
                raise HTTPException(
                    401, "Password telah berubah. Masuk dengan password terbaru."
                )
            con.execute("DELETE FROM auth_sessions WHERE expires<?", (time.time(),))
            con.execute(
                "INSERT INTO auth_sessions VALUES (?,?,?)",
                (
                    hashlib.sha256(token.encode()).hexdigest(),
                    row["id"],
                    time.time() + 12 * 3600,
                ),
            )
        return token, {
            "id": row["id"],
            "login": self.box.open(row["display_login"], "login:" + row["id"]).decode(),
            "role": row["role"],
            "guest": row["auth_kind"] == "browser",
        }

    def principal(self, token):
        if not token:
            raise HTTPException(401, "Silakan masuk ke akun Anda.")
        with self.repository.connect() as con:
            row = con.execute(
                "SELECT p.id,p.login,p.display_login,p.role,p.enabled,p.auth_kind,s.expires FROM auth_sessions s JOIN principals p ON p.id=s.principal_id WHERE token_hash=?",
                (hashlib.sha256(token.encode()).hexdigest(),),
            ).fetchone()
        if not row or not row["enabled"] or row["expires"] <= time.time():
            raise HTTPException(401, "Sesi login berakhir. Silakan masuk kembali.")
        return {
            "id": row["id"],
            "login": self.box.open(row["display_login"], "login:" + row["id"]).decode(),
            "role": row["role"],
            "guest": row["auth_kind"] == "browser",
        }

    def logout(self, token):
        with self.repository.connect(write=True) as con:
            con.execute(
                "DELETE FROM auth_sessions WHERE token_hash=?",
                (hashlib.sha256((token or "").encode()).hexdigest(),),
            )


def actor(request):
    return request.state.actor


def roles(request, *allowed):
    who = actor(request)
    if who["role"] not in allowed:
        raise HTTPException(
            403, "Akun ini tidak memiliki kewenangan untuk tindakan tersebut."
        )
    return who
