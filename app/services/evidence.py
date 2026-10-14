"""Minimal AEAD-sealed evidence, accessed only through authorized controllers."""

import json
import hashlib
import os
import time
import uuid
import cv2
from fastapi import HTTPException
from app.model.repository import utcnow


class PrivateObjectStorage:
    def put(self, key, ciphertext):
        raise NotImplementedError

    def get(self, key):
        raise NotImplementedError

    def delete(self, key):
        raise NotImplementedError


class S3PrivateStorage(PrivateObjectStorage):
    """Optional private S3-compatible storage; IAM credentials stay outside code."""

    def __init__(self, bucket, endpoint=None):
        if endpoint and not endpoint.startswith("https://"):
            raise ValueError("Object storage membutuhkan TLS.")
        import boto3

        self.client = boto3.client("s3", endpoint_url=endpoint)
        self.bucket = bucket
        block = self.client.get_public_access_block(Bucket=bucket)[
            "PublicAccessBlockConfiguration"
        ]
        if not all(
            block.get(k)
            for k in [
                "BlockPublicAcls",
                "IgnorePublicAcls",
                "BlockPublicPolicy",
                "RestrictPublicBuckets",
            ]
        ):
            raise ValueError("Bucket bukti harus memblokir akses publik.")

    def put(self, key, ciphertext):
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=ciphertext.encode(),
            ContentType="application/octet-stream",
            ServerSideEncryption="AES256",
        )

    def get(self, key):
        return (
            self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read().decode()
        )

    def delete(self, key):
        self.client.delete_object(Bucket=self.bucket, Key=key)


class EvidenceStore:
    def __init__(self, repository, box, storage=None):
        self.repository, self.box, self.storage = repository, box, storage

    @staticmethod
    def binding(metadata):
        fields = [
            "id",
            "application_id",
            "subject_id",
            "revision",
            "policy_version",
            "kind",
            "expires",
        ]
        if metadata.get("binding_version", 1) >= 2:
            fields += ["created", "binding_version"]
        return json.dumps(
            {k: metadata[k] for k in fields}, sort_keys=True, separators=(",", ":")
        )

    def save(self, con, application, kind, content, retention_days, policy, expires=None):
        meta = {
            "id": "EVD-" + uuid.uuid4().hex,
            "application_id": application["id"],
            "subject_id": application["subject_id"],
            "revision": application["revision"],
            "policy_version": policy,
            "kind": kind,
            "created": utcnow(),
            "expires": expires if expires is not None else time.time() + retention_days * 86400,
            "binding_version": 2,
        }
        sealed = self.box.seal(content, self.binding(meta))
        # Keep the local DB write atomic with the workflow. S3 operations are
        # immutable; failed DB commits may leave opaque encrypted orphan objects.
        if self.storage:
            self.storage.put(meta["id"], sealed)
            sealed = "s3:" + meta["id"]
        con.execute(
            "INSERT INTO evidence (id,application_id,subject_id,revision,policy_version,kind,created,expires,ciphertext,binding_version) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                meta["id"],
                meta["application_id"],
                meta["subject_id"],
                meta["revision"],
                meta["policy_version"],
                kind,
                meta["created"],
                meta["expires"],
                sealed,
                meta["binding_version"],
            ),
        )
        return meta

    def json(self, con, application, kind, value, days, policy):
        return self.save(
            con,
            application,
            kind,
            json.dumps(value, ensure_ascii=False, allow_nan=False).encode(),
            days,
            policy,
        )

    def image(self, con, application, kind, image, days, policy, expires=None):
        encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 90])[
            1
        ].tobytes()
        meta = self.save(con, application, kind, encoded, days, policy, expires=expires)
        meta["stored_content_sha256"] = hashlib.sha256(encoded).hexdigest()
        meta["transform"] = "Decoded server image, EXIF removed, JPEG quality 90"
        return meta

    def read(self, con, evidence_id):
        row = con.execute(
            "SELECT * FROM evidence WHERE id=?", (evidence_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "Bukti tidak ditemukan.")
        meta = dict(row)
        if not row["ciphertext"] and row["expires"] > time.time():
            raise HTTPException(410, "Foto bukti telah dihapus oleh administrator.")
        if not row["ciphertext"] or row["expires"] <= time.time():
            raise HTTPException(
                410, "Retensi bukti telah berakhir. Capture baru diperlukan."
            )
        cipher = row["ciphertext"]
        if cipher.startswith("s3:"):
            if not self.storage:
                raise HTTPException(503, "Object storage belum tersedia.")
            cipher = self.storage.get(cipher[3:])
        return self.box.open(cipher, self.binding(meta)), meta

    def purge(self):
        with self.repository.connect(write=True) as con:
            rows = con.execute(
                "SELECT id,ciphertext FROM evidence WHERE expires<=? AND ciphertext IS NOT NULL",
                (time.time(),),
            ).fetchall()
            for row in rows:
                if row["ciphertext"].startswith("s3:"):
                    if not self.storage:
                        raise RuntimeError(
                            "S3 diperlukan untuk menghapus objek bukti, metadata tidak dihapus lebih dahulu."
                        )
                    self.storage.delete(row["ciphertext"][3:])
            con.execute(
                "UPDATE evidence SET ciphertext=NULL WHERE expires<=?", (time.time(),)
            )
        if rows:
            self.repository.audit(
                "Retensi bukti", "Bukti kedaluwarsa dihapus: " + str(len(rows))
            )
        return len(rows)
