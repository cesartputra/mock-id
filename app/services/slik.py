"""Host backend authorizes issuance; inference workers never access SLIK."""

import json
import os
import time
import uuid
from fastapi import HTTPException

DEMO_MARKER = "DEMO — BUKAN INFORMASI DEBITUR RESMI"


class SlikServiceAdapter:
    def fetch(self, identity, idempotency_key):
        raise NotImplementedError


class MockSlikAdapter(SlikServiceAdapter):
    def fetch(self, identity, idempotency_key):
        # All financial values and names below are fixed synthetic demonstration
        # data, never claims about the verified person's financial history.
        facilities = [
            {
                "creditor": "BANK CONTOH DEMO",
                "branch": "CABANG DEMO JAKARTA",
                "account": "DEMO-REK-001",
                "limit": 10000000,
                "outstanding": 2500000,
                "collectibility": "1 - Lancar",
                "quality": 1,
                "type": "Kredit konsumsi",
                "usage": "Konsumsi",
                "contract": "DEMO-AKAD-001",
                "started": "2025-01-01",
                "maturity": "2027-01-01",
                "interest_percent": 10.0,
                "principal_arrears": 0,
                "interest_arrears": 0,
                "arrears_days": 0,
                "condition": "Aktif",
                "updated": "2026-09-30",
                "history": [
                    {
                        "month": f"2025-{m:02d}" if m >= 10 else f"2026-{m:02d}",
                        "quality": 1,
                        "arrears_days": 0,
                    }
                    for m in [10, 11, 12, 1, 2, 3, 4, 5, 6, 7, 8, 9]
                ],
                "collateral": [
                    {
                        "type": "Kendaraan contoh",
                        "reference": "DEMO-AGN-001",
                        "value": 5000000,
                        "owner": "DEBITUR SINTETIS",
                        "valuation_date": "2026-09-30",
                        "shared": False,
                    }
                ],
                "guarantors": [],
            },
            {
                "creditor": "LEMBAGA PEMBIAYAAN CONTOH",
                "branch": "CABANG DEMO",
                "account": "DEMO-REK-002",
                "limit": 20000000,
                "outstanding": 8000000,
                "collectibility": "1 - Lancar",
                "quality": 1,
                "type": "Pembiayaan konsumsi",
                "usage": "Konsumsi",
                "contract": "DEMO-AKAD-002",
                "started": "2025-06-01",
                "maturity": "2028-06-01",
                "interest_percent": 8.0,
                "principal_arrears": 0,
                "interest_arrears": 0,
                "arrears_days": 0,
                "condition": "Aktif",
                "updated": "2026-09-30",
                "history": [
                    {
                        "month": f"2025-{m:02d}" if m >= 10 else f"2026-{m:02d}",
                        "quality": 2 if m == 7 else 1,
                        "arrears_days": 30 if m == 7 else 0,
                    }
                    for m in [10, 11, 12, 1, 2, 3, 4, 5, 6, 7, 8, 9]
                ],
                "collateral": [],
                "guarantors": [
                    {
                        "name": "PENJAMIN SINTETIS",
                        "identity": "DEMO-PENJAMIN-001",
                        "type": "Perseorangan contoh",
                        "updated": "2026-09-30",
                    }
                ],
            },
        ]
        return {
            "label": DEMO_MARKER,
            "synthetic": True,
            "schema_version": "slik-demo-v2",
            "reference": idempotency_key,
            "subject_name": "DEBITUR SINTETIS",
            "subject_nik": "0000000000000000",
            "search": {
                "identity_type": "NIK",
                "identity": "0000000000000000",
                "last_position": "September 2026",
                "requested_at": __import__("datetime")
                .datetime.now(__import__("datetime").timezone.utc)
                .isoformat(),
            },
            "debtor": {
                "type": "Perseorangan",
                "name": "DEBITUR SINTETIS",
                "nik": "0000000000000000",
                "birth": "1990-01-01",
                "birthplace": "KOTA CONTOH",
                "address": "JALAN DEMO NOMOR 1, KOTA CONTOH",
                "occupation": "PEKERJA CONTOH",
                "reporters": [f["creditor"] for f in facilities],
            },
            "summary": {
                "total_limit": sum(f["limit"] for f in facilities),
                "total_outstanding": sum(f["outstanding"] for f in facilities),
                "creditors": len(facilities),
                "worst_quality": 2,
                "worst_month": "2026-07",
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
        with self.repository.connect() as con:
            app = self.flow.get(con, application_id)
            self.flow.authorize(con, app, actor)
            self.authorize(con, app, actor)
            row = con.execute(
                "SELECT * FROM issuance WHERE application_id=? AND revision=? AND state='READY'",
                (application_id, app["revision"]),
            ).fetchone()
            if app["state"] != "SLIK_READY" or not row:
                raise HTTPException(409, "Hasil SLIK belum tersedia.")
            result = self.flow.box.open_json(row["report_ciphertext"], row["id"])
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
