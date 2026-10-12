"use strict";
let authEpoch = 0;
let accessMode = null;
let principal = null,
  applicationRows = [],
  selectedApplication = null,
  capacityCalendar = null,
  operatorMetrics = null;
const stateLabels = {
  VERIFYING: "Verifikasi berlangsung",
  AUTO_APPROVED: "Verifikasi otomatis disetujui — demo",
  MANUAL_PENDING: "Pemeriksaan manual diperlukan",
  MANUAL_SCHEDULED: "Pemeriksaan manual terjadwal",
  MANUAL_IN_REVIEW: "Sedang diperiksa helpdesk",
  MANUAL_APPROVED: "Pemeriksaan manual disetujui — demo",
  MANUAL_REJECTED: "Permohonan belum disetujui",
  REJECTED: "Permohonan belum disetujui",
  CAPTURE_RETRY: "Perbaiki bukti",
  TECHNICAL_PENDING: "Pemeriksaan tertunda",
  SLIK_PENDING: "Hasil sedang disiapkan",
  SLIK_READY: "Hasil SLIK demo tersedia",
};
const approvedStates = [
  "AUTO_APPROVED",
  "MANUAL_APPROVED",
  "SLIK_PENDING",
  "SLIK_READY",
];
const keyForAction = () => crypto.randomUUID();
function accountView() {
  if (principal)
    return `<section class="public-form-panel"><h1>Akun petugas</h1><p>${esc(principal.login)} · ${esc(principal.role)}</p><button class="button primary" data-page="requests">Permohonan saya</button><button class="button" data-logout>Keluar</button></section>`;
  return `<section class="public-form-panel"><span class="home-kicker">AKSES DEMO LOKAL</span><h1>Masuk sebagai petugas</h1><p>Halaman ini untuk helpdesk dan administrator. Pemohon langsung memilih Pendaftaran tanpa login.</p><form id="account-form"><div class="field"><label for="account-login">Nama akun</label><input id="account-login" name="login" autocomplete="username" required minlength="3" maxlength="80"></div><div class="field"><label for="account-password">Kata sandi</label><input id="account-password" name="password" type="password" autocomplete="current-password" required minlength="10" maxlength="200"></div><p class="text-error" id="step-error" role="alert"></p><div class="form-actions"><button class="button primary" name="action" value="login">Masuk</button></div></form><p class="state-note">Akun helpdesk/administrator dibuat melalui perintah administrator di terminal. Email bukan kanal pengiriman hasil pada demo ini.</p></section>`;
}
function applicationPanel(app, operator = false) {
  const routing = app.routing || {};
  const manual = app.state === "MANUAL_PENDING";
  return `<section class="panel config-panel application-panel"><div class="panel-head"><div><small>${esc(app.id)} · bukti versi ${app.capture_revision}</small><h2>${esc(stateLabels[app.state] || app.state)}</h2></div><span class="badge ${["REJECTED", "MANUAL_REJECTED"].includes(app.state) ? "orange" : "blue"}">${esc(app.state)}</span></div><p>${esc(app.reason || "Ikuti langkah verifikasi untuk melanjutkan permohonan.")}</p>${typeof routing.routing_score === "number" ? `<div class="routing-score"><strong>${(Math.floor(routing.routing_score * 100) / 100).toFixed(2)}<small>/100</small></strong><span>Skor routing ${routing.calibrated ? "terkalibrasi" : "heuristik demo"}<br>Bukan persentase kepastian identitas. Tampilan dipotong dua desimal; keputusan memakai nilai asli.</span></div>` : ""}<p class="simulation-note">Identitas resmi: ${app.identity_verified ? "terverifikasi oleh prosedur berwenang" : "belum terverifikasi"}. Demo hanya menghasilkan data sintetis.</p>${manual ? `<div class="callout">${esc(app.manual_admission?.message || "Kuota hari ini akan diperiksa otomatis menggunakan bukti yang sudah diambil.")}${app.manual_admission?.next_working_day ? `<br>Hari kerja berikutnya: ${esc(app.manual_admission.next_working_day)}. Ketersediaan diperiksa kembali saat mencoba; belum ada slot yang dipesan.` : ""}</div>` : ""}${app.reservation ? `<div class="callout">Kasus ${esc(app.reservation.case_id)} · ${esc(app.reservation.day)} · ${esc(app.reservation.window)} WIB<br>Status ${esc(app.reservation.state)}</div>` : ""}${["REJECTED", "MANUAL_REJECTED"].includes(app.state) ? `<p class="callout">${routing.security_review ? "Pemeriksaan memberi sinyal risiko keamanan. Ini bukan bukti pasti penipuan. " : ""}${esc(app.appeal)}</p>` : ""}${
    operator
      ? `<div class="result-controls">${Object.entries(routing.mandatory || {})
          .map(
            ([name, value]) =>
              `<div class="result-control"><span>${esc(name)}</span><span class="badge ${value ? "green" : "orange"}">${value ? "Terpenuhi" : "Perlu pemeriksaan"}</span></div>`,
          )
          .join("")}</div><div class="evidence-grid">${(app.evidence || [])
          .filter(
            (e) =>
              ["document", "selfie", "holding"].includes(e.kind) ||
              e.kind.startsWith("gesture-"),
          )
          .map(
            (e) =>
              `<figure><img src="/api/evidence/${encodeURIComponent(e.id)}" alt="Bukti ${esc(e.kind)}"><figcaption>${esc(e.kind)} · ${date(e.created)}<small>Retensi sampai ${date(e.expires * 1000)}</small></figcaption></figure>`,
          )
          .join("")}</div><div class="buttons">${(app.evidence || [])
          .filter((e) => ["identity", "verification"].includes(e.kind))
          .map(
            (e) =>
              `<button class="button" data-evidence="${esc(e.id)}">Lihat ${e.kind === "identity" ? "identitas server" : "hasil model & pengikat bukti"}</button>`,
          )
          .join("")}</div>`
      : ""
  }<div class="buttons">${app.review_note_evidence ? `<button class="button" data-evidence="${esc(app.review_note_evidence)}">Lihat catatan helpdesk</button>` : ""}${!operator && manual ? `<button class="button primary" data-try-today="${app.id}">Cek kuota hari ini lagi</button>` : ""}${!operator && app.state === "MANUAL_SCHEDULED" ? `<button class="button" data-cancel-case="${app.id}">Batalkan reservasi</button>` : ""}${!operator && approvedStates.includes(app.state) ? `<button class="button primary" data-slik="${app.id}">${app.state === "SLIK_READY" ? "Lihat hasil SLIK demo" : app.state === "SLIK_PENDING" ? "Periksa / coba penarikan kembali" : "Ambil hasil SLIK demo"}</button><button class="button" data-persistent-registration="${app.id}">Lengkapi pendaftaran demo</button>` : ""}${!operator && ["CAPTURE_RETRY", "TECHNICAL_PENDING", "VERIFYING"].includes(app.state) && !flow ? `<button class="button primary" data-resume-capture="${app.id}">Lanjutkan capture baru</button>` : ""}${operator && principal?.role === "helpdesk" && app.state === "MANUAL_SCHEDULED" ? `<button class="button primary" data-start-review="${app.id}">Mulai pemeriksaan</button>` : ""}</div>${operator && principal?.role === "helpdesk" && app.state === "MANUAL_IN_REVIEW" ? `<form id="manual-review-form" data-id="${app.id}" data-revision="${app.capture_revision}"><div class="field"><label for="manual-note">Dasar keputusan dan catatan pemeriksaan</label><textarea id="manual-note" name="note" required minlength="10" maxlength="1000"></textarea></div><label class="scenario"><input type="checkbox" name="identity_review"> Saya memeriksa bukti identitas dengan prosedur manual demo (bukan validasi Dukcapil).</label><label class="scenario"><input type="checkbox" name="authority_review"> Saya memeriksa pernyataan dan kewenangan pemohon untuk identitas yang diminta.</label><div class="buttons"><button class="button primary" name="decision" value="approve">Setujui untuk hasil sintetis</button><button class="button danger" name="decision" value="reject">Tolak permohonan ini</button><button class="button" name="decision" value="repair">Minta perbaikan</button></div><p class="text-error" id="step-error" role="alert"></p></form>` : ""}</section>`;
}
function requestsView() {
  return `${head("Permohonan saya", "Permohonan tersimpan untuk browser ini tanpa login. Gunakan browser yang sama untuk memeriksa status.", `<button class="button primary" data-page="registration">Permohonan baru</button>`, "STATUS PERMOHONAN")}<div class="application-list">${applicationRows.map((app) => `<button class="application-row" data-application="${app.id}"><div><strong>${esc(app.name || "Permohonan baru")}</strong><small>${esc(app.id)} · ${date(app.updated)}</small></div><span class="badge blue">${esc(stateLabels[app.state] || app.state)}</span></button>`).join("") || '<section class="public-form-panel"><p>Belum ada permohonan pada browser ini.</p></section>'}</div>${selectedApplication ? applicationPanel(selectedApplication, principal?.role !== "applicant") : ""}`;
}
function operatorQueueView() {
  const rows = applicationRows.filter(
    (a) => a.state.startsWith("MANUAL_") || a.reservation?.case_id,
  );
  return `${head("Kasus helpdesk", "Bukti, keputusan dan kapasitas menggunakan permohonan persisten.")}<div class="application-list">${rows.map((app) => `<button class="application-row" data-application="${app.id}"><div><strong>${esc(app.name || app.id)}</strong><small>${esc(app.reservation?.case_id || "Belum reservasi")} · ${esc(app.reservation?.day || "Menunggu pilihan jadwal")}</small></div><span>${esc(stateLabels[app.state])}</span></button>`).join("") || '<div class="empty">Belum ada kasus manual yang dapat diakses.</div>'}</div>${selectedApplication ? applicationPanel(selectedApplication, true) : ""}${capacityCalendar ? capacitySummary(capacityCalendar) : ""}`;
}
function capacitySummary(calendar) {
  return `<section class="panel config-panel"><h2>Kapasitas helpdesk</h2><p>${esc(calendar.label)} · ${calendar.timezone}</p><div class="capacity-days">${calendar.days.map((day) => `<div class="capacity-day ${day.available ? "available" : ""}"><strong>${esc(day.day)}</strong><span>${day.working_day ? `${day.used} terpakai · ${day.remaining} tersisa` : "Tutup / hari libur"}</span></div>`).join("")}</div></section>`;
}
function manualCalendarView(app, calendar) {
  return `<p>${esc(calendar.message)}</p><p class="state-note">${esc(calendar.label)} · Asia/Jakarta. Hanya reservasi manual menggunakan kuota helpdesk.</p>${
    calendar.all_full
      ? '<div class="callout">Tidak ada tanggal tersedia dalam horizon ini. Permohonan tetap menunggu jadwal; periksa kembali atau hubungi helpdesk melalui aplikasi induk.</div>'
      : `<form id="manual-booking-form" data-id="${app.id}" data-move="${app.state === "MANUAL_SCHEDULED"}"><div class="capacity-days">${calendar.days
          .filter((d) => d.available)
          .map(
            (d) =>
              `<label class="capacity-day available"><input type="radio" name="day" value="${d.day}" required><strong>${d.day}</strong><span>${d.opens}–${d.closes} WIB · ${d.remaining} slot</span></label>`,
          )
          .join(
            "",
          )}</div><button class="button primary" type="submit">${app.state === "MANUAL_SCHEDULED" ? "Pindahkan jadwal" : "Reservasi pemeriksaan manual"}</button><p class="text-error" id="modal-error" role="alert"></p></form>`
  }<button class="button" data-close>Tutup</button>`;
}
function adminMetricsView() {
  const m = operatorMetrics;
  if (!m) return "";
  return `<section class="panel config-panel"><h2>Operasional permohonan</h2><p>${Object.entries(
    m.routing_volume || {},
  )
    .map(([key, value]) => `${esc(key)}: ${value}`)
    .join(" · ")}</p><div class="capacity-days">${Object.entries(m.volume)
    .map(
      ([k, v]) =>
        `<div class="capacity-day"><strong>${v}</strong><span>${esc(k)}</span></div>`,
    )
    .join(
      "",
    )}</div><p>Kasus menunggu: ${m.waiting_cases} · waktu tunggu rata-rata ${m.wait_seconds_mean === null ? "belum tersedia" : (m.wait_seconds_mean / 3600).toFixed(1) + " jam"}</p><p>Latensi verifikasi rata-rata: ${m.verification_latency_ms_mean === null ? "belum tersedia" : (m.verification_latency_ms_mean / 1000).toFixed(2) + " detik"} · observasi retry: ${m.retry_observations} · gangguan teknis: ${m.technical_results}</p><p class="state-note">${esc(m.scope)}</p></section>`;
}
async function showApplication(id) {
  selectedApplication = await api("/applications/" + id);
  page = ["helpdesk", "admin"].includes(principal?.role) ? "queue" : "requests";
  history.replaceState(null, "", "#" + page);
  render();
}
async function showCapacityConfig() {
  const c = await api("/policy/capacity");
  modal(
    "Kebijakan kapasitas demo",
    `<form id="capacity-config-form"><div class="form-grid">${[
      ["opens", "Buka", "time"],
      ["closes", "Tutup", "time"],
      ["daily_capacity", "Kapasitas harian", "number"],
      ["booking_horizon_days", "Horizon (hari)", "number"],
      ["decision_ttl_hours", "Masa berlaku keputusan (jam)", "number"],
      ["retention_days", "Retensi bukti (hari)", "number"],
    ]
      .map(
        ([k, label, type]) =>
          `<div class="field"><label for="config-${k}">${label}</label><input id="config-${k}" name="${k}" type="${type}" value="${c[k]}" required></div>`,
      )
      .join(
        "",
      )}<div class="field wide"><label for="config-workdays">Hari kerja (0=Senin, 6=Minggu)</label><input id="config-workdays" name="workdays" value="${c.workdays.join(",")}" required></div><div class="field wide"><label for="config-holidays">Hari libur (YYYY-MM-DD, pisahkan koma)</label><input id="config-holidays" name="holidays" value="${c.holidays.join(",")}"></div><div class="field wide"><label for="config-label">Label kebijakan</label><input id="config-label" name="label" value="${esc(c.label)}" required></div></div><p>Timezone: Asia/Jakarta. Contoh demo, bukan SOP resmi OJK.</p><button class="button primary">Simpan kebijakan</button><p class="text-error" id="modal-error" role="alert"></p></form>`,
  );
}
function syntheticReportView(result) {
  const r = result.report;
  const money = (v) =>
    new Intl.NumberFormat("id-ID", {
      style: "currency",
      currency: "IDR",
      maximumFractionDigits: 0,
    }).format(v);
  const fields = (pairs) =>
    `<dl class="slik-fields">${pairs.map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${esc(v ?? "—")}</dd></div>`).join("")}</dl>`;
  const summary = r.summary || {
    total_limit: r.facilities.reduce((n, f) => n + f.limit, 0),
    total_outstanding: r.facilities.reduce((n, f) => n + f.outstanding, 0),
    creditors: r.facilities.length,
  };
  return `<article class="slik-report"><div class="demo-report-marker">DEMO — BUKAN INFORMASI DEBITUR RESMI</div><header class="slik-report-header"><span class="home-kicker">LAPORAN SINTETIS</span><h2>Informasi Debitur</h2><p>Contoh susunan laporan SLIK untuk debitur perseorangan.</p></header><p class="callout">Data contoh tidak menggambarkan kondisi keuangan pemohon dan tidak berasal dari layanan SLIK OJK.</p><p>Permohonan milik <strong>${esc(result.request_subject.name)}</strong> · ${esc(result.request_subject.nik_masked)}. Subjek pada contoh laporan: <strong>${esc(r.subject_name)}</strong>.</p><section><h3>Informasi pencarian</h3>${fields(
    [
      ["Nomor laporan demo", r.reference],
      ["Kata kunci pencarian", "NIK " + r.subject_nik],
      [
        "Tanggal permintaan",
        r.search?.requested_at ? date(r.search.requested_at) : "—",
      ],
      ["Posisi data contoh", r.search?.last_position || "—"],
    ],
  )}</section><section><h3>Data pokok debitur</h3>${fields([
    ["Jenis debitur", r.debtor?.type || "Perseorangan"],
    ["Nama debitur", r.subject_name],
    ["NIK sintetis", r.subject_nik],
    [
      "Tempat / tanggal lahir",
      r.debtor ? r.debtor.birthplace + " / " + r.debtor.birth : "—",
    ],
    ["Alamat contoh", r.debtor?.address],
    ["Pekerjaan contoh", r.debtor?.occupation],
  ])}<p class="state-note">Pelapor contoh: ${esc(r.debtor?.reporters?.join(" · ") || "—")}.</p></section><section><h3>Ringkasan fasilitas</h3><div class="slik-totals">${fields(
    [
      ["Plafon efektif", money(summary.total_limit)],
      ["Baki debet", money(summary.total_outstanding)],
      ["Jumlah kreditur", summary.creditors],
      [
        "Kualitas terburuk / bulan",
        summary.worst_quality
          ? summary.worst_quality + " / " + summary.worst_month
          : "—",
      ],
    ],
  )}</div><p class="state-note">Baki debet adalah sisa pokok pinjaman, di luar bunga dan denda.</p></section>${r.facilities
    .map(
      (f, i) =>
        `<section class="slik-facility"><h3>Kredit / pembiayaan ${i + 1}</h3>${fields(
          [
            ["Pelapor", f.creditor],
            ["Cabang", f.branch],
            ["Nomor rekening contoh", f.account],
            ["Nomor akad", f.contract],
            [
              "Jenis / penggunaan",
              [f.type, f.usage].filter(Boolean).join(" / "),
            ],
            ["Kondisi fasilitas", f.condition],
            [
              "Tanggal mulai / jatuh tempo",
              [f.started, f.maturity].filter(Boolean).join(" / "),
            ],
            ["Tanggal update", f.updated],
            ["Plafon", money(f.limit)],
            ["Baki debet", money(f.outstanding)],
            ["Kualitas", f.collectibility],
            [
              "Suku bunga contoh",
              f.interest_percent == null ? "—" : f.interest_percent + "%",
            ],
            [
              "Tunggakan pokok / bunga",
              f.principal_arrears == null
                ? "—"
                : money(f.principal_arrears) +
                  " / " +
                  money(f.interest_arrears),
            ],
            ["Jumlah hari tunggakan", f.arrears_days],
          ],
        )}<h4>Riwayat kualitas / hari tunggakan 12 bulan</h4><div class="slik-table-scroll" tabindex="0" role="region" aria-label="Riwayat fasilitas ${i + 1}"><table class="slik-history"><thead><tr><th scope="col">Bulan</th>${(f.history || []).map((h) => `<th scope="col">${esc(h.month)}</th>`).join("")}</tr></thead><tbody><tr><th scope="row">Kualitas</th>${(f.history || []).map((h) => `<td class="${h.quality > 1 ? "quality-attention" : ""}">${h.quality}</td>`).join("")}</tr><tr><th scope="row">Hari tunggakan</th>${(f.history || []).map((h) => `<td>${h.arrears_days}</td>`).join("")}</tr></tbody></table></div><h4>Agunan</h4>${
          f.collateral?.length
            ? f.collateral
                .map((c) =>
                  fields([
                    ["Jenis / nomor", c.type + " / " + c.reference],
                    ["Nilai agunan contoh", money(c.value)],
                    ["Pemilik contoh", c.owner],
                    ["Tanggal penilaian", c.valuation_date],
                    ["Paripasu", c.shared ? "Ya" : "Tidak"],
                  ]),
                )
                .join("")
            : "<p>Tidak ada agunan pada fasilitas contoh ini.</p>"
        }<h4>Penjamin</h4>${
          f.guarantors?.length
            ? f.guarantors
                .map((g) =>
                  fields([
                    ["Nama contoh", g.name],
                    ["Identitas contoh", g.identity],
                    ["Golongan", g.type],
                    ["Tanggal update", g.updated],
                  ]),
                )
                .join("")
            : "<p>Tidak ada penjamin pada fasilitas contoh ini.</p>"
        }</section>`,
    )
    .join(
      "",
    )}<section class="slik-legend"><h3>Arti kode kualitas kredit</h3><p>1 — Lancar · 2 — Dalam Perhatian Khusus · 3 — Kurang Lancar · 4 — Diragukan · 5 — Macet.</p><p class="state-note">Seluruh nominal dan identitas dalam laporan ini merupakan contoh sintetis.</p></section><footer>${esc(r.label)}</footer></article><div class="buttons slik-report-actions"><button class="button" data-print-report>Cetak / simpan PDF</button><button class="button primary" data-close>Tutup hasil</button></div>`;
}
document.addEventListener("click", async (event) => {
  const button = event.target.closest("button");
  if (!button) return;
  try {
    if (button.hasAttribute("data-logout")) {
      await api("/auth/logout", { method: "POST" });
      authEpoch++;
      stopCamera();
      $("#modal").close();
      releasePreviews();
      principal = null;
      applicationRows = [];
      selectedApplication = null;
      operatorMetrics = null;
      workspace = {
        records: [],
        audit: [],
        settings: {},
        health: { ready: false, files: {} },
      };
      flow = null;
      selectedApplication = null;
      await navigate("account");
    } else if (button.dataset.application)
      await showApplication(button.dataset.application);
    else if (button.dataset.tryToday) {
      await api(`/applications/${button.dataset.tryToday}/manual/try-today`, {
        method: "POST",
      });
      await reloadWorkspace();
      await showApplication(button.dataset.tryToday);
    } else if (button.dataset.manualCalendar) {
      const app = await api("/applications/" + button.dataset.manualCalendar);
      const calendar = await api("/manual/calendar");
      modal("Pilih jadwal pemeriksaan", manualCalendarView(app, calendar));
    } else if (button.dataset.cancelCase) {
      await api(`/applications/${button.dataset.cancelCase}/manual/cancel`, {
        method: "POST",
        headers: { "Idempotency-Key": keyForAction() },
      });
      await reloadWorkspace();
      await showApplication(button.dataset.cancelCase);
    } else if (button.dataset.startReview) {
      await api(`/applications/${button.dataset.startReview}/manual/start`, {
        method: "POST",
      });
      await reloadWorkspace();
      await showApplication(button.dataset.startReview);
    } else if (button.dataset.slik) {
      const id = button.dataset.slik;
      const app = await api("/applications/" + id);
      if (app.state !== "SLIK_READY")
        await api("/applications/" + id + "/slik", { method: "POST" });
      await reloadWorkspace();
      await showApplication(id);
      if (selectedApplication.state === "SLIK_READY") {
        const result = await api("/applications/" + id + "/slik");
        modal("Hasil SLIK sintetis", syntheticReportView(result));
      }
    } else if (button.hasAttribute("data-print-report")) {
      window.print();
    } else if (button.dataset.evidence) {
      const evidence = await api("/evidence/" + button.dataset.evidence);
      modal(
        "Bukti terikat permohonan",
        `<pre class="report-json">${esc(JSON.stringify(evidence, null, 2))}</pre><button class="button" data-close>Tutup</button>`,
      );
    } else if (button.hasAttribute("data-capacity-config"))
      await showCapacityConfig();
    else if (button.dataset.resumeCapture) {
      await newFlow(false, button.dataset.resumeCapture);
      await navigate("verify");
    } else if (button.dataset.persistentRegistration) {
      selectedApplication = await api(
        "/applications/" + button.dataset.persistentRegistration,
      );
      applicationContext = { debtorType: "individual", preview: false };
      registrationDraft = {
        ...draftDefaults(false),
        name: selectedApplication.name,
      };
      registrationStep = 0;
      await navigate("postkyc");
    }
  } catch (error) {
    errorMessage(error);
  }
});
document.addEventListener("submit", async (event) => {
  const form = event.target;
  if (
    ![
      "account-form",
      "manual-booking-form",
      "manual-review-form",
      "capacity-config-form",
    ].includes(form.id)
  )
    return;
  event.preventDefault();
  if (!form.checkValidity()) return form.reportValidity();
  const data = Object.fromEntries(new FormData(form));
  try {
    if (form.id === "account-form") {
      const body = { login: data.login, password: data.password };
      if (event.submitter?.value === "signup")
        await api("/auth/signup", {
          method: "POST",
          body: JSON.stringify(body),
        });
      authEpoch++;
      principal = (
        await api("/auth/login", { method: "POST", body: JSON.stringify(body) })
      ).principal;
      flow = null;
      selectedApplication = null;
      await navigate(
        principal.role === "helpdesk"
          ? "queue"
          : principal.role === "admin"
            ? "dashboard"
            : "requests",
      );
    } else if (form.id === "manual-booking-form") {
      await api(
        `/applications/${form.dataset.id}/manual/${form.dataset.move === "true" ? "move" : "reserve"}`,
        {
          method: "POST",
          body: JSON.stringify({ day: data.day }),
          headers: { "Idempotency-Key": keyForAction() },
        },
      );
      $("#modal").close();
      await reloadWorkspace();
      await showApplication(form.dataset.id);
    } else if (form.id === "manual-review-form") {
      await api(`/applications/${form.dataset.id}/manual/review`, {
        method: "POST",
        body: JSON.stringify({
          decision: event.submitter.value,
          capture_revision: Number(form.dataset.revision),
          note: data.note,
          identity_review: !!data.identity_review,
          authority_review: !!data.authority_review,
        }),
      });
      await reloadWorkspace();
      await showApplication(form.dataset.id);
    } else {
      const body = {
        ...data,
        timezone: "Asia/Jakarta",
        workdays: data.workdays.split(",").map(Number),
        holidays: data.holidays
          .split(",")
          .map((v) => v.trim())
          .filter(Boolean),
      };
      for (const k of [
        "daily_capacity",
        "booking_horizon_days",
        "decision_ttl_hours",
        "retention_days",
      ])
        body[k] = Number(body[k]);
      await api("/policy/capacity", {
        method: "PUT",
        body: JSON.stringify(body),
      });
      $("#modal").close();
      await reloadWorkspace();
      render();
      toast("Kebijakan kapasitas tersimpan.");
    }
  } catch (error) {
    errorMessage(error);
  }
});
