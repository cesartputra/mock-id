"""Generate authorized, clearly marked synthetic reports; no browser print step."""

from io import BytesIO
from xml.sax.saxutils import escape
from datetime import datetime
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    PageBreak,
)
from app.services.slik import DEMO_MARKER


class SlikPdfService:
    def render(self, result):
        report = result["report"]
        if not report.get("synthetic") or report.get("label") != DEMO_MARKER:
            raise ValueError("Generator demo hanya menerima laporan sintetis bertanda.")
        out = BytesIO()
        width = A4[0] - 32 * mm
        styles = getSampleStyleSheet()
        styles.add(
            ParagraphStyle(
                "BodyDemo", fontName="Helvetica", fontSize=9, leading=13, spaceAfter=7
            )
        )
        styles.add(
            ParagraphStyle(
                "LabelDemo",
                fontName="Helvetica",
                fontSize=7.5,
                leading=10,
                textColor=colors.HexColor("#68716c"),
            )
        )
        styles.add(
            ParagraphStyle(
                "HeadingDemo",
                fontName="Helvetica-Bold",
                fontSize=13,
                leading=17,
                textColor=colors.HexColor("#b5252d"),
                spaceBefore=16,
                spaceAfter=9,
            )
        )
        styles.add(
            ParagraphStyle(
                "TitleDemo",
                fontName="Helvetica-Bold",
                fontSize=23,
                leading=28,
                spaceAfter=10,
            )
        )
        styles.add(
            ParagraphStyle(
                "SmallDemo",
                fontName="Helvetica",
                fontSize=7,
                leading=10,
                alignment=TA_CENTER,
            )
        )

        def p(value, style="BodyDemo"):
            return Paragraph(
                escape(str(value if value is not None else "-")), styles[style]
            )

        def money(value):
            return "Rp " + f"{value:,.0f}".replace(",", ".")

        def fields(pairs):
            rows = []
            for i in range(0, len(pairs), 2):
                cells = []
                for label, value in pairs[i : i + 2]:
                    cells.append([p(label, "LabelDemo"), p(value)])
                if len(cells) == 1:
                    cells.append("")
                rows.append(cells)
            t = Table(rows, colWidths=[width / 2] * 2, hAlign="LEFT")
            t.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f4f6f3")),
                        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#dce1dc")),
                        (
                            "INNERGRID",
                            (0, 0),
                            (-1, -1),
                            0.5,
                            colors.HexColor("#dce1dc"),
                        ),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 10),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                        ("TOPPADDING", (0, 0), (-1, -1), 8),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ]
                )
            )
            return t

        def heading(text):
            return p(text, "HeadingDemo")

        def footer(canvas, doc):
            canvas.saveState()
            canvas.setFillColor(colors.HexColor("#b5252d"))
            canvas.setFont("Helvetica-Bold", 8)
            canvas.drawString(
                16 * mm, A4[1] - 16 * mm, "DEMO - BUKAN INFORMASI DEBITUR RESMI"
            )
            canvas.setStrokeColor(colors.HexColor("#b5252d"))
            canvas.line(16 * mm, A4[1] - 19 * mm, A4[0] - 16 * mm, A4[1] - 19 * mm)
            canvas.setFont("Helvetica", 7)
            canvas.setFillColor(colors.HexColor("#68716c"))
            canvas.drawString(
                16 * mm,
                13 * mm,
                "Laporan sintetis. Tidak berasal dari layanan SLIK OJK.",
            )
            canvas.drawRightString(A4[0] - 16 * mm, 13 * mm, f"Halaman {doc.page}")
            canvas.restoreState()

        search = report.get("search", {})
        debtor = report.get("debtor", {})
        summary = report.get("summary", {})
        stamp = search.get("requested_at", "-")
        if stamp != "-":
            from app.services.workflow import JAKARTA

            stamp = (
                datetime.fromisoformat(stamp)
                .astimezone(JAKARTA)
                .strftime("%d-%m-%Y %H:%M WIB")
            )
        story = [
            p("Informasi Debitur", "TitleDemo"),
            p("Contoh laporan SLIK - debitur perseorangan"),
            p(
                "Identitas debitur mengikuti data KTP yang disimpan dan diperiksa server lokal. Seluruh fasilitas dan nominal kredit adalah data acak sintetis, bukan informasi keuangan pemohon. Identitas resmi belum diverifikasi oleh Dukcapil."
            ),
            heading("Permohonan yang diproses"),
            fields(
                [
                    ("Pemohon", result["request_subject"]["name"]),
                    (
                        "NIK pemohon (tersamarkan)",
                        result["request_subject"]["nik_masked"],
                    ),
                ]
            ),
            heading("Informasi pencarian"),
            fields(
                [
                    ("Nomor laporan demo", report["reference"]),
                    ("Kata kunci pencarian", "NIK " + report["subject_nik"]),
                    ("Tanggal permintaan", stamp),
                    ("Posisi data contoh", search.get("last_position")),
                ]
            ),
            heading("Data pokok debitur"),
            fields(
                [
                    ("Nama debitur", report["subject_name"]),
                    ("NIK debitur", report["subject_nik"]),
                    ("Jenis debitur", debtor.get("type", "Perseorangan")),
                    (
                        "Tempat / tanggal lahir",
                        debtor.get("birthplace", "-")
                        + " / "
                        + debtor.get("birth", "-"),
                    ),
                    ("Alamat KTP", debtor.get("address")),
                    ("Pekerjaan (bila tersedia)", debtor.get("occupation")),
                ]
            ),
            heading("Ringkasan fasilitas"),
            fields(
                [
                    (
                        "Plafon efektif",
                        money(
                            summary.get(
                                "total_limit",
                                sum(f["limit"] for f in report["facilities"]),
                            )
                        ),
                    ),
                    (
                        "Baki debet",
                        money(
                            summary.get(
                                "total_outstanding",
                                sum(f["outstanding"] for f in report["facilities"]),
                            )
                        ),
                    ),
                    (
                        "Jumlah kreditur",
                        summary.get("creditors", len(report["facilities"])),
                    ),
                    (
                        "Kualitas terburuk / bulan",
                        str(summary.get("worst_quality", "-"))
                        + " / "
                        + summary.get("worst_month", "-"),
                    ),
                ]
            ),
            Spacer(1, 8),
            p("Baki debet adalah sisa pokok pinjaman, di luar bunga dan denda."),
        ]
        for i, f in enumerate(report["facilities"]):
            story += [
                PageBreak(),
                p(f"Kredit / Pembiayaan {i+1}", "TitleDemo"),
                p(f["creditor"]),
                fields(
                    [
                        (
                            "Pelapor / cabang",
                            f["creditor"] + " / " + f.get("branch", "-"),
                        ),
                        ("Tanggal update", f.get("updated")),
                        ("Nomor rekening contoh", f.get("account")),
                        ("Nomor akad contoh", f.get("contract")),
                        (
                            "Jenis / penggunaan",
                            f.get("type", "-") + " / " + f.get("usage", "-"),
                        ),
                        ("Kondisi fasilitas", f.get("condition")),
                        ("Tanggal mulai", f.get("started")),
                        ("Tanggal jatuh tempo", f.get("maturity")),
                        ("Plafon", money(f["limit"])),
                        ("Baki debet", money(f["outstanding"])),
                        ("Kualitas kredit", f["collectibility"]),
                        (
                            "Suku bunga contoh",
                            str(f.get("interest_percent", "-")) + "%",
                        ),
                        (
                            "Tunggakan pokok / bunga",
                            money(f.get("principal_arrears", 0))
                            + " / "
                            + money(f.get("interest_arrears", 0)),
                        ),
                        ("Jumlah hari tunggakan", f.get("arrears_days")),
                    ]
                ),
                heading("Riwayat kualitas / hari tunggakan 12 bulan"),
            ]
            history = f.get("history", [])
            if history:
                data = [
                    ["Bulan"] + [h["month"] for h in history],
                    ["Kualitas"] + [str(h["quality"]) for h in history],
                    ["Hari tunggakan"] + [str(h["arrears_days"]) for h in history],
                ]
                data = [[p(v, "SmallDemo") for v in row] for row in data]
                table = Table(
                    data, colWidths=[65] + [(width - 65) / len(history)] * len(history)
                )
                table.setStyle(
                    TableStyle(
                        [
                            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dce1dc")),
                            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f4f6f3")),
                            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                            ("TOPPADDING", (0, 0), (-1, -1), 6),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                            ("LEFTPADDING", (0, 0), (-1, -1), 2),
                            ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                        ]
                    )
                )
                story.append(table)
            else:
                story.append(p("Riwayat belum tersedia pada laporan contoh ini."))
            story.append(heading("Agunan"))
            for c in f.get("collateral", []):
                story.append(
                    fields(
                        [
                            ("Jenis / nomor", c["type"] + " / " + c["reference"]),
                            ("Nilai agunan contoh", money(c["value"])),
                            ("Pemilik contoh", c["owner"]),
                            ("Tanggal penilaian", c["valuation_date"]),
                            ("Paripasu", "Ya" if c["shared"] else "Tidak"),
                        ]
                    )
                )
            if not f.get("collateral"):
                story.append(p("Tidak ada agunan pada fasilitas contoh ini."))
            story.append(heading("Penjamin"))
            for g in f.get("guarantors", []):
                story.append(
                    fields(
                        [
                            ("Nama contoh", g["name"]),
                            ("Identitas contoh", g["identity"]),
                            ("Golongan", g["type"]),
                            ("Tanggal update", g["updated"]),
                        ]
                    )
                )
            if not f.get("guarantors"):
                story.append(p("Tidak ada penjamin pada fasilitas contoh ini."))
            story += [
                Spacer(1, 12),
                p(
                    "Kode kualitas: 1 - Lancar; 2 - Dalam Perhatian Khusus; 3 - Kurang Lancar; 4 - Diragukan; 5 - Macet."
                ),
            ]
        doc = SimpleDocTemplate(
            out,
            pagesize=A4,
            rightMargin=16 * mm,
            leftMargin=16 * mm,
            topMargin=25 * mm,
            bottomMargin=23 * mm,
            title="Laporan SLIK Demo - Bukan Informasi Debitur Resmi",
            author="mock-id demo",
            pageCompression=1,
        )
        doc.build(story, onFirstPage=footer, onLaterPages=footer)
        return out.getvalue()
