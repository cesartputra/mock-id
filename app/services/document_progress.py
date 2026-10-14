"""Applicant-safe document stages derived from the current evidence revision."""


def document_progress(application):
    state = application["state"]
    payload = application["payload"]
    history = [h for h in payload.get("history", [])
               if h.get("revision") == application["revision"]]

    def latest(states):
        return next((h["at"] for h in reversed(history) if h["to"] in states), None)

    stages = [
        {"key": "received", "label": "Dokumen Diterima", "status": "done",
         "message": "Bukti capture diterima pada server lokal.",
         "at": next((h["at"] for h in history if h["from"] == "VERIFYING"), None)},
        {"key": "review", "label": "Dokumen Direview", "status": "pending",
         "message": "Menunggu pemeriksaan.", "at": None},
        {"key": "complete", "label": "Selesai", "status": "pending",
         "message": "PDF tersedia setelah pemeriksaan disetujui.", "at": None},
    ]
    received, review, complete = stages
    if state == "VERIFYING":
        received.update(status="current", message="Pengambilan dan pemeriksaan bukti berlangsung.", at=None)
    elif state == "CAPTURE_RETRY":
        received.update(status="attention", message="Bukti perlu diperbaiki. Ulangi hanya tahap yang diminta.")
    elif state == "TECHNICAL_PENDING":
        target = review if payload.get("evidence") else received
        if target is received:
            received["at"] = None
        target.update(status="attention", message="Pemeriksaan tertunda karena gangguan teknis; dapat dicoba kembali.")
    elif state in {"MANUAL_PENDING", "MANUAL_SCHEDULED", "MANUAL_IN_REVIEW"}:
        review.update(status="current", at=latest({"MANUAL_IN_REVIEW"}), message={
            "MANUAL_PENDING": "Menunggu ketersediaan kuota pemeriksaan manual.",
            "MANUAL_SCHEDULED": "Dalam antrean pemeriksaan helpdesk sesuai reservasi.",
            "MANUAL_IN_REVIEW": "Helpdesk sedang memeriksa bukti permohonan.",
        }[state])
    elif state in {"REJECTED", "MANUAL_REJECTED"}:
        review.update(status="failed", message="Permohonan belum disetujui. Lihat keterangan pemeriksaan.",
                      at=latest({state}))
        complete["message"] = "PDF tidak diterbitkan untuk keputusan ini."
    elif state in {"AUTO_APPROVED", "MANUAL_APPROVED", "SLIK_PENDING", "SLIK_READY"}:
        review.update(status="done", message="Pemeriksaan manual disetujui." if
                      (payload.get("decision") or {}).get("kind") == "manual" else "Pemeriksaan otomatis disetujui.",
                      at=latest({"AUTO_APPROVED", "MANUAL_APPROVED"}))
        complete.update(status="done" if state == "SLIK_READY" else "current",
                        message="PDF SLIK demo tersedia untuk diunduh." if state == "SLIK_READY"
                        else "Laporan SLIK demo sedang disiapkan.",
                        at=latest({"SLIK_READY"}) if state == "SLIK_READY" else None)
    else:
        received.update(status="pending", message="Bukti belum diterima.", at=None)
    return {"stages": stages, "updated": application["updated"], "revision": application["revision"]}


def registration_progress(record):
    """Unlinked mock forms never claim verification or issuance."""
    return {"updated": record["created"], "revision": None, "stages": [
        {"key": "received", "label": "Dokumen Diterima", "status": "done",
         "message": "Formulir demo disimpan. Dokumen belum diverifikasi.", "at": record["created"]},
        {"key": "review", "label": "Dokumen Direview", "status": "pending",
         "message": "Jalur ini hanya pratinjau; pemeriksaan tidak dijalankan.", "at": None},
        {"key": "complete", "label": "Selesai", "status": "pending",
         "message": "Tidak ada laporan SLIK yang diterbitkan pada jalur mock.", "at": None},
    ]}
