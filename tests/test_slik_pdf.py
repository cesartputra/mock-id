"""Document/protocol fixtures verify PDF output and access, not KYC accuracy."""

from io import BytesIO
import time
import pytest
from pypdf import PdfReader
from app.services.slik import MockSlikAdapter
from app.services.slik_pdf import SlikPdfService
from test_workflow import prepare, account


def test_pdf_layout_marker_and_twelve_month_data():
    result = {
        "report": MockSlikAdapter().fetch(
            {
                "name": "PEMOHON & <CONTOH>",
                "nik": "0000000000000000",
                "birth": "1990-01-01",
            },
            "SLIK-PDF-FIXTURE",
        ),
        "request_subject": {
            "name": "PEMOHON & <CONTOH>",
            "nik_masked": "**** **** **** 3456",
        },
    }
    raw = SlikPdfService().render(result)
    pdf = PdfReader(BytesIO(raw))
    assert raw.startswith(b"%PDF-") and len(pdf.pages) == 1 + len(
        result["report"]["facilities"]
    )
    assert all(
        "DEMO - BUKAN INFORMASI DEBITUR RESMI" in p.extract_text() for p in pdf.pages
    )
    assert "PEMOHON & <CONTOH>" in pdf.pages[0].extract_text()
    assert "Ringkasan fasilitas" in pdf.pages[0].extract_text()
    for page in pdf.pages[1:]:
        text = page.extract_text()
        assert "Riwayat kualitas" in text and "2025-10" in text and "2026-09" in text
        assert "Agunan" in text and "Penjamin" in text
    result["report"]["synthetic"] = False
    with pytest.raises(ValueError):
        SlikPdfService().render(result)


def test_pdf_only_for_approved_current_owner_and_active_decision(client, face_image):
    app, session, _ = prepare(client, face_image)
    endpoint = "/api/applications/" + app["id"] + "/slik.pdf"
    assert client.get(endpoint).status_code == 409
    client.app.state.slik.issue(app["id"], client.fixture_actor)
    response = client.get(endpoint)
    assert response.status_code == 200 and response.content.startswith(b"%PDF-")
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"].startswith("attachment;")
    assert response.headers["cache-control"] == "no-store"
    other, headers = account(client, "pdf-intruder")
    assert client.get(endpoint, headers=headers).status_code == 404
    client.app.state.workflow.invalidate(
        app["id"], client.fixture_actor, session.revision + 1
    )
    assert client.get(endpoint).status_code == 409


def test_manual_pending_and_expired_decision_never_download_pdf(client, face_image):
    app, _, _ = prepare(client, face_image, manual=True)
    assert client.get("/api/applications/" + app["id"] + "/slik.pdf").status_code == 409
    ready, _, _ = prepare(client, face_image)
    client.app.state.slik.issue(ready["id"], client.fixture_actor)
    flow = client.app.state.workflow
    with flow.repository.connect(write=True) as con:
        data = flow.get(con, ready["id"])
        data["payload"]["decision"]["expires"] = time.time() - 1
        flow.save(con, data)
    assert (
        client.get("/api/applications/" + ready["id"] + "/slik.pdf").status_code == 409
    )


def test_random_financial_data_stable_per_issuance_identity_stays_from_evidence():
    identity = {
        "name": "PEMOHON SERVER",
        "nik": "0000000000000000",
        "birth": "1990-01-01",
        "address": "ALAMAT KTP SERVER",
    }
    adapter = MockSlikAdapter()
    first = adapter.fetch(identity, "SLIK-RANDOM-A")
    again = adapter.fetch(identity, "SLIK-RANDOM-A")
    other = adapter.fetch(identity, "SLIK-RANDOM-B")
    assert first["facilities"] == again["facilities"]
    assert first["facilities"] != other["facilities"]
    assert first["debtor"]["name"] == other["debtor"]["name"] == identity["name"]
    assert first["subject_nik"] == other["subject_nik"] == identity["nik"]
    assert first["debtor"]["birth"] == identity["birth"]
    assert first["debtor"]["address"] == identity["address"]
    for f in first["facilities"] + other["facilities"]:
        assert 0 <= f["outstanding"] <= f["limit"]
    assert first["summary"]["worst_quality"] == max(
        h["quality"] for f in first["facilities"] for h in f["history"]
    )


def test_pdf_rechecks_revision_after_rendering(client, face_image, monkeypatch):
    app, session, _ = prepare(client, face_image)
    client.app.state.slik.issue(app["id"], client.fixture_actor)
    original = SlikPdfService.render

    def changed(self, result):
        content = original(self, result)
        client.app.state.workflow.invalidate(
            app["id"], client.fixture_actor, session.revision + 1
        )
        return content

    monkeypatch.setattr(SlikPdfService, "render", changed)
    assert client.get("/api/applications/" + app["id"] + "/slik.pdf").status_code == 409


def test_legacy_demo_report_upgrades_identity_once_and_bad_adapter_cannot_issue(
    client, face_image
):
    app, _, _ = prepare(client, face_image)
    slik = client.app.state.slik
    slik.issue(app["id"], client.fixture_actor)
    with slik.repository.connect(write=True) as con:
        row = con.execute(
            "SELECT * FROM issuance WHERE application_id=?", (app["id"],)
        ).fetchone()
        old = slik.flow.box.open_json(row["report_ciphertext"], row["id"])
        old["report"].update(
            schema_version="slik-demo-v2",
            subject_name="DEBITUR SINTETIS",
            subject_nik="0000000000000000",
        )
        con.execute(
            "UPDATE issuance SET report_ciphertext=? WHERE id=?",
            (slik.flow.box.seal_json(old, row["id"]), row["id"]),
        )
    fixed = slik.report(app["id"], client.fixture_actor)
    assert fixed["report"]["subject_name"] == "PEMOHON DEMO"
    assert fixed["report"]["subject_nik"] == "1234567890123456"
    assert fixed == slik.report(app["id"], client.fixture_actor)
    second, _, _ = prepare(client, face_image)

    class WrongIdentity(MockSlikAdapter):
        def fetch(self, identity, key):
            report = super().fetch(identity, key)
            report["subject_nik"] = "0000000000000000"
            return report

    slik.adapter = WrongIdentity()
    assert slik.issue(second["id"], client.fixture_actor)["state"] == "SLIK_PENDING"
    assert (
        client.get("/api/applications/" + second["id"] + "/slik.pdf").status_code == 409
    )
