"""Administrator cleanup of one application, plus revision-bound card crop storage."""
import json
import time
import cv2
import numpy as np
from fastapi import HTTPException
from app.model.repository import utcnow
from app.services.document import document_crop

JSON_KINDS = {"identity", "verification", "manual-review"}


def is_photo(kind):
    return kind not in JSON_KINDS


class OperatorDataService:
    def __init__(self, workflow, sessions):
        self.flow, self.sessions = workflow, sessions
        self.repository = workflow.repository

    @staticmethod
    def admin(actor):
        if actor["role"] != "admin":
            raise HTTPException(403, "Clean data hanya dapat dilakukan administrator.")

    def related(self, con, app):
        rows = [dict(r) for r in con.execute("SELECT * FROM evidence WHERE application_id=?", (app["id"],)).fetchall()]
        session_ids = {s.id for s in self.sessions.items.values() if s.application_id == app["id"]}
        session_ids.update(app["payload"].get("session_ids", []))
        verification_ids = {app["payload"].get("verification_id")}
        # Include past capture revisions. Expired evidence is decrypted internally
        # only to locate deletion targets; no private content is returned to UI.
        for row in rows:
            if row["kind"] == "verification" and row["ciphertext"]:
                cipher = row["ciphertext"]
                if cipher.startswith("s3:"):
                    if not self.flow.evidence.storage:
                        raise HTTPException(503, "Storage bukti belum tersedia.")
                    cipher = self.flow.evidence.storage.get(cipher[3:])
                packed = json.loads(self.flow.box.open(cipher, self.flow.evidence.binding(row)))
                session_ids.add((packed.get("session_binding") or {}).get("session_id"))
                verification_ids.add((packed.get("result") or {}).get("id"))
        session_ids.discard(None)
        verification_ids.discard(None)
        results = []
        for row in con.execute("SELECT id,payload FROM results").fetchall():
            value = self.repository.decode(row["payload"], "results:" + row["id"])
            if (row["id"] in verification_ids or value.get("session_id") in session_ids
                    or (value.get("application") or {}).get("id") == app["id"]):
                results.append(row["id"])
        verification_ids.update(results)
        registrations = []
        for row in con.execute("SELECT id,payload,verification_id FROM registrations").fetchall():
            value = self.repository.decode(row["payload"], "registrations:" + row["id"])
            if value.get("application_id") == app["id"] or row["verification_id"] in verification_ids:
                registrations.append(row["id"])
        return rows, session_ids, results, registrations

    def plan(self, application_id, actor):
        self.admin(actor)
        with self.sessions.lock, self.repository.connect() as con:
            app = self.flow.get(con, application_id)
            rows, _, results, registrations = self.related(con, app)
            return {"application_id": app["id"], "name": app["payload"].get("name"),
                    "capture_revision": app["revision"], "updated_at": app["updated"],
                    "photos": sum(is_photo(r["kind"]) and bool(r["ciphertext"]) for r in rows),
                    "results": len(results), "registrations": len(registrations),
                    "reports": con.execute("SELECT COUNT(*) AS n FROM issuance WHERE application_id=?", (app["id"],)).fetchone()["n"],
                    "scope": "selected_application"}

    def clean(self, application_id, actor, mode, revision, expected_updated_at, confirm_application_id):
        with self.sessions.lock:
            return self._clean(application_id, actor, mode, revision, expected_updated_at, confirm_application_id)

    def _clean(self, application_id, actor, mode, revision, expected_updated_at, confirm_application_id):
        self.admin(actor)
        if mode not in {"photos", "full"} or confirm_application_id != application_id:
            raise HTTPException(422, "Pilihan atau konfirmasi permohonan tidak sesuai.")
        with self.sessions.lock, self.repository.connect(write=True) as con:
            app = self.flow.get(con, application_id)
            if app["revision"] != revision or app["updated"] != expected_updated_at:
                raise HTTPException(409, "Data permohonan berubah. Buka kembali konfirmasi clean data.")
            active = [s for s in self.sessions.items.values() if s.application_id == application_id]
            if any(s.processing or s.liveness_processing for s in active):
                raise HTTPException(409, "Capture masih diproses. Tunggu sebelum membersihkan data.")
            if con.execute("SELECT id FROM issuance WHERE application_id=? AND state='IN_FLIGHT' AND lease_until>?",
                           (application_id, time.time())).fetchone():
                raise HTTPException(409, "PDF sedang diproses. Tunggu sebelum membersihkan data.")
            rows, session_ids, results, registrations = self.related(con, app)
            targets = rows if mode == "full" else [r for r in rows if is_photo(r["kind"])]
            remote = [r["ciphertext"][3:] for r in targets if (r["ciphertext"] or "").startswith("s3:")]
            if remote and not self.flow.evidence.storage:
                raise HTTPException(503, "Storage diperlukan untuk menghapus foto/objek bukti.")
            for key in remote:
                self.flow.evidence.storage.delete(key)
            count = sum(bool(r["ciphertext"]) and is_photo(r["kind"]) for r in targets)
            now = utcnow()
            if mode == "photos":
                for row in targets:
                    con.execute("UPDATE evidence SET ciphertext=NULL WHERE id=?", (row["id"],))
                for entry in app["payload"].get("evidence", []):
                    if is_photo(entry["kind"]):
                        entry["deleted_at"] = now
                app["payload"]["photo_cleanup"] = {"at": now, "count": count}
                app["payload"]["document_crop_status"] = "photos_deleted"
                self.flow.save(con, app)
            else:
                refs = {application_id, *session_ids, *results, *registrations}
                for table in ["manual_cases", "issuance"]:
                    refs.update(r["id"] for r in con.execute("SELECT id FROM " + table + " WHERE application_id=?", (application_id,)).fetchall())
                for row in con.execute("SELECT owner_id,key,response FROM idempotency").fetchall():
                    value = self.repository.decode(row["response"], "idempotency:" + row["owner_id"] + ":" + row["key"])
                    if application_id in json.dumps(value):
                        con.execute("DELETE FROM idempotency WHERE owner_id=? AND key=?", (row["owner_id"], row["key"]))
                for record_id in registrations:
                    con.execute("DELETE FROM registrations WHERE id=?", (record_id,))
                for record_id in results:
                    con.execute("DELETE FROM results WHERE id=?", (record_id,))
                for ref in refs:
                    con.execute("DELETE FROM audit WHERE ref=?", (ref,))
                for table in ["evidence", "manual_cases", "issuance"]:
                    con.execute("DELETE FROM " + table + " WHERE application_id=?", (application_id,))
                con.execute("DELETE FROM applications WHERE id=?", (application_id,))
            con.execute("INSERT INTO audit(created,type,ref,detail) VALUES (?,?,?,?)",
                        (now, "Clean data permohonan", "SYSTEM" if mode == "full" else application_id,
                         f"Administrator {actor['id']}; mode {mode}; {count} foto. Cakupan satu permohonan."))
        # Invalidate retained arrays/proofs only after the DB transaction commits.
        # Late camera responses also see data_cleaned and cannot restore captures.
        with self.sessions.lock:
            for session in active:
                session.data_cleaned = True
                session.document = session.document_result = session.document_probe = session.document_consensus = None
                session.last_result = None
                self.sessions.clear_liveness(session)
                self.sessions.items.pop(session.id, None)
        return {"mode": mode, "application_id": application_id, "deleted_photos": count,
                "application_deleted": mode == "full", "scope": "selected_application"}

    def crop_source(self, application_id, actor):
        with self.repository.connect() as con:
            app = self.flow.get(con, application_id)
            self.flow.authorize(con, app, actor, operator=True)
            crop = next((e for e in app["payload"].get("evidence", []) if e["kind"] == "document-crop" and not e.get("deleted_at")), None)
            if crop:
                self.flow.evidence.read(con, crop["id"])
                return self.flow.public(app, True), None
            source = next((e for e in app["payload"].get("evidence", []) if e["kind"] == "document" and not e.get("deleted_at")), None)
            if not source:
                raise HTTPException(410, "Foto KTP tidak tersedia atau telah dihapus.")
            content, _ = self.flow.evidence.read(con, source["id"])
            image = cv2.imdecode(np.frombuffer(content, np.uint8), cv2.IMREAD_COLOR)
            if image is None:
                raise HTTPException(422, "Foto KTP tersimpan tidak dapat dibaca.")
            identity = self.flow.identity(con, app)
            return None, (app["revision"], source, image, identity["nik"])

    def save_crop(self, application_id, actor, revision, source, image, reading, expected_nik):
        selected = document_crop(image, reading)
        if reading.get("fields", {}).get("nik") != expected_nik or selected is None:
            raise HTTPException(422, "Area KTP belum dapat dipisahkan dengan yakin. Foto asli tetap tersedia; ambil ulang KTP yang bingkainya terlihat.")
        crop, info = selected
        with self.repository.connect(write=True) as con:
            app = self.flow.get(con, application_id)
            self.flow.authorize(con, app, actor, operator=True)
            if app["revision"] != revision or source["id"] not in [e["id"] for e in app["payload"].get("evidence", [])]:
                raise HTTPException(409, "Foto KTP sudah diganti. Muat permohonan terbaru.")
            self.flow.evidence.read(con, source["id"])  # Cleanup/expiry during OCR cannot resurrect a photo.
            if any(e["kind"] == "document-crop" and not e.get("deleted_at") for e in app["payload"]["evidence"]):
                return self.flow.public(app, True)
            meta = self.flow.evidence.image(con, app, "document-crop", crop, 1,
                                           source["policy_version"], expires=source["expires"])
            meta.update(derived_from=source["id"], crop=info)
            app["payload"]["evidence"].append(meta)
            app["payload"]["document_crop_status"] = "available"
            self.flow.save(con, app)
            con.execute("INSERT INTO audit(created,type,ref,detail) VALUES (?,?,?,?)",
                        (utcnow(), "Crop KTP tersimpan", app["id"], f"Actor {actor['id']}; revision {revision}; turunan foto server."))
            return self.flow.public(app, True)
