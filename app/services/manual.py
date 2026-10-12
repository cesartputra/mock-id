"""Capacity and case updates share one serializable write transaction."""

import hashlib
import json
import time
import uuid
from datetime import datetime, timedelta, date
from fastapi import HTTPException
from app.model.repository import utcnow
from app.services.workflow import JAKARTA


class ManualService:
    def __init__(self, workflow, clock=None):
        self.flow = workflow
        self.repository = workflow.repository
        self.clock = clock or (lambda: datetime.now(JAKARTA))

    def day_open(self, day, config):
        return (
            day.weekday() in config["workdays"]
            and day.isoformat() not in config["holidays"]
        )

    def used(self, con, day):
        return con.execute(
            "SELECT COUNT(*) AS n FROM manual_cases WHERE day=? AND state!='CANCELLED'",
            (day,),
        ).fetchone()["n"]

    def calendar(self):
        now = self.clock()
        config = self.flow.settings()
        days = []
        with self.repository.connect() as con:
            for delta in range(config["booking_horizon_days"] + 1):
                day = now.date() + timedelta(days=delta)
                used = self.used(con, day.isoformat())
                valid = self.day_open(day, config)
                if delta == 0 and now.strftime("%H:%M") >= config["closes"]:
                    valid = False
                days.append(
                    {
                        "day": day.isoformat(),
                        "working_day": self.day_open(day, config),
                        "used": used,
                        "remaining": (
                            max(0, config["daily_capacity"] - used) if valid else 0
                        ),
                        "available": valid and used < config["daily_capacity"],
                        "opens": config["opens"],
                        "closes": config["closes"],
                    }
                )
        today = days[0]
        within = (
            self.day_open(now.date(), config)
            and config["opens"] <= now.strftime("%H:%M") < config["closes"]
        )
        code = (
            "AVAILABLE"
            if within and today["remaining"]
            else "CAPACITY_FULL" if within else "OUTSIDE_HOURS"
        )
        message = {
            "AVAILABLE": "Verifikasi otomatis belum memadai. Anda dapat melanjutkan pemeriksaan manual menggunakan bukti yang sudah diambil.",
            "CAPACITY_FULL": "Kuota pemeriksaan manual hari ini sudah penuh. Coba kembali pada hari kerja berikutnya.",
            "OUTSIDE_HOURS": "Pemeriksaan manual tersedia pada jam kerja. Coba kembali pada hari kerja berikutnya.",
        }[code]
        return {
            "timezone": "Asia/Jakarta",
            "label": config["label"],
            "code": code,
            "message": message,
            "days": days,
            "all_full": not any(d["available"] for d in days),
        }

    def validate_day(self, day, config):
        try:
            selected = date.fromisoformat(day)
        except ValueError:
            raise HTTPException(422, "Tanggal jadwal tidak valid.")
        now = self.clock()
        if (
            selected < now.date()
            or selected > now.date() + timedelta(days=config["booking_horizon_days"])
            or not self.day_open(selected, config)
        ):
            raise HTTPException(422, "Pilih hari kerja di dalam horizon jadwal.")
        if selected == now.date() and now.strftime("%H:%M") >= config["closes"]:
            raise HTTPException(422, "Jam layanan hari ini sudah berakhir.")
        return selected

    def idempotent(self, con, actor, key, data):
        if not 8 <= len(key) <= 100:
            raise HTTPException(422, "Idempotency-Key 8–100 karakter diperlukan.")
        fingerprint = hashlib.sha256(
            json.dumps(data, sort_keys=True).encode()
        ).hexdigest()
        row = con.execute(
            "SELECT * FROM idempotency WHERE owner_id=? AND key=?", (actor["id"], key)
        ).fetchone()
        if row:
            if row["fingerprint"] != fingerprint:
                raise HTTPException(
                    409, "Idempotency key sudah dipakai untuk payload berbeda."
                )
            return fingerprint, self.repository.decode(
                row["response"], "idempotency:" + actor["id"] + ":" + key
            )
        return fingerprint, None

    def record_idempotent(self, con, actor, key, fingerprint, response):
        con.execute(
            "INSERT INTO idempotency VALUES (?,?,?,?)",
            (
                actor["id"],
                key,
                fingerprint,
                self.repository.encode(
                    response, "idempotency:" + actor["id"] + ":" + key
                ),
            ),
        )

    def admit_today(self, application_id, actor):
        # One write transaction covers the decision, final capacity check and
        # reservation. A full-day response stores no failed idempotency entry.
        with self.repository.connect(write=True) as con:
            app = self.flow.get(con, application_id)
            self.flow.authorize(con, app, actor)
            if app["state"] in ["MANUAL_SCHEDULED", "MANUAL_IN_REVIEW"]:
                return self.flow.public(app)
            if app["state"] != "MANUAL_PENDING":
                raise HTTPException(409, "Permohonan tidak menunggu verifikasi manual.")
            now = self.clock()
            config = self.flow.settings(con)
            day = now.date()
            next_day = next(
                (
                    day + timedelta(days=i)
                    for i in range(1, config["booking_horizon_days"] + 1)
                    if self.day_open(day + timedelta(days=i), config)
                ),
                None,
            )
            code = "AVAILABLE"
            if (
                not self.day_open(day, config)
                or now.strftime("%H:%M") >= config["closes"]
            ):
                code = "OUTSIDE_HOURS"
            elif self.used(con, day.isoformat()) >= config["daily_capacity"]:
                code = "CAPACITY_FULL"
            if code == "AVAILABLE":
                key = (
                    "auto-today-"
                    + hashlib.sha256(
                        (
                            application_id
                            + ":"
                            + str(app["revision"])
                            + ":"
                            + str(app["payload"].get("manual_admission_generation", 0))
                            + ":"
                            + day.isoformat()
                        ).encode()
                    ).hexdigest()
                )
                self.reserve(application_id, actor, day.isoformat(), key)
                app = self.flow.get(con, application_id)
                message = "Kuota hari ini telah diambil otomatis. Permohonan menunggu pemeriksaan helpdesk."
                code = "RESERVED"
            else:
                message = (
                    "Kuota pemeriksaan manual hari ini sudah penuh. Coba kembali pada hari kerja berikutnya."
                    if code == "CAPACITY_FULL"
                    else "Layanan pemeriksaan manual hari ini tutup. Coba kembali pada hari kerja berikutnya."
                )
            app["payload"]["manual_admission"] = {
                "code": code,
                "day": day.isoformat(),
                "next_working_day": (
                    next_day.isoformat() if next_day and code != "RESERVED" else None
                ),
                "message": message,
                "automatic": True,
            }
            self.flow.save(con, app)
            return self.flow.public(app)

    def reserve(self, application_id, actor, day, key, move=False):
        with self.repository.connect(write=True) as con:
            fingerprint, previous = self.idempotent(
                con,
                actor,
                key,
                {
                    "id": application_id,
                    "day": day,
                    "operation": "move" if move else "reserve",
                },
            )
            app = self.flow.get(con, application_id)
            self.flow.authorize(con, app, actor)
            if previous:
                return previous
            if app["state"] not in (
                ["MANUAL_SCHEDULED"] if move else ["MANUAL_PENDING", "MANUAL_SCHEDULED"]
            ):
                raise HTTPException(
                    409, "Permohonan tidak dapat dijadwalkan pada status ini."
                )
            config = self.flow.settings(con)
            self.validate_day(day, config)
            existing = con.execute(
                "SELECT * FROM manual_cases WHERE application_id=?", (application_id,)
            ).fetchone()
            active = existing and existing["state"] != "CANCELLED"
            if active and not move:
                if existing["day"] != day:
                    raise HTTPException(
                        409, "Sudah memiliki reservasi. Gunakan pemindahan jadwal."
                    )
                response = self.flow.public(app)
                self.record_idempotent(con, actor, key, fingerprint, response)
                return response
            used = self.used(con, day) - (1 if active and existing["day"] == day else 0)
            if used >= config["daily_capacity"]:
                raise HTTPException(
                    409,
                    {
                        "code": "CAPACITY_FULL",
                        "message": "Slot habis saat dipilih. Silakan pilih tanggal lain.",
                    },
                )
            if not app["payload"].get("evidence") or any(
                e["expires"] <= time.time() for e in app["payload"]["evidence"]
            ):
                raise HTTPException(
                    410, "Bukti sudah kedaluwarsa. Ambil ulang sebelum menjadwalkan."
                )
            # Retention must cover the appointment; do not silently retain longer.
            at = datetime.fromisoformat(day + "T" + config["opens"]).replace(
                tzinfo=JAKARTA
            )
            if min(e["expires"] for e in app["payload"]["evidence"]) <= at.timestamp():
                raise HTTPException(
                    410,
                    "Jadwal melewati retensi bukti. Pilih tanggal lebih dekat atau ambil bukti baru.",
                )
            case_id = (
                existing["id"] if existing else "CASE-" + uuid.uuid4().hex[:12].upper()
            )
            con.execute(
                "INSERT INTO manual_cases VALUES (?,?,?,?,?,?,?) ON CONFLICT(application_id) DO UPDATE SET day=excluded.day,revision=excluded.revision,state=excluded.state,assigned_to=NULL,payload=excluded.payload",
                (
                    case_id,
                    application_id,
                    day,
                    app["revision"],
                    "SCHEDULED",
                    None,
                    json.dumps(
                        {"created": utcnow(), "reason": app["payload"].get("reason")}
                    ),
                ),
            )
            if app["state"] == "MANUAL_PENDING":
                self.flow.transition(app, "MANUAL_SCHEDULED")
            app["payload"]["reservation"] = {
                "case_id": case_id,
                "day": day,
                "timezone": "Asia/Jakarta",
                "window": config["opens"] + "–" + config["closes"],
                "state": "SCHEDULED",
            }
            self.flow.save(con, app)
            response = self.flow.public(app)
            self.record_idempotent(con, actor, key, fingerprint, response)
        self.repository.audit(
            "Reservasi manual", "Slot " + day + "; actor " + actor["id"], application_id
        )
        return response

    def cancel(self, application_id, actor, key):
        with self.repository.connect(write=True) as con:
            fingerprint, previous = self.idempotent(
                con, actor, key, {"id": application_id, "operation": "cancel"}
            )
            app = self.flow.get(con, application_id)
            self.flow.authorize(con, app, actor)
            if previous:
                return previous
            if app["state"] != "MANUAL_SCHEDULED":
                raise HTTPException(
                    409, "Reservasi tidak dapat dibatalkan pada status ini."
                )
            con.execute(
                "UPDATE manual_cases SET state='CANCELLED' WHERE application_id=?",
                (application_id,),
            )
            self.flow.transition(app, "MANUAL_PENDING")
            app["payload"]["reservation"] = None
            app["payload"]["manual_admission_generation"] = (
                app["payload"].get("manual_admission_generation", 0) + 1
            )
            app["payload"]["manual_admission"] = None
            self.flow.save(con, app)
            response = self.flow.public(app)
            self.record_idempotent(con, actor, key, fingerprint, response)
        self.repository.audit(
            "Reservasi dibatalkan",
            "Kapasitas dikembalikan; actor " + actor["id"],
            application_id,
        )
        return response

    def start(self, application_id, actor):
        if actor["role"] != "helpdesk":
            raise HTTPException(403, "Hanya helpdesk dapat memulai pemeriksaan.")
        with self.repository.connect(write=True) as con:
            app = self.flow.get(con, application_id)
            self.flow.authorize(con, app, actor, operator=True)
            case = con.execute(
                "SELECT * FROM manual_cases WHERE application_id=?", (application_id,)
            ).fetchone()
            if (
                not case
                or app["state"] != "MANUAL_SCHEDULED"
                or case["revision"] != app["revision"]
            ):
                raise HTTPException(409, "Kasus belum terjadwal atau bukti berubah.")
            now = self.clock()
            config = self.flow.settings(con)
            if (
                case["day"] != now.date().isoformat()
                or not self.day_open(now.date(), config)
                or not config["opens"] <= now.strftime("%H:%M") < config["closes"]
            ):
                raise HTTPException(
                    409, "Pemeriksaan dimulai pada hari dan jam layanan yang dipesan."
                )
            con.execute(
                "UPDATE manual_cases SET state='IN_REVIEW',assigned_to=? WHERE application_id=?",
                (actor["id"], application_id),
            )
            self.flow.transition(app, "MANUAL_IN_REVIEW")
            app["payload"]["reservation"]["state"] = "IN_REVIEW"
            self.flow.save(con, app)
        self.repository.audit(
            "Pemeriksaan manual dimulai", "Actor " + actor["id"], application_id
        )
        return self.flow.public(app, True)

    def review(
        self,
        application_id,
        actor,
        decision,
        revision,
        note,
        identity_review,
        authority_review,
    ):
        if actor["role"] != "helpdesk":
            raise HTTPException(403, "Keputusan dibuat oleh helpdesk berwenang.")
        with self.repository.connect(write=True) as con:
            app = self.flow.get(con, application_id)
            self.flow.authorize(con, app, actor, operator=True)
            case = con.execute(
                "SELECT * FROM manual_cases WHERE application_id=?", (application_id,)
            ).fetchone()
            if (
                app["state"] != "MANUAL_IN_REVIEW"
                or not case
                or case["assigned_to"] != actor["id"]
                or revision != app["revision"]
                or case["revision"] != revision
            ):
                raise HTTPException(
                    409, "Kasus/versi bukti tidak sesuai dengan pemeriksaan petugas."
                )
            for evidence in app["payload"]["evidence"]:
                self.flow.evidence.read(con, evidence["id"])
            if decision == "approve":
                mandatory = app["payload"]["routing"]["mandatory"]
                if (
                    not mandatory["session_nonce_proof"]
                    or not mandatory["no_security_rejection"]
                    or not mandatory["document_identity_complete"]
                ):
                    raise HTTPException(
                        409,
                        "Bukti sesi/identitas wajib perlu diperbaiki; tidak dapat ditutupi keputusan manual.",
                    )
                if not identity_review or not authority_review:
                    raise HTTPException(
                        422, "Dasar pemeriksaan identitas dan kewenangan harus dicatat."
                    )
                app["payload"]["authority_verified"] = bool(
                    authority_review
                    and app["payload"]["authority_attested"]
                    and (
                        self.flow.policy.mode == "demo"
                        or app["payload"].get("authority_verified")
                    )
                )
                if not app["payload"]["authority_verified"]:
                    raise HTTPException(
                        409, "Pernyataan kewenangan pemohon belum tersedia."
                    )
                app["payload"]["identity_assessment"] = {
                    "procedure": "manual_document_review",
                    "reviewer_id": actor["id"],
                    "local_review": True,
                    "official": app["payload"]["identity_verified"],
                }
                if self.flow.policy.mode != "demo" and not all(mandatory.values()):
                    raise HTTPException(
                        409,
                        "Pemeriksaan wajib produksi belum terpenuhi. Perbaiki bukti/prosedur berwenang terlebih dahulu.",
                    )
                if (
                    self.flow.policy.mode != "demo"
                    and not app["payload"]["identity_verified"]
                ):
                    raise HTTPException(
                        409,
                        "Sumber identitas resmi belum terverifikasi; keputusan produksi ditahan.",
                    )
                self.flow.transition(app, "MANUAL_APPROVED")
                self.flow.approval(app, "manual", actor)
            elif decision == "reject":
                self.flow.transition(app, "MANUAL_REJECTED")
            elif decision == "repair":
                self.flow.transition(app, "CAPTURE_RETRY")
                app["payload"]["retry"] = {
                    "stage": "document",
                    "label": "Perbaiki bukti sesuai catatan petugas",
                    "reason": note,
                }
            else:
                raise HTTPException(422, "Keputusan tidak valid.")
            meta = self.flow.evidence.json(
                con,
                app,
                "manual-review",
                {
                    "note": note,
                    "actor": actor["id"],
                    "login": actor["login"],
                    "decision": decision,
                    "revision": revision,
                },
                self.flow.settings(con)["retention_days"],
                app["payload"]["routing"]["policy_version"],
            )
            app["payload"]["evidence"].append(meta)
            app["payload"]["review"] = {
                "actor": actor["id"],
                "login": actor["login"],
                "note_evidence": meta["id"],
                "at": utcnow(),
                "revision": revision,
            }
            if decision == "repair":
                app["payload"][
                    "reason"
                ] = "Perbaiki bukti sesuai catatan helpdesk. Catatan dapat dibuka pada permohonan ini."
            con.execute(
                "UPDATE manual_cases SET state='COMPLETED' WHERE application_id=?",
                (application_id,),
            )
            app["payload"]["reservation"]["state"] = "COMPLETED"
            self.flow.save(con, app)
        self.repository.audit(
            "Keputusan manual",
            decision + "; actor " + actor["id"] + "; revision " + str(revision),
            application_id,
        )
        return self.flow.public(app, True)
