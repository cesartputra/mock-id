"""Persistent application decisions, bound to an evidence revision."""

import json
import os
import time
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from fastapi import HTTPException
from app.model.repository import utcnow
from app.services.score_policy import DEMO_SOFT_CONTROLS, ScorePolicy
from app.services.authority import AuthorityService

JAKARTA = ZoneInfo("Asia/Jakarta")
DEFAULT_FLOW = {
    "timezone": "Asia/Jakarta",
    "workdays": [0, 1, 2, 3, 4],
    "opens": "08:00",
    "closes": "17:00",
    "daily_capacity": 10,
    "holidays": [],
    "booking_horizon_days": 14,
    "decision_ttl_hours": 24,
    "retention_days": 21,
    "label": "Contoh demo — bukan SOP OJK",
}
TRANSITIONS = {
    "REQUEST_CREATED": {"VERIFYING"},
    "VERIFYING": {
        "AUTO_APPROVED",
        "MANUAL_PENDING",
        "REJECTED",
        "CAPTURE_RETRY",
        "TECHNICAL_PENDING",
    },
    "CAPTURE_RETRY": {"VERIFYING"},
    "TECHNICAL_PENDING": {"VERIFYING", "SLIK_PENDING"},
    "AUTO_APPROVED": {"SLIK_PENDING", "VERIFYING"},
    "MANUAL_PENDING": {"MANUAL_SCHEDULED", "VERIFYING"},
    "MANUAL_SCHEDULED": {"MANUAL_PENDING", "MANUAL_IN_REVIEW", "VERIFYING"},
    "MANUAL_IN_REVIEW": {
        "MANUAL_APPROVED",
        "MANUAL_REJECTED",
        "CAPTURE_RETRY",
        "VERIFYING",
    },
    "MANUAL_APPROVED": {"SLIK_PENDING", "VERIFYING"},
    "MANUAL_REJECTED": set(),
    "REJECTED": set(),
    "SLIK_PENDING": {"SLIK_READY", "VERIFYING"},
    "SLIK_READY": {"VERIFYING"},
}


class WorkflowService:
    def __init__(self, repository, box, evidence, authority_adapter=None):
        self.repository, self.box, self.evidence = repository, box, evidence
        self.policy = ScorePolicy()
        self.authority = authority_adapter or AuthorityService()
        with repository.connect(write=True) as con:
            con.execute(
                "INSERT INTO flow_settings VALUES (1,?) ON CONFLICT(id) DO NOTHING",
                (json.dumps(DEFAULT_FLOW),),
            )

    def settings(self, con=None):
        if con:
            return json.loads(
                con.execute("SELECT payload FROM flow_settings WHERE id=1").fetchone()[
                    "payload"
                ]
            )
        with self.repository.connect() as connection:
            return self.settings(connection)

    def get(self, con, application_id):
        row = con.execute(
            "SELECT * FROM applications WHERE id=?", (application_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "Permohonan tidak ditemukan.")
        return {
            **dict(row),
            "payload": self.repository.decode(
                row["payload"], "applications:" + row["id"]
            ),
        }

    def save(self, con, app):
        app["updated"] = utcnow()
        con.execute(
            "UPDATE applications SET subject_id=?,revision=?,state=?,updated=?,payload=? WHERE id=?",
            (
                app["subject_id"],
                app["revision"],
                app["state"],
                app["updated"],
                self.repository.encode(app["payload"], "applications:" + app["id"]),
                app["id"],
            ),
        )

    def transition(self, app, target):
        if target not in TRANSITIONS.get(app["state"], set()):
            raise HTTPException(
                409, "Transisi permohonan tidak valid: " + app["state"] + " → " + target
            )
        app["payload"].setdefault("history", []).append(
            {
                "from": app["state"],
                "to": target,
                "at": utcnow(),
                "revision": app["revision"],
            }
        )
        app["state"] = target

    def authorize(self, con, app, actor, operator=False):
        if app["owner_id"] == actor["id"]:
            return
        if operator and actor["role"] in ["helpdesk", "admin"]:
            case = con.execute(
                "SELECT * FROM manual_cases WHERE application_id=?", (app["id"],)
            ).fetchone()
            if actor["role"] == "admin" or (
                case and (not case["assigned_to"] or case["assigned_to"] == actor["id"])
            ):
                return
        raise HTTPException(404, "Permohonan tidak ditemukan atau tidak dapat diakses.")

    def public(self, app, operator=False):
        p = app["payload"]
        routing = p.get("routing") or {}
        value = {
            "id": app["id"],
            "state": app["state"],
            "capture_revision": app["revision"],
            "created": app["created"],
            "updated": app["updated"],
            "name": p.get("name"),
            "nik_masked": p.get("nik_masked"),
            "reason": p.get("reason"),
            "routing": (
                routing
                if operator
                else {
                    k: routing.get(k)
                    for k in [
                        "demo_routing_score",
                        "routing_score",
                        "calibrated",
                        "policy_version",
                        "decision",
                        "scope",
                        "automatic_threshold",
                        "demo_model_override",
                        "security_review",
                    ]
                }
            ),
            "verification_id": p.get("verification_id"),
            "identity_verified": p.get("identity_verified", False),
            "identity_demo_passed": p.get("identity_demo_passed", False),
            "authority_verified": p.get("authority_verified", False),
            "channel": "authenticated_dashboard",
            "review_note_evidence": (p.get("review") or {}).get("note_evidence"),
            "decision": p.get("decision"),
            "reservation": p.get("reservation"),
            "manual_admission": p.get("manual_admission"),
            "slik": p.get("slik"),
            "retry": p.get("retry"),
            "owner_id": app["owner_id"] if operator else None,
            "missing_controls": [
                k for k, v in routing.get("mandatory", {}).items() if not v
            ],
            "appeal": "Penolakan berlaku untuk permohonan ini. Hubungi helpdesk atau ajukan peninjauan melalui aplikasi induk; demo tidak mengirim pesan.",
        }
        if operator:
            value.update(
                evidence=p.get("evidence", []),
                verification_id=p.get("verification_id"),
                history=p.get("history", []),
                review=p.get("review"),
                identity_assessment=p.get("identity_assessment"),
            )
        return value

    def create(self, owner):
        now = utcnow()
        app = {
            "id": "APP-" + uuid.uuid4().hex[:16].upper(),
            "owner_id": owner["id"],
            "subject_id": None,
            "revision": 0,
            "state": "REQUEST_CREATED",
            "created": now,
            "updated": now,
            "payload": {"authority_attested": False, "capture_count": 1, "history": []},
        }
        with self.repository.connect(write=True) as con:
            con.execute(
                "INSERT INTO applications VALUES (?,?,?,?,?,?,?,?)",
                (
                    app["id"],
                    app["owner_id"],
                    None,
                    0,
                    app["state"],
                    now,
                    now,
                    self.repository.encode(app["payload"], "applications:" + app["id"]),
                ),
            )
            self.transition(app, "VERIFYING")
            self.save(con, app)
        return app

    def attest(self, application_id, owner, accepted):
        with self.repository.connect(write=True) as con:
            app = self.get(con, application_id)
            self.authorize(con, app, owner)
            if app["state"] != "VERIFYING":
                raise HTTPException(
                    409, "Pernyataan diberikan sebelum keputusan verifikasi."
                )
            app["payload"]["authority_attested"] = bool(accepted)
            app["payload"]["authority_attested_at"] = utcnow()
            self.save(con, app)
        self.repository.audit(
            "Pernyataan kewenangan",
            "Pemohon menyatakan permohonan untuk diri sendiri.",
            application_id,
        )
        return self.public(app)

    def invalidate(self, application_id, actor, revision, new_capture=False):
        with self.repository.connect(write=True) as con:
            app = self.get(con, application_id)
            self.authorize(con, app, actor)
            if revision <= app["revision"]:
                raise HTTPException(
                    409, "Generasi capture sudah berubah. Gunakan sesi terbaru."
                )
            if new_capture and app["payload"].get("capture_count", 1) >= 3:
                raise HTTPException(
                    429,
                    "Batas tiga sesi kamera untuk permohonan ini tercapai. Hubungi bantuan atau buat permohonan baru.",
                )
            if new_capture:
                app["payload"]["capture_count"] = (
                    app["payload"].get("capture_count", 1) + 1
                )
            if app["state"] in ["REJECTED", "MANUAL_REJECTED"]:
                raise HTTPException(
                    409,
                    "Permohonan telah ditolak. Buat permohonan baru atau minta peninjauan.",
                )
            if app["state"] != "VERIFYING":
                self.transition(app, "VERIFYING")
            app["revision"] = revision
            app["payload"].update(
                decision=None,
                slik=None,
                routing=None,
                evidence=[],
                verification_id=None,
                reservation=None,
                identity_demo_passed=False,
            )
            con.execute(
                "UPDATE manual_cases SET state='CANCELLED' WHERE application_id=? AND state NOT IN ('CANCELLED','COMPLETED')",
                (app["id"],),
            )
            con.execute(
                "UPDATE issuance SET state='REVOKED' WHERE application_id=?",
                (app["id"],),
            )
            self.save(con, app)
            con.execute(
                "INSERT INTO audit(created,type,ref,detail) VALUES (?,?,?,?)",
                (
                    utcnow(),
                    "Keputusan dibatalkan",
                    app["id"],
                    "Bukti diganti; pemeriksaan baru diperlukan.",
                ),
            )
        return app

    def ingest(self, session, result, selfie, holding, frames):
        if not session.application_id:
            return None
        with self.repository.connect(write=True) as con:
            app = self.get(con, session.application_id)
            if app["revision"] != session.revision or app["state"] != "VERIFYING":
                raise HTTPException(
                    409, "Bukti sudah berubah atau permohonan telah diputuskan."
                )
            fields = dict(session.document_result["fields"])
            subject = self.box.subject(fields["nik"])
            app["subject_id"] = subject
            controls = [
                c
                for c in result["checks"]
                if c.get("effect") != "advisory" and c["mode"] != "mock"
            ]
            from datetime import date
            import re

            try:
                valid_birth = (
                    bool(fields.get("birth"))
                    and date.fromisoformat(fields["birth"]) <= date.today()
                )
            except ValueError:
                valid_birth = False
            complete = bool(
                fields.get("name", "").strip()
                and valid_birth
                and re.fullmatch("[0-9]{16}", fields.get("nik", ""))
            )
            all_local = bool(controls) and all(
                c["status"] == "passed" for c in controls
            )
            authority = self.authority.check(
                app["owner_id"], fields, app["payload"].get("authority_attested", False)
            )
            mandatory = {
                "session_nonce_proof": bool(
                    session.consumed
                    and session.proof_checked_revision == session.revision
                    and session.liveness_result
                    and session.liveness_result.get("passed")
                ),
                "document_identity_complete": complete,
                "document_face_liveness_pad": all_local,
                "no_security_rejection": result["status"] != "attack",
                "applicant_authority": bool(authority["verified"]),
                "approved_identity_procedure": (
                    all_local
                    if self.policy.mode == "demo"
                    else bool(result.get("identity_verified"))
                ),
            }
            demo_eligible = bool(controls) and all(
                c["status"] == "passed"
                or (c["status"] == "failed" and c["name"] in DEMO_SOFT_CONTROLS)
                for c in controls
            )
            policy_result = {**result, "demo_score_eligible": demo_eligible}
            if result["status"] == "pass" and not complete:
                policy_result = {**policy_result, "status": "capture"}
            routing = self.policy.route(policy_result, mandatory)
            routing_reason = {
                "MANUAL_PENDING": "Verifikasi otomatis memerlukan pemeriksaan tambahan oleh helpdesk.",
                "REJECTED": "Permohonan ini belum dapat disetujui. Gunakan informasi bantuan atau peninjauan keberatan.",
                "AUTO_APPROVED": "Kontrol lokal dan kewenangan permohonan demo terpenuhi. Hanya hasil sintetis yang dapat dibuka.",
            }.get(routing["decision"], result["reason"])
            if routing.get("demo_model_override"):
                routing_reason = "Skor routing demo memenuhi ambang ≥50/100. Ketidakpastian model diterima khusus untuk PDF sintetis; skor dan kontrol asli tetap tercatat."
            if routing["security_review"]:
                routing_reason = "Pemeriksaan memberi sinyal risiko keamanan. Sinyal model bukan bukti pasti penipuan; permohonan ini memerlukan peninjauan keamanan."
            app["payload"].update(
                name=fields.get("name"),
                nik_masked=result["nik_masked"],
                routing=routing,
                verification_id=result["id"],
                reason=(
                    "Nama dan tanggal lahir belum lengkap. Perbaiki data OCR."
                    if not complete
                    else routing_reason
                ),
                identity_verified=bool(result.get("identity_verified")),
                identity_demo_passed=bool(result.get("identity_demo_passed")),
                authority_verified=bool(authority["verified"]),
                authority_assessment=authority,
                identity_assessment={
                    "procedure": (
                        "demo_local_capture"
                        if self.policy.mode == "demo"
                        else "official_adapter_required"
                    ),
                    "official": bool(result.get("identity_verified")),
                },
                retry=result.get("retry")
                or (
                    {
                        "stage": "document",
                        "label": "Lengkapi identitas",
                        "reason": "Nama dan tanggal lahir diperlukan.",
                    }
                    if not complete
                    else None
                ),
            )
            days = self.settings(con)["retention_days"]
            policy = routing["policy_version"]
            evidence = [
                self.evidence.json(con, app, "identity", fields, days, policy),
                self.evidence.json(
                    con,
                    app,
                    "verification",
                    {
                        "result": result,
                        "session_binding": {
                            "session_id": session.id,
                            "capture_revision": session.revision,
                            "proof_bound": mandatory["session_nonce_proof"],
                            "selfie_digest": session.liveness_selfie,
                        },
                    },
                    days,
                    policy,
                ),
            ]
            for kind, image in [
                ("document", session.document),
                ("selfie", selfie),
                ("holding", holding),
            ]:
                meta = self.evidence.image(con, app, kind, image, days, policy)
                meta["source_sha256"] = {
                    "document": session.document_digest,
                    "selfie": session.liveness_selfie,
                    "holding": session.holding_digest,
                }[kind]
                evidence.append(meta)
            for i, image in enumerate(frames[:3]):
                evidence.append(
                    self.evidence.image(
                        con, app, "gesture-" + str(i), image, days, policy
                    )
                )
            app["payload"]["evidence"] = evidence
            app["payload"]["control_policy_snapshot"] = result.get("rules", {})
            self.transition(app, routing["decision"])
            if routing["decision"] == "AUTO_APPROVED":
                self.approval(app, "automatic", None)
            self.save(con, app)
            con.execute(
                "INSERT INTO audit(created,type,ref,detail) VALUES (?,?,?,?)",
                (
                    utcnow(),
                    "Routing permohonan",
                    app["id"],
                    routing["decision"] + "; policy " + routing["policy_version"],
                ),
            )
        return self.public(app)

    def approval(self, app, kind, actor):
        now = time.time()
        config = self.settings()
        app["payload"]["decision"] = {
            "kind": kind,
            "revision": app["revision"],
            "subject_id": app["subject_id"],
            "policy_version": app["payload"]["routing"]["policy_version"],
            "authority_basis": app["payload"].get("authority_assessment"),
            "control_policy_snapshot": app["payload"].get("control_policy_snapshot"),
            "at": utcnow(),
            "expires": now + config["decision_ttl_hours"] * 3600,
            "reviewer_id": actor["id"] if actor else None,
            "identity_verified": app["payload"].get("identity_verified", False),
            "authority_verified": app["payload"].get("authority_verified", False),
            "scope": "synthetic_only" if self.policy.mode == "demo" else "production",
        }

    def snapshot(self, application_id, actor):
        with self.repository.connect() as con:
            app = self.get(con, application_id)
            self.authorize(con, app, actor, operator=True)
            return self.public(app, actor["role"] in ["helpdesk", "admin"])

    def identity(self, con, app):
        meta = next(
            (e for e in app["payload"].get("evidence", []) if e["kind"] == "identity"),
            None,
        )
        if not meta:
            raise HTTPException(409, "Bukti identitas tidak tersedia.")
        content, _ = self.evidence.read(con, meta["id"])
        return json.loads(content)

    def technical(self, session):
        if not session.application_id:
            return
        with self.repository.connect(write=True) as con:
            app = self.get(con, session.application_id)
            if app["state"] == "VERIFYING" and app["revision"] == session.revision:
                self.transition(app, "TECHNICAL_PENDING")
                app["payload"][
                    "reason"
                ] = "Pemeriksaan atau penyimpanan belum selesai. Hasil belum diputuskan."
                app["payload"]["retry"] = {
                    "stage": "verify",
                    "label": "Jalankan pemeriksaan kembali",
                    "reason": app["payload"]["reason"],
                }
                self.save(con, app)
