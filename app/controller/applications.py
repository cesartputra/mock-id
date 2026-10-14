"""Authorized applicant, helpdesk, administrator and host integration API."""

import json
from datetime import date
from fastapi import APIRouter, Request, HTTPException, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field, model_validator
from app.services.auth import actor, roles
from app.services.workflow import JAKARTA
from app.services.slik_pdf import SlikPdfService
from app.services.imaging import CaptureError
from app.services.pipeline import ModelUnavailable

router = APIRouter(prefix="/api")


class Attestation(BaseModel):
    accepted: bool


class DemoRecheck(BaseModel):
    capture_revision: int = Field(ge=0, strict=True)


class CleanupRequest(BaseModel):
    mode: str = Field(pattern="^(photos|full)$")
    capture_revision: int = Field(ge=0, strict=True)
    expected_updated_at: str = Field(min_length=10, max_length=80)
    confirm_application_id: str = Field(min_length=5, max_length=80)


class Booking(BaseModel):
    day: str


class Decision(BaseModel):
    decision: str = Field(pattern="^(approve|reject|repair)$")
    capture_revision: int = Field(ge=0)
    note: str = Field(min_length=10, max_length=1000)
    identity_review: bool = False
    authority_review: bool = False


class CapacityConfig(BaseModel):
    timezone: str = Field(pattern="^Asia/Jakarta$")
    workdays: list[int] = Field(min_length=1, max_length=7)
    opens: str = Field(pattern="^([01][0-9]|2[0-3]):[0-5][0-9]$")
    closes: str = Field(pattern="^([01][0-9]|2[0-3]):[0-5][0-9]$")
    daily_capacity: int = Field(ge=1, le=1000)
    holidays: list[str] = Field(max_length=366)
    booking_horizon_days: int = Field(ge=1, le=90)
    decision_ttl_hours: int = Field(ge=1, le=168)
    retention_days: int = Field(ge=1, le=90)
    label: str = Field(min_length=5, max_length=100)

    @model_validator(mode="after")
    def validate(self):
        if (
            self.opens >= self.closes
            or any(d not in range(7) for d in self.workdays)
            or len(set(self.workdays)) != len(self.workdays)
        ):
            raise ValueError("Jam/hari kerja tidak valid.")
        for holiday in self.holidays:
            date.fromisoformat(holiday)
        return self


class Handoff(BaseModel):
    application_id: str
    subject_id: str = Field(min_length=64, max_length=64)
    owner_id: str


@router.get("/applications")
def listing(request: Request):
    who = actor(request)
    flow = request.app.state.workflow
    with flow.repository.connect() as con:
        if who["role"] == "admin":
            rows = con.execute(
                "SELECT id FROM applications ORDER BY created DESC LIMIT 500"
            ).fetchall()
        elif who["role"] == "helpdesk":
            rows = con.execute(
                "SELECT a.id FROM applications a JOIN manual_cases c ON a.id=c.application_id WHERE c.state!='CANCELLED' AND (c.assigned_to IS NULL OR c.assigned_to=?) ORDER BY a.created DESC LIMIT 500",
                (who["id"],),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT id FROM applications WHERE owner_id=? ORDER BY created DESC LIMIT 500",
                (who["id"],),
            ).fetchall()
        return [
            flow.public(flow.get(con, row["id"]), who["role"] in ["admin", "helpdesk"])
            for row in rows
        ]


@router.get("/applications/{application_id}")
def status(application_id: str, request: Request):
    return request.app.state.workflow.snapshot(application_id, actor(request))


@router.get("/operator/applications/{application_id}/cleanup")
def cleanup_plan(application_id: str, request: Request):
    return request.app.state.operator_data.plan(application_id, roles(request, "admin"))


@router.post("/operator/applications/{application_id}/cleanup")
def cleanup(application_id: str, body: CleanupRequest, request: Request):
    return request.app.state.operator_data.clean(application_id, roles(request, "admin"), body.mode,
                                                body.capture_revision, body.expected_updated_at, body.confirm_application_id)


@router.post("/applications/{application_id}/document-crop")
async def stored_document_crop(application_id: str, request: Request):
    who = roles(request, "admin", "helpdesk")
    service = request.app.state.operator_data
    existing, source = service.crop_source(application_id, who)
    if existing:
        return existing
    revision, metadata, image, nik = source
    try:
        reading = await request.app.state.inference_queue.run(request.app.state.verifier.document, image)
    except CaptureError as exc:
        raise HTTPException(422, str(exc)) from exc
    except ModelUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    return service.save_crop(application_id, who, revision, metadata, image, reading, nik)


@router.post("/applications/{application_id}/demo/recheck")
def recheck_demo(application_id: str, body: DemoRecheck, request: Request):
    who = actor(request)
    outcome = request.app.state.workflow.recheck_demo_policy(application_id, who, body.capture_revision)
    if outcome["state"] == "AUTO_APPROVED":
        outcome = request.app.state.slik.issue(application_id, who)
    return outcome


@router.post("/applications/{application_id}/attest")
def attest(application_id: str, body: Attestation, request: Request):
    return request.app.state.workflow.attest(
        application_id, actor(request), body.accepted
    )


@router.get("/manual/calendar")
def calendar(request: Request):
    return request.app.state.manual.calendar()


@router.post("/applications/{application_id}/manual/try-today")
def try_today(application_id: str, request: Request):
    return request.app.state.manual.admit_today(application_id, actor(request))


@router.post("/applications/{application_id}/manual/reserve")
def reserve(
    application_id: str,
    body: Booking,
    request: Request,
    idempotency_key: str = Header(alias="Idempotency-Key"),
):
    if actor(request).get("guest"):
        return request.app.state.manual.admit_today(application_id, actor(request))
    return request.app.state.manual.reserve(
        application_id, actor(request), body.day, idempotency_key
    )


@router.post("/applications/{application_id}/manual/move")
def move(
    application_id: str,
    body: Booking,
    request: Request,
    idempotency_key: str = Header(alias="Idempotency-Key"),
):
    if actor(request).get("guest"):
        raise HTTPException(403, "Pemohon menggunakan kuota hari ini secara otomatis.")
    return request.app.state.manual.reserve(
        application_id, actor(request), body.day, idempotency_key, True
    )


@router.post("/applications/{application_id}/manual/cancel")
def cancel(
    application_id: str,
    request: Request,
    idempotency_key: str = Header(alias="Idempotency-Key"),
):
    return request.app.state.manual.cancel(
        application_id, actor(request), idempotency_key
    )


@router.post("/applications/{application_id}/manual/start")
def start(application_id: str, request: Request):
    return request.app.state.manual.start(application_id, roles(request, "helpdesk"))


@router.post("/applications/{application_id}/manual/review")
def review(application_id: str, body: Decision, request: Request):
    who = roles(request, "helpdesk")
    outcome = request.app.state.manual.review(
        application_id,
        who,
        body.decision,
        body.capture_revision,
        body.note.strip(),
        body.identity_review,
        body.authority_review,
    )
    if outcome["state"] == "MANUAL_APPROVED":
        outcome = request.app.state.slik.issue(application_id, who)
    return outcome


@router.post("/applications/{application_id}/slik")
def issue(application_id: str, request: Request):
    return request.app.state.slik.issue(application_id, actor(request))


@router.get("/applications/{application_id}/slik")
def report(application_id: str, request: Request):
    return request.app.state.slik.report(application_id, actor(request))


@router.get("/applications/{application_id}/slik.pdf")
def download_report(application_id: str, request: Request):
    who = actor(request)
    request.app.state.auth.limit("pdf-download:" + who["id"], 30, 3600)
    slik = request.app.state.slik
    result = slik.report(application_id, who)
    content = SlikPdfService().render(result)
    # Rendering must not publish a decision revoked or expired meanwhile.
    with slik.repository.connect() as con:
        current = slik.flow.get(con, application_id)
        slik.authorize(con, current, who)
        if (
            current["revision"] != result["revision"]
            or current["state"] != "SLIK_READY"
        ):
            raise HTTPException(409, "Keputusan berubah. PDF lama tidak dapat diunduh.")
    slik.repository.audit(
        "PDF SLIK demo diunduh",
        "Actor " + who["id"] + "; revision " + str(result["revision"]),
        application_id,
    )
    import re

    filename = "slik-demo-" + re.sub(r"[^A-Za-z0-9-]", "", current["id"]) + ".pdf"
    return Response(
        content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'attachment; filename="' + filename + '"',
            "Cache-Control": "no-store",
        },
    )


@router.post("/integration/handoff")
def handoff(body: Handoff, request: Request):
    who = roles(request, "integration")
    flow = request.app.state.workflow
    with flow.repository.connect() as con:
        app = flow.get(con, body.application_id)
        if app["owner_id"] != body.owner_id:
            raise HTTPException(409, "Pemilik handoff tidak sesuai permohonan.")
    return request.app.state.slik.issue(body.application_id, who, body.subject_id)


@router.get("/integration/applications/{application_id}/decision")
def integration_decision(application_id: str, owner_id: str, request: Request):
    who = roles(request, "integration")
    flow = request.app.state.workflow
    with flow.repository.connect() as con:
        app = flow.get(con, application_id)
        if app["owner_id"] != owner_id:
            raise HTTPException(404, "Permohonan tidak ditemukan.")
        data = {
            "application_id": app["id"],
            "owner_id": app["owner_id"],
            "subject_id": app["subject_id"],
            "capture_revision": app["revision"],
            "state": app["state"],
            "decision": app["payload"].get("decision"),
            "channel": "authenticated_dashboard",
            "identity_verified": app["payload"].get("identity_verified", False),
        }
    flow.repository.audit(
        "Keputusan handoff dilihat", "Service actor " + who["id"], application_id
    )
    return data


@router.get("/evidence/{evidence_id}")
def evidence(evidence_id: str, request: Request):
    who = roles(request, "helpdesk", "admin", "applicant")
    flow = request.app.state.workflow
    with flow.repository.connect() as con:
        row = con.execute(
            "SELECT application_id FROM evidence WHERE id=?", (evidence_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "Bukti tidak ditemukan.")
        app = flow.get(con, row["application_id"])
        flow.authorize(con, app, who, operator=True)
        if evidence_id not in [e["id"] for e in app["payload"].get("evidence", [])]:
            raise HTTPException(409, "Bukti bukan versi yang sedang diperiksa.")
        content, meta = flow.evidence.read(con, evidence_id)
        if who["role"] == "applicant" and meta["kind"] == "verification":
            raise HTTPException(
                403,
                "Metrik mentah dan diagnostik hanya tersedia untuk operator berwenang.",
            )
    flow.repository.audit(
        "Bukti dilihat", "Actor " + who["id"] + "; evidence " + evidence_id, app["id"]
    )
    return Response(
        content,
        media_type=(
            "application/json"
            if meta["kind"] in ["identity", "verification", "manual-review"]
            else "image/jpeg"
        ),
        headers={"Cache-Control": "no-store", "Content-Disposition": "inline"},
    )


@router.get("/policy/capacity")
def capacity(request: Request):
    roles(request, "admin")
    return request.app.state.workflow.settings()


@router.put("/policy/capacity")
def set_capacity(body: CapacityConfig, request: Request):
    who = roles(request, "admin")
    flow = request.app.state.workflow
    with flow.repository.connect(write=True) as con:
        con.execute(
            "UPDATE flow_settings SET payload=? WHERE id=1", (body.model_dump_json(),)
        )
    flow.repository.audit("Kebijakan kapasitas diperbarui", "Actor " + who["id"])
    return body


@router.get("/operator/metrics")
def metrics(request: Request):
    roles(request, "admin")
    flow = request.app.state.workflow
    with flow.repository.connect() as con:
        volume = {
            r["state"]: r["n"]
            for r in con.execute(
                "SELECT state,COUNT(*) AS n FROM applications GROUP BY state"
            ).fetchall()
        }
        routing_volume = {}
        for row in con.execute("SELECT id FROM applications").fetchall():
            application = flow.get(con, row["id"])
            route = (application["payload"].get("routing") or {}).get("decision")
            if route:
                routing_volume[route] = routing_volume.get(route, 0) + 1
        records = flow.repository.results()
        durations = [r["duration_ms"] for r in records if "duration_ms" in r]
        retries = sum(max(0, r.get("attempt", 1) - 1) for r in records)
        cases = con.execute(
            "SELECT a.created,c.state FROM applications a JOIN manual_cases c ON a.id=c.application_id WHERE c.state IN ('SCHEDULED','IN_REVIEW')"
        ).fetchall()
    from datetime import datetime
    import time

    wait = [
        max(0, time.time() - datetime.fromisoformat(r["created"]).timestamp())
        for r in cases
    ]
    return {
        "volume": volume,
        "routing_volume": routing_volume,
        "retry_observations": retries,
        "verification_latency_ms_mean": (
            sum(durations) / len(durations) if durations else None
        ),
        "waiting_cases": len(cases),
        "wait_seconds_mean": sum(wait) / len(wait) if wait else None,
        "technical_results": sum(r.get("status") == "technical" for r in records),
        "runtime": request.app.state.verifier.availability(),
        "scope": "Observed local verification records; retry count may include repeated observations, not unique people.",
    }
