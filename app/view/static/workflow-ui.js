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
  if (["admin", "helpdesk"].includes(principal?.role))
    return `<section class="public-form-panel"><h1>Akun petugas</h1><p>${esc(principal.login)} · ${esc(principal.role)}</p><button class="button primary" data-page="${principal.role === "admin" ? "dashboard" : "queue"}">Workspace petugas</button><button class="button" data-logout>Keluar</button></section>`;
  return `<section class="public-form-panel"><span class="home-kicker">AKSES DEMO LOKAL</span><h1>Masuk sebagai petugas</h1><p>Halaman ini untuk helpdesk dan administrator. Pemohon langsung memilih Pendaftaran tanpa login.</p><form id="account-form"><div class="field"><label for="account-login">Nama akun</label><input id="account-login" name="login" autocomplete="username" required minlength="3" maxlength="80"></div><div class="field"><label for="account-password">Kata sandi</label><input id="account-password" name="password" type="password" autocomplete="current-password" required minlength="10" maxlength="200"></div><p class="text-error" id="step-error" role="alert"></p><div class="form-actions"><button class="button primary" name="action" value="login">Masuk</button></div></form><p class="state-note">Akun helpdesk/administrator dibuat melalui perintah administrator di terminal. Email bukan kanal pengiriman hasil pada demo ini.</p></section>`;
}
function routingExplanation(routing) {
  const controlLabels = {
    session_nonce_proof: "Binding bukti sesi",
    document_identity_complete: "Identitas KTP lengkap",
    no_security_rejection: "Tidak ada penolakan keamanan",
    applicant_authority: "Kewenangan pemohon",
    approved_identity_procedure: "Prosedur identitas",
  };
  const labels = {
    face: "Kemiripan wajah",
    pad: "PAD rekaman",
    ocr: "OCR KTP",
    ai: "Bukti classifier AI",
    controls: "Kelengkapan seluruh kontrol",
  };
  if (!routing.contributions || !routing.weights || !routing.components)
    return "";
  const rows = Object.entries(routing.contributions)
    .map(
      ([key, points]) =>
        `<tr><td>${esc(labels[key] || key)}</td><td>${Number(routing.components[key]).toFixed(2)}</td><td>${(Number(routing.weights[key]) * 100).toFixed(2)}%</td><td>${Number(points).toFixed(2)}</td></tr>`,
    )
    .join("");
  return `<details class="routing-explanation"><summary>Asal perhitungan skor</summary><div class="routing-table-scroll"><table><thead><tr><th>Komponen</th><th>Poin heuristik</th><th>Bobot</th><th>Kontribusi</th></tr></thead><tbody>${rows}</tbody></table></div><p>Skor = jumlah (poin × bobot). Semua kontrol wajib juga harus terpenuhi. ${routing.ai_validation_required === false ? "Classifier AI hanya diagnostik opsional dan tidak memengaruhi skor atau kelulusan." : routing.ai_evidence_usable === false ? "Classifier AI belum meyakinkan: tidak mendapat poin bukti dan memerlukan tinjauan." : ""}</p>${routing.assessment?.blocked_controls?.length ? `<p>Perlu diperiksa: ${routing.assessment.blocked_controls.map((name) => esc(controlLabels[name] || name)).join(", ")}.</p>` : ""}</details>`;
}
function applicationPanel(app, operator = false) {
  const routing = app.routing || {};
  const manual = app.state === "MANUAL_PENDING";
  return `<section class="panel config-panel application-panel"><div class="panel-head"><div><small>${esc(app.id)} · bukti versi ${app.capture_revision}</small><h2>${esc(stateLabels[app.state] || app.state)}</h2></div><span class="badge ${["REJECTED", "MANUAL_REJECTED"].includes(app.state) ? "orange" : "blue"}">${esc(app.state)}</span></div><p>${esc(app.state === "SLIK_READY" ? "Verifikasi disetujui. PDF SLIK demo diunduh otomatis. Jika browser menahan unduhan, gunakan tombol unduh ulang." : app.reason || "Ikuti langkah verifikasi untuk melanjutkan permohonan.")}</p>${typeof routing.routing_score === "number" ? `<div class="routing-score"><strong>${(Math.floor(routing.routing_score * 100) / 100).toFixed(2)}<small>/100</small></strong><span>Skor routing ${routing.calibrated ? "terkalibrasi" : "heuristik demo"}<br>Bukan persentase kepastian identitas. ${routing.automatic_threshold === 50 ? "Ambang skor demo: ≥50/100 dan seluruh kontrol wajib terpenuhi." : ""} Tampilan dipotong dua desimal; keputusan memakai nilai asli.</span></div>` : ""}${routingExplanation(routing)}${routing.demo_model_override ? '<p class="callout">Disetujui dengan ambang skor demo. Ada kontrol model yang belum terpenuhi; nilai aslinya tetap tercatat. PDF berisi data keuangan sintetis.</p>' : ""}<p class="simulation-note">${app.identity_demo_passed ? "Dukcapil: MOCK · lolos simulasi." : `Identitas resmi: ${app.identity_verified ? "terverifikasi oleh prosedur berwenang" : "belum terverifikasi"}.`} Identitas laporan mengikuti data KTP server; data keuangannya acak sintetis.</p>${manual ? `<div class="callout">${esc(app.manual_admission?.message || "Kuota hari ini akan diperiksa otomatis menggunakan bukti yang sudah diambil.")}${app.manual_admission?.next_working_day ? `<br>Hari kerja berikutnya: ${esc(app.manual_admission.next_working_day)}. Ketersediaan diperiksa kembali saat mencoba; belum ada slot yang dipesan.` : ""}</div>` : ""}${app.reservation ? `<div class="callout">Kasus ${esc(app.reservation.case_id)} · ${esc(app.reservation.day)} · ${esc(app.reservation.window)} WIB<br>Status ${esc(app.reservation.state)}</div><p>Halaman ini memeriksa status otomatis. PDF diunduh setelah pemeriksaan disetujui. Simpan nomor permohonan untuk mengecek melalui Status layanan pada browser yang sama.</p>` : ""}${["REJECTED", "MANUAL_REJECTED"].includes(app.state) ? `<p class="callout">${routing.security_review ? "Pemeriksaan memberi sinyal risiko keamanan. Ini bukan bukti pasti penipuan. " : ""}${esc(app.appeal)}</p>` : ""}${
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
  }<div class="buttons">${app.review_note_evidence ? `<button class="button" data-evidence="${esc(app.review_note_evidence)}">Lihat catatan helpdesk</button>` : ""}${!operator && manual ? `<button class="button primary" data-try-today="${app.id}">Cek kuota hari ini lagi</button>` : ""}${!operator && app.state === "MANUAL_SCHEDULED" ? `<button class="button" data-cancel-case="${app.id}">Batalkan reservasi</button>` : ""}${!operator && approvedStates.includes(app.state) ? `<button class="button primary" data-slik="${app.id}">${app.state === "SLIK_READY" ? "Unduh ulang PDF SLIK demo" : "Coba siapkan PDF kembali"}</button>` : ""}${!operator && ["CAPTURE_RETRY", "TECHNICAL_PENDING", "VERIFYING"].includes(app.state) && (!flow || page === "result") ? `<button class="button primary" data-resume-capture="${app.id}">Lanjutkan capture baru</button>` : ""}${operator && principal?.role === "helpdesk" && app.state === "MANUAL_SCHEDULED" ? `<button class="button primary" data-start-review="${app.id}">Mulai pemeriksaan</button>` : ""}</div>${operator && principal?.role === "helpdesk" && app.state === "MANUAL_IN_REVIEW" ? `<form id="manual-review-form" data-id="${app.id}" data-revision="${app.capture_revision}"><div class="field"><label for="manual-note">Dasar keputusan dan catatan pemeriksaan</label><textarea id="manual-note" name="note" required minlength="10" maxlength="1000"></textarea></div><label class="scenario"><input type="checkbox" name="identity_review"> Saya memeriksa bukti identitas dengan prosedur manual demo (bukan validasi Dukcapil).</label><label class="scenario"><input type="checkbox" name="authority_review"> Saya memeriksa pernyataan dan kewenangan pemohon untuk identitas yang diminta.</label><div class="buttons"><button class="button primary" name="decision" value="approve">Setujui untuk hasil sintetis</button><button class="button danger" name="decision" value="reject">Tolak permohonan ini</button><button class="button" name="decision" value="repair">Minta perbaikan</button></div><p class="text-error" id="step-error" role="alert"></p></form>` : ""}</section>`;
}
function deliveryView() {
  return `${head("Hasil verifikasi", "PDF SLIK demo diunduh otomatis setelah keputusan disetujui dan laporan tersedia.", "", "HASIL PENDAFTARAN")}${selectedApplication ? applicationPanel(selectedApplication) : '<section class="public-form-panel"><p>Belum ada hasil aktif. Mulai melalui Pendaftaran atau masukkan nomor permohonan pada Status layanan.</p><button class="button primary" data-page="registration">Pendaftaran</button></section>'}`;
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
  page = ["helpdesk", "admin"].includes(principal?.role) ? "queue" : "result";
  history.replaceState(null, "", "#" + page);
  render();
  if (principal?.role === "applicant")
    await observeDelivery(selectedApplication);
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
let deliveryTimer = null;
let deliveryWatchEpoch = 0;
function rememberApplication(id) {
  try {
    sessionStorage.setItem("mock_id_active_application", id);
  } catch {}
}
function stopDeliveryWatch() {
  clearTimeout(deliveryTimer);
  deliveryTimer = null;
  deliveryWatchEpoch++;
}
async function fetchReportPdf(app) {
  const epoch = authEpoch,
    generation = deliveryWatchEpoch;
  const response = await fetch(
    `/api/applications/${encodeURIComponent(app.id)}/slik.pdf`,
    {
      credentials: "same-origin",
      headers: { "X-Local-Client": "mock-id", "X-Workspace-Mode": "public" },
    },
  );
  if (!response.ok) return readApiResponse(response);
  const blob = await response.blob();
  if (epoch !== authEpoch || generation !== deliveryWatchEpoch)
    throw new Error("Kepemilikan browser berubah; unduhan lama diabaikan.");
  const magic = new Uint8Array(await blob.slice(0, 5).arrayBuffer());
  if (
    !response.headers.get("content-type")?.startsWith("application/pdf") ||
    String.fromCharCode(...magic) !== "%PDF-"
  )
    throw new Error("Server belum mengirim dokumen PDF yang valid.");
  return blob;
}
let deliveryStorage = null;
try {
  deliveryStorage = sessionStorage;
} catch {}
const reportDelivery = new ReportDelivery({
  fetchPdf: fetchReportPdf,
  storage: deliveryStorage,
  savePdf: (blob, filename) => {
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 30000);
  },
});
async function deliverPdf(app, manual = false) {
  try {
    if (await reportDelivery.deliver(app, { manual }))
      toast("PDF SLIK demo dikirim ke browser untuk diunduh.");
  } catch (error) {
    toast(error.message + " Gunakan tombol unduh kembali.");
  }
}
async function observeDelivery(app) {
  stopDeliveryWatch();
  if (!app || principal?.role !== "applicant") return;
  rememberApplication(app.id);
  if (app.state === "SLIK_READY") {
    await deliverPdf(app);
    return;
  }
  if (
    ![
      "MANUAL_PENDING",
      "MANUAL_SCHEDULED",
      "MANUAL_IN_REVIEW",
      "SLIK_PENDING",
    ].includes(app.state)
  )
    return;
  const generation = deliveryWatchEpoch,
    ownerEpoch = authEpoch;
  const poll = async () => {
    if (
      generation !== deliveryWatchEpoch ||
      ownerEpoch !== authEpoch ||
      !["verify", "result"].includes(page)
    )
      return;
    try {
      const fresh = await api("/applications/" + app.id);
      if (generation !== deliveryWatchEpoch || ownerEpoch !== authEpoch) return;
      selectedApplication = fresh;
      if (flow?.result?.application?.id === app.id)
        flow.result.application = fresh;
      render();
      if (fresh.state === "SLIK_READY") {
        await deliverPdf(fresh);
        return;
      }
      if (
        ![
          "MANUAL_PENDING",
          "MANUAL_SCHEDULED",
          "MANUAL_IN_REVIEW",
          "SLIK_PENDING",
        ].includes(fresh.state)
      )
        return;
    } catch (error) {
      if ([401, 403, 404, 410].includes(error.status)) return;
    }
    if (generation === deliveryWatchEpoch)
      deliveryTimer = setTimeout(poll, 5000);
  };
  deliveryTimer = setTimeout(poll, 5000);
}
document.addEventListener("click", async (event) => {
  const button = event.target.closest("button");
  if (!button) return;
  try {
    if (button.hasAttribute("data-logout")) {
      await api("/auth/logout", { method: "POST" });
      authEpoch++;
      stopDeliveryWatch();
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
      let app = await api("/applications/" + id);
      if (app.state !== "SLIK_READY")
        app = await api("/applications/" + id + "/slik", { method: "POST" });
      selectedApplication = app;
      rememberApplication(id);
      page = "result";
      history.replaceState(null, "", "#result");
      render();
      stopDeliveryWatch();
      if (app.state === "SLIK_READY") await deliverPdf(app, true);
      else await observeDelivery(app);
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
            : "home",
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
