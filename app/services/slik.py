"""Host backend authorizes issuance; inference workers never access SLIK."""

import json
import os
import time
import uuid
import random
import hashlib
import re
from datetime import datetime, timezone
from fastapi import HTTPException

DEMO_MARKER = "DEMO — BUKAN INFORMASI DEBITUR RESMI"


class SlikServiceAdapter:
    def fetch(self, identity, idempotency_key):
        raise NotImplementedError


class MockSlikAdapter(SlikServiceAdapter):
    def fetch(self, identity, idempotency_key):
        # Identity comes from authorized server evidence. Only financial demo
        # data is pseudorandom, stable for the same downstream issuance ID.
        if (
            not identity.get("name")
            or not re.fullmatch(r"[0-9]{16}", identity.get("nik", ""))
            or not identity.get("birth")
        ):
            raise ValueError("Identitas server lengkap diperlukan untuk laporan demo.")
        rng = random.Random(
            int.from_bytes(
                hashlib.sha256(
                    ("synthetic-credit-v3:" + idempotency_key).encode()
                ).digest(),
                "big",
            )
        )
        labels = {
            1: "Lancar",
            2: "Dalam Perhatian Khusus",
            3: "Kurang Lancar",
            4: "Diragukan",
            5: "Macet",
        }
        creditors = rng.sample(
            [
                "BANK DEMO NUSANTARA",
                "BANK DEMO SENTOSA",
                "BANK DEMO SEJAHTERA",
                "PEMBIAYAAN DEMO MAKMUR",
            ],
            rng.randint(1, 3),
        )
        facilities = []
        for i, creditor in enumerate(creditors, 1):
            limit = rng.randrange(10, 201) * 500000
            outstanding = rng.randrange(0, int(limit / 100000) + 1) * 100000
            history = []
            for month in [
                "2025-10",
                "2025-11",
                "2025-12",
                "2026-01",
                "2026-02",
                "2026-03",
                "2026-04",
                "2026-05",
                "2026-06",
                "2026-07",
                "2026-08",
                "2026-09",
            ]:
                quality = rng.choices([1, 2, 3, 4, 5], weights=[75, 15, 5, 3, 2])[0]
                ranges = {
                    1: (0, 0),
                    2: (1, 90),
                    3: (91, 120),
                    4: (121, 180),
                    5: (181, 240),
                }
                history.append(
                    {
                        "month": month,
                        "quality": quality,
                        "arrears_days": rng.randint(*ranges[quality]),
                    }
                )
            quality = history[-1]["quality"] if outstanding else 1
            if not outstanding:
                history[-1].update(quality=1, arrears_days=0)
            facilities.append(
                {
                    "creditor": creditor,
                    "branch": "CABANG DEMO",
                    "account": f"DEMO-REK-{rng.randrange(100000,999999)}",
                    "contract": f"DEMO-AKAD-{rng.randrange(100000,999999)}",
                    "limit": limit,
                    "outstanding": outstanding,
                    "quality": quality,
                    "collectibility": f"{quality} - {labels[quality]}",
                    "type": rng.choice(
                        [
                            "Kredit konsumsi",
                            "Kredit modal kerja",
                            "Pembiayaan kendaraan",
                        ]
                    ),
                    "usage": "Contoh pembiayaan sintetis",
                    "started": f"2024-{rng.randint(1,12):02d}-01",
                    "maturity": f"2028-{rng.randint(1,12):02d}-01",
                    "interest_percent": round(rng.uniform(6, 18), 1),
                    "principal_arrears": (
                        min(outstanding, rng.randint(1, 5) * 100000)
                        if quality > 1
                        else 0
                    ),
                    "interest_arrears": (
                        rng.randint(1, 10) * 10000 if quality > 1 else 0
                    ),
                    "arrears_days": history[-1]["arrears_days"],
                    "condition": "Aktif" if outstanding else "Lunas",
                    "updated": "2026-09-30",
                    "history": history,
                    "collateral": [],
                    "guarantors": [],
                }
            )
        worst = max(
            (h for f in facilities for h in f["history"]),
            key=lambda h: (h["quality"], h["month"]),
        )
        return {
            "label": DEMO_MARKER,
            "synthetic": True,
            "financial_data_synthetic": True,
            "identity_source": "authorized_server_capture",
            "schema_version": "slik-demo-v3",
            "reference": idempotency_key,
            "subject_name": identity["name"],
            "subject_nik": identity["nik"],
            "search": {
                "identity_type": "NIK",
                "identity": identity["nik"],
                "last_position": "September 2026 (data keuangan contoh)",
                "requested_at": datetime.now(timezone.utc).isoformat(),
            },
            "debtor": {
                "type": "Perseorangan",
                "name": identity["name"],
                "nik": identity["nik"],
                "birth": identity["birth"],
                "birthplace": identity.get("birthplace", "-"),
                "address": identity.get("address") or "-",
                "occupation": identity.get("occupation", "-"),
                "reporters": creditors,
            },
            "summary": {
                "total_limit": sum(f["limit"] for f in facilities),
                "total_outstanding": sum(f["outstanding"] for f in facilities),
                "creditors": len(facilities),
                "worst_quality": worst["quality"],
                "worst_month": worst["month"],
                "currency": "IDR",
            },
            "facilities": facilities,
        }


class OfficialSlikAdapter(SlikServiceAdapter):
    def fetch(self, identity, idempotency_key):
        raise RuntimeError(
            "Adapter SLIK resmi belum dikonfigurasi. Tidak ada layanan resmi yang dipanggil."
        )


class SlikService:
    def __init__(self, workflow, adapter=None):
        self.flow = workflow
        self.repository = workflow.repository
        self.adapter = adapter or (
            MockSlikAdapter()
            if workflow.policy.mode == "demo"
            else OfficialSlikAdapter()
        )

    def authorize(self, con, app, actor, expected_subject=None):
        p = app["payload"]
        d = p.get("decision")
        if actor["role"] == "integration":
            if not expected_subject or expected_subject != app["subject_id"]:
                raise HTTPException(
                    409, "Subjek handoff tidak sesuai keputusan server."
                )
        elif (
            actor["role"] == "helpdesk"
            and d
            and d.get("kind") == "manual"
            and d.get("reviewer_id") == actor["id"]
        ):
            case = con.execute(
                "SELECT assigned_to,state,revision FROM manual_cases WHERE application_id=?",
                (app["id"],),
            ).fetchone()
            if (
                not case
                or case["assigned_to"] != actor["id"]
                or case["state"] != "COMPLETED"
                or case["revision"] != app["revision"]
            ):
                raise HTTPException(
                    403,
                    "Penerbitan membutuhkan kasus yang sudah diputuskan oleh petugas ini.",
                )
        else:
            self.flow.authorize(con, app, actor)
        owner = con.execute(
            "SELECT enabled FROM principals WHERE id=?", (app["owner_id"],)
        ).fetchone()
        if not owner or not owner["enabled"]:
            raise HTTPException(403, "Kanal dashboard akun pemohon tidak aktif.")
        if (
            not d
            or d["revision"] != app["revision"]
            or d["subject_id"] != app["subject_id"]
            or d["expires"] <= time.time()
        ):
            raise HTTPException(
                409, "Keputusan belum sah, kedaluwarsa, atau telah dibatalkan."
            )
        if app["state"] not in [
            "AUTO_APPROVED",
            "MANUAL_APPROVED",
            "SLIK_PENDING",
            "SLIK_READY",
        ]:
            raise HTTPException(409, "Keputusan tidak mengizinkan penerbitan hasil.")
        if not d["authority_verified"] or not p.get("authority_attested"):
            raise HTTPException(403, "Kewenangan pemohon belum terpenuhi.")
        if self.flow.policy.mode != "demo" and (
            not d["identity_verified"] or not all(p["routing"]["mandatory"].values())
        ):
            raise HTTPException(
                409, "Pemeriksaan wajib/sumber identitas produksi belum terpenuhi."
            )
        # The channel is an authenticated dashboard bound to the owner account,
        # not a browser-supplied email address. No email delivery is performed.
        for evidence in p.get("evidence", []):
            if evidence["expires"] <= time.time():
                raise HTTPException(410, "Bukti keputusan telah kedaluwarsa.")
        identity = self.flow.identity(con, app)
        if self.flow.box.subject(identity["nik"]) != app["subject_id"]:
            raise HTTPException(409, "Identitas server dan keputusan tidak sesuai.")
        return identity

    def issue(self, application_id, actor, expected_subject=None):
        # Reserve a stable issuance ID before calling downstream. The adapter
        # must honor this ID on retries, including ambiguous network failures.
        with self.repository.connect(write=True) as con:
            app = self.flow.get(con, application_id)
            identity = self.authorize(con, app, actor, expected_subject)
            row = con.execute(
                "SELECT * FROM issuance WHERE application_id=? AND revision=?",
                (application_id, app["revision"]),
            ).fetchone()
            if row and row["state"] == "READY":
                return self.flow.public(app)
            if row and row["state"] == "IN_FLIGHT" and row["lease_until"] > time.time():
                return self.flow.public(app)
            issue_id = row["id"] if row else "SLIK-" + uuid.uuid4().hex
            lease_token = uuid.uuid4().hex
            if not row:
                con.execute(
                    "INSERT INTO issuance (id,application_id,revision,state,report_ciphertext,lease_until,lease_token) VALUES (?,?,?,?,?,?,?)",
                    (
                        issue_id,
                        application_id,
                        app["revision"],
                        "IN_FLIGHT",
                        None,
                        time.time() + 60,
                        lease_token,
                    ),
                )
            else:
                con.execute(
                    "UPDATE issuance SET state='IN_FLIGHT',lease_until=?,lease_token=? WHERE id=?",
                    (time.time() + 60, lease_token, issue_id),
                )
            if app["state"] != "SLIK_PENDING":
                self.flow.transition(app, "SLIK_PENDING")
            app["payload"]["slik"] = {
                "id": issue_id,
                "state": "SLIK_PENDING",
                "label": (
                    DEMO_MARKER
                    if self.flow.policy.mode == "demo"
                    else "Penerbitan ditahan sampai layanan berwenang tersedia"
                ),
            }
            self.flow.save(con, app)
            revision = app["revision"]
        try:
            report = self.adapter.fetch(identity, issue_id)
            if self.flow.policy.mode == "demo" and (
                not report.get("synthetic") or report.get("label") != DEMO_MARKER
            ):
                raise RuntimeError(
                    "Adapter demo harus mengembalikan laporan sintetis bertanda."
                )
            if self.flow.policy.mode == "demo" and (
                report.get("subject_name") != identity["name"]
                or report.get("subject_nik") != identity["nik"]
                or report.get("debtor", {}).get("birth") != identity["birth"]
            ):
                raise RuntimeError("Identitas laporan berbeda dari bukti server.")
        except Exception:
            with self.repository.connect(write=True) as con:
                con.execute(
                    "UPDATE issuance SET state='PENDING',lease_until=0 WHERE id=? AND state='IN_FLIGHT' AND lease_token=?",
                    (issue_id, lease_token),
                )
            self.repository.audit(
                "SLIK tertunda",
                "Downstream belum selesai; retry menggunakan issuance ID yang sama.",
                application_id,
            )
            return (
                self.flow.snapshot(application_id, actor)
                if actor["role"] != "integration"
                else {"id": application_id, "state": "SLIK_PENDING"}
            )
        with self.repository.connect(write=True) as con:
            app = self.flow.get(con, application_id)
            current = con.execute(
                "SELECT lease_token FROM issuance WHERE id=?", (issue_id,)
            ).fetchone()
            if current["lease_token"] != lease_token:
                return self.flow.public(app)
            if app["revision"] != revision or app["state"] != "SLIK_PENDING":
                con.execute(
                    "UPDATE issuance SET state='REVOKED' WHERE id=?", (issue_id,)
                )
                raise HTTPException(
                    409, "Bukti berubah saat penarikan data. Hasil tidak diterbitkan."
                )
            self.authorize(con, app, actor, expected_subject)
            sealed = self.flow.box.seal_json(
                {
                    "report": report,
                    "decision_subject_id": app["subject_id"],
                    "revision": revision,
                    "request_subject": {
                        "name": app["payload"]["name"],
                        "nik_masked": app["payload"]["nik_masked"],
                    },
                },
                issue_id,
            )
            con.execute(
                "UPDATE issuance SET state='READY',report_ciphertext=?,lease_until=0 WHERE id=?",
                (sealed, issue_id),
            )
            self.flow.transition(app, "SLIK_READY")
            app["payload"]["slik"]["state"] = "SLIK_READY"
            self.flow.save(con, app)
        self.repository.audit(
            "SLIK demo siap" if self.flow.policy.mode == "demo" else "SLIK siap",
            "Issuance " + issue_id,
            application_id,
        )
        return self.flow.public(app)

    def report(self, application_id, actor):
        with self.repository.connect(write=True) as con:
            app = self.flow.get(con, application_id)
            self.flow.authorize(con, app, actor)
            identity = self.authorize(con, app, actor)
            row = con.execute(
                "SELECT * FROM issuance WHERE application_id=? AND revision=? AND state='READY'",
                (application_id, app["revision"]),
            ).fetchone()
            if app["state"] != "SLIK_READY" or not row:
                raise HTTPException(409, "Hasil SLIK belum tersedia.")
            result = self.flow.box.open_json(row["report_ciphertext"], row["id"])
            if (
                self.flow.policy.mode == "demo"
                and result["report"].get("schema_version") != "slik-demo-v3"
            ):
                result["report"] = MockSlikAdapter().fetch(identity, row["id"])
                con.execute(
                    "UPDATE issuance SET report_ciphertext=? WHERE id=?",
                    (self.flow.box.seal_json(result, row["id"]), row["id"]),
                )
            if self.flow.policy.mode == "demo" and (
                result["report"]["subject_name"] != identity["name"]
                or result["report"]["subject_nik"] != identity["nik"]
                or result["report"]["debtor"]["birth"] != identity["birth"]
            ):
                raise HTTPException(
                    409, "Identitas laporan tidak sesuai bukti yang disetujui."
                )
        self.repository.audit(
            "Hasil SLIK dilihat", "Actor " + actor["id"], application_id
        )
        return result

    def recover_inflight(self):
        # Local single-process startup only. A distributed worker must use a
        # lease/outbox; never run this recovery independently on every instance.
        if self.repository.database.dialect == "sqlite":
            with self.repository.connect(write=True) as con:
                con.execute(
                    "UPDATE issuance SET state='PENDING',lease_until=0 WHERE state='IN_FLIGHT'"
                )
