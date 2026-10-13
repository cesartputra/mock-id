"""Complete server control inventory: missing/uncertain evidence never passes."""

CONTROL_NAMES = (
    "Liveness saat rekaman",
    "OCR KTP",
    "Kualitas capture",
    "Selfie tanpa penutup wajah",
    "Foto KYC tanpa penutup wajah",
    "Wajah KTP ↔ selfie",
    "Wajah selfie ↔ foto KYC",
    "KTP dalam foto KYC",
    "Kesesuaian NIK kedua foto KTP",
    "Tangan dekat KTP",
    "Tantangan liveness",
    "Kontinuitas wajah capture",
    "Anti-spoof / PAD",
    "PAD foto memegang KTP",
    "Dukcapil",
)


OPTIONAL_CONTROLS = {"Classifier gambar AI (diagnostik)"}


def assess_controls(result, mandatory, *, demo):
    by_name = {}
    for check in result.get("checks", []):
        by_name.setdefault(check.get("name"), []).append(check)
    controls = []
    for name in CONTROL_NAMES:
        matches = by_name.get(name, [])
        check = matches[0] if len(matches) == 1 else None
        status = check.get("status") if check else "missing"
        if name == "Dukcapil" and check and check.get("mode") == "mock":
            detail = check.get("detail", {})
            passed = demo and status == "passed" and detail.get("simulated") is True
        else:
            passed = status == "passed"
        controls.append(
            {
                "name": name,
                "passed": bool(passed),
                "status": status,
                "effect": "required",
                "mode": check.get("mode") if check else None,
            }
        )
    # Every additional check participates; it cannot disappear through "advisory".
    for name, matches in by_name.items():
        if name not in CONTROL_NAMES and name not in OPTIONAL_CONTROLS:
            controls.append(
                {
                    "name": name or "Kontrol tanpa nama",
                    "passed": len(matches) == 1
                    and matches[0].get("status") == "passed",
                    "status": (
                        matches[0].get("status") if len(matches) == 1 else "duplicate"
                    ),
                    "effect": "required",
                    "mode": matches[0].get("mode"),
                }
            )
    for key in (
        "session_nonce_proof",
        "document_identity_complete",
        "no_security_rejection",
        "applicant_authority",
        "approved_identity_procedure",
    ):
        passed = mandatory.get(key) is True
        controls.append(
            {
                "name": key,
                "passed": passed,
                "status": "passed" if passed else "failed",
                "effect": "required",
            }
        )
    # Composite document_face_liveness_pad is a gate, not a duplicate score component.
    coverage = sum(c["passed"] for c in controls) / len(controls)
    blocked = [c["name"] for c in controls if not c["passed"]]
    incomplete = any(
        c["status"] in ("missing", "unavailable", "duplicate") for c in controls
    )
    return {
        "controls": controls,
        "optional_controls": [
            dict(c, effect="advisory")
            for name in OPTIONAL_CONTROLS
            for c in by_name.get(name, [])
        ],
        "coverage": coverage,
        "all_passed": not blocked,
        "blocked_controls": blocked,
        "incomplete": incomplete,
        "formula": "passed_controls / total_required_controls",
        "control_count": len(controls),
    }
