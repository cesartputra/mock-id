"use strict";
const debtorTypes = {
  individual: "Perseorangan",
  business: "Badan usaha",
  deceased: "Debitur meninggal dunia",
};
let applicationContext = { debtorType: "individual", preview: false };
let registrationDraft = null;
let registrationStep = 0;
let registrationReceipt = null;
let registrationSubmitting = false;
let registrationIdentity = null;
let serviceStatus = null, statusNumberDraft = "", statusLookupRevision = 0;
const serviceTime = (value) => {
  const moment = new Date(value);
  return value && Number.isFinite(moment.getTime())
    ? new Intl.DateTimeFormat("id-ID", { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Jakarta" }).format(moment) + " WIB"
    : "Belum tersedia";
};
function processTracker(progress) {
  return documentStatusView(progress, { escape: esc, icon, formatTime: serviceTime });
}
const purposeLabels = {
  personal: "Informasi untuk diri sendiri",
  application: "Pengajuan fasilitas kredit/pembiayaan",
  correction: "Pemeriksaan dan koreksi data",
};
const publicPages = new Set([
  "account",
  "home",
  "result",
  "registration",
  "verify",
  "postkyc",
  "receipt",
  "status",
]);
function publicBrand() {
  return `<span class="public-wordmark"><span class="wordmark-symbol">i</span><span><b>deb</b>ku</span></span><span class="public-brand-divider"></span><span class="public-brand-label">INFORMASI DEBITUR<small>DEMO INTEGRASI LOKAL</small></span>`;
}
function publicHome() {
  return `<section class="public-home"><div class="home-brand">${publicBrand()}</div><span class="home-kicker">LAYANAN INFORMASI DEBITUR</span><h1>Selamat datang di aplikasi<br>permohonan informasi debitur</h1><p class="home-intro">Coba alur pendaftaran iDeb dengan verifikasi identitas<br class="desktop-break"> dan pemeriksaan wajah secara lokal.</p><div class="home-services"><div><button class="button public-register" data-page="registration">${icon("file")} Pendaftaran</button><p>Ajukan permohonan untuk perseorangan,<br>badan usaha, atau debitur meninggal dunia.</p></div><div><button class="button public-status" data-page="status">${icon("queue")} Status layanan</button><p>Lihat status pendaftaran demo<br>yang sudah Anda buat.</p></div></div><div class="home-demo-note">${icon("info")} Demo lokal. Pendaftaran tidak dikirim ke OJK.</div><button class="button link" data-preview-postkyc>Pratinjau alur setelah KYC ${icon("arrow")}</button></section>`;
}
function registrationHeader(number, title, subtitle) {
  return `<div class="registration-heading"><span>${number}</span><div><h1>${title}</h1><p>${subtitle}</p></div></div>`;
}
function publicRegistration() {
  const kind = applicationContext.debtorType;
  return `<section class="public-form-panel process-page">${registrationHeader(1, "Cek ketersediaan layanan", "Pilih jenis debitur untuk memulai pendaftaran.")}<form id="debtor-form"><div class="form-grid"><div class="field"><label for="debtor-type">Jenis debitur <em>*</em></label><select id="debtor-type" name="debtorType" required>${Object.entries(
    debtorTypes,
  )
    .map(
      ([key, name]) =>
        `<option value="${key}" ${kind === key ? "selected" : ""}>${name}</option>`,
    )
    .join(
      "",
    )}</select></div><div class="field"><label for="debtor-citizenship">${kind === "business" ? "Kategori badan usaha" : "Kewarganegaraan debitur"} <em>*</em></label><select id="debtor-citizenship"><option>${kind === "business" ? "Badan usaha Indonesia" : "Warga Negara Indonesia"}</option></select></div><div class="field"><label for="debtor-identity-type">Jenis identitas debitur</label><input id="debtor-identity-type" value="${kind === "business" ? "NPWP badan usaha (mock)" : "Kartu Tanda Penduduk (KTP)"}" readonly></div><div class="field"><label for="debtor-identity-number">Nomor identitas debitur</label><input id="debtor-identity-number" placeholder="${kind === "individual" ? "Diisi otomatis dari OCR KTP" : "Jalur dokumen masih berupa mock"}" readonly><small class="field-help">${kind === "individual" ? "NIK mengikuti pembacaan KTP; tidak perlu diketik ulang." : "Demo ini tidak memvalidasi identitas pada jalur ini."}</small></div></div><div class="registration-notice ${kind === "individual" ? "" : "neutral"}">${icon(kind === "individual" ? "verify" : "file")}<div><strong>${kind === "individual" ? "Verifikasi identitas perseorangan" : "Pendaftaran dokumen"}</strong><p>${kind === "individual" ? "Anda akan membaca KTP, melakukan liveness, dan mengambil foto diri bersama KTP. Persetujuan dan puzzle keamanan muncul sebelum verifikasi." : "Jalur ini menampilkan mock formulir dokumen. KYC dan liveness tidak dijalankan untuk jenis debitur ini."}</p></div></div><div class="registration-route">${kind === "individual" ? "Jenis debitur → KYC & liveness → Data permohonan → Konfirmasi" : "Jenis debitur → Data permohonan → Dokumen pendukung → Bukti pendaftaran"}</div><p class="text-error" id="step-error" role="alert"></p><div class="form-actions"><button type="button" class="button" data-page="home">Kembali</button><button class="button service-primary" type="submit">Selanjutnya ${icon("arrow")}</button></div></form><div class="public-form-footnote">Demo integrasi. Ketersediaan layanan dan pendaftaran OJK tidak diperiksa pada aplikasi lokal ini.</div></section>`;
}
function draftDefaults(preview) {
  return {
    name: preview
      ? "PEMOHON DEMO"
      : registrationIdentity?.name || selectedApplication?.name || flow?.ocr?.fields?.name || "",
    email: preview ? "pemohon@example.com" : "",
    phone: preview ? "081234567890" : "",
    address: preview
      ? "Jalan Contoh No. 1, Jakarta"
      : registrationIdentity?.address || flow?.ocr?.fields?.address || "",
    purpose: "personal",
  };
}
function canContinueAfterKyc() {
  return (
    applicationContext.preview ||
    applicationContext.debtorType !== "individual" ||
    approvedStates.includes(
      selectedApplication?.state || flow?.result?.application?.state,
    )
  );
}
function postKycView() {
  if (!canContinueAfterKyc())
    return `<section class="public-form-panel">${registrationHeader(2, "Verifikasi diperlukan", "Selesaikan KYC sebelum mengisi data permohonan.")}<button class="button primary" data-page="verify">Kembali ke verifikasi</button></section>`;
  const draft = registrationDraft || draftDefaults(applicationContext.preview);
  const preview = applicationContext.preview;
  const individual = applicationContext.debtorType === "individual";
  const state = preview
    ? "Pratinjau alur · KYC belum dijalankan"
    : individual
      ? "KYC lokal terpenuhi"
      : "Mock pendaftaran dokumen";
  return `<section class="public-form-panel process-page">${registrationHeader(registrationStep ? 3 : 2, registrationStep ? "Dokumen pendukung dan konfirmasi" : "Data registrasi", debtorTypes[applicationContext.debtorType])}<div class="registration-steps"><span class="done">✓ Jenis debitur</span>${individual ? `<span class="${preview ? "preview" : "done"}">${preview ? "◌ Pratinjau" : "✓ KYC & liveness"}</span>` : ""}<span class="${registrationStep ? "done" : "current"}">${registrationStep ? "✓" : "2"} Data registrasi</span><span class="${registrationStep ? "current" : ""}">3 Dokumen & konfirmasi</span></div><div class="registration-notice ${preview || !individual ? "neutral" : "success"}">${icon(preview ? "info" : individual ? "check" : "file")}<div><strong>${state}</strong><p>${preview ? "Ini hanya contoh tampilan setelah verifikasi. Tidak ada hasil KYC yang dibuat atau diluluskan." : individual ? "Pemeriksaan capture lokal berhasil. Dukcapil lolos simulasi; identitas resmi belum diverifikasi." : "Alur ini memakai formulir demo tanpa pemeriksaan wajah."}</p></div></div>${registrationStep ? registrationReview(draft) : registrationFields(draft)}<div class="public-form-footnote">Data disimpan pada server lokal untuk demo. Tidak ada permohonan atau email yang dikirim ke OJK.</div></section>`;
}
function registrationFields(draft) {
  const kind = applicationContext.debtorType;
  const identity = applicationContext.preview
    ? { nik: "1234567890123456", birth: "1990-01-01" }
    : registrationIdentity || {};
  const locked = kind === "individual" && !applicationContext.preview;
  return `<form id="registration-data-form"><div class="registration-form-columns"><div><div class="field"><label for="registration-identity">Jenis identitas debitur</label><input id="registration-identity" value="${kind === "business" ? "NPWP badan usaha — mock" : "KTP"}" readonly></div>${kind === "individual" ? `<div class="field"><label for="registration-nik">Nomor identitas debitur</label><input id="registration-nik" value="${esc(identity.nik)}" readonly><small class="field-help">${applicationContext.preview ? "Nomor sintetis untuk pratinjau." : "Mengikuti bukti KTP yang disimpan server."}</small></div>` : ""}<div class="field"><label for="registration-name">${kind === "business" ? "Nama badan usaha" : "Nama lengkap debitur"} <em>*</em></label><input id="registration-name" name="name" value="${esc(draft.name)}" required minlength="2" maxlength="100" autocomplete="name" ${locked ? "readonly" : ""}></div>${kind === "individual" ? `<div class="field"><label for="registration-birth">Tanggal lahir debitur</label><input id="registration-birth" value="${esc(identity.birth)}" type="date" readonly></div>` : ""}<div class="field"><label for="registration-address">Alamat debitur <em>*</em></label><textarea id="registration-address" name="address" minlength="5" maxlength="250" required autocomplete="street-address" rows="2">${esc(draft.address)}</textarea></div></div><div><div class="field"><label for="registration-email">Alamat email aktif <em>*</em></label><input id="registration-email" name="email" value="${esc(draft.email)}" type="email" maxlength="120" required autocomplete="email"><small class="field-help">Disimpan sebagai data demo; tidak ada email yang dikirim.</small></div><div class="field"><label for="registration-phone">Nomor handphone <em>*</em></label><input id="registration-phone" name="phone" value="${esc(draft.phone)}" type="tel" inputmode="tel" pattern="\\+?[0-9]{9,16}" required autocomplete="tel" placeholder="08xxxxxxxxxx"></div><div class="field"><label for="registration-purpose">Tujuan permohonan informasi debitur <em>*</em></label><select id="registration-purpose" name="purpose">${Object.entries(purposeLabels).map(([key, label]) => `<option value="${key}" ${draft.purpose === key ? "selected" : ""}>${label}</option>`).join("")}</select></div><div class="registration-data-note">${icon("info")}<div><strong>${applicationContext.preview ? "Data contoh pratinjau" : "Data identitas dari KTP"}</strong><p>${applicationContext.preview ? "Nama, NIK, dan tanggal lahir pada pratinjau ini adalah data sintetis." : kind === "individual" ? "Nama, NIK, dan tanggal lahir mengikuti data KTP server. Formulir ini melengkapi kontak dan tujuan permohonan." : "Jalur badan usaha dan debitur meninggal dunia masih berupa contoh formulir dokumen."}</p></div></div></div></div>${kind !== "individual" ? `<div class="document-checklist"><h3>Dokumen pendukung — mock</h3><p>${kind === "business" ? "Contoh tahap untuk NPWP badan usaha, akta perusahaan, identitas pengurus, dan surat kuasa." : "Contoh tahap untuk identitas debitur, identitas ahli waris, bukti kematian, dan bukti hubungan keluarga."}</p><label><input type="checkbox" name="documents" required> Saya memahami tahap unggah dokumen pada jalur ini masih berupa mock.</label></div>` : ""}<p class="text-error" id="step-error" role="alert"></p><div class="form-actions"><button type="button" class="button" data-page="registration">Kembali</button><button class="button service-primary" type="submit">Selanjutnya ${icon("arrow")}</button></div></form>`;
}
function documentIllustration(kind) {
  const card = '<rect x="65" y="86" width="54" height="33" rx="4" fill="#d8edf7" stroke="#3378a0"/><path d="M72 95h22m-22 6h16m-16 6h20" stroke="#3378a0"/><circle cx="107" cy="97" r="5" fill="#3378a0"/>';
  return `<svg viewBox="0 0 180 140" role="img" aria-label="Panduan ${kind === "document" ? "KTP" : kind === "holding" ? "foto memegang KTP" : "wajah di kamera"}">${kind === "document" ? '<rect x="22" y="26" width="136" height="88" rx="8" fill="#d8edf7" stroke="#3378a0" stroke-width="2"/><path d="M34 43h75m-75 15h60m-60 12h53m-53 12h48m-48 12h65" stroke="#3378a0" stroke-width="3"/><circle cx="133" cy="64" r="14" fill="#88b6cf"/><path d="M115 97c0-27 36-27 36 0" fill="#88b6cf"/>' : `<circle cx="90" cy="42" r="25" fill="#e8c7ae"/><path d="M63 34c3-32 52-31 54 0" fill="#364756"/><path d="M39 136c0-81 102-81 102 0" fill="#3378a0"/>${kind === "holding" ? card + '<path d="M53 109h19m45 0h10" stroke="#e8c7ae" stroke-width="14" stroke-linecap="round"/>' : '<path d="M20 30V15h20m100 0h20v15m0 80v15h-20m-100 0H20v-15" fill="none" stroke="#a93033" stroke-width="3"/>'}`}</svg>`;
}
function supportingDocuments() {
  if (applicationContext.debtorType !== "individual") return "";
  const captured = !applicationContext.preview && canContinueAfterKyc();
  const sameApplication = flow?.session?.application_id === selectedApplication?.id;
  return `<div class="supporting-documents"><h2>Dokumen pendukung</h2><p>Bukti diambil pada tahap KYC. Pengambilan kamera berjalan otomatis saat persyaratan terpenuhi.</p><div class="supporting-document-grid">${[
    ["document", "Identitas asli (KTP)", "NIK, nama, tanggal lahir, dan potret kartu."],
    ["holding", "Foto diri dengan identitas asli", "Wajah, kartu, NIK, dan tangan diperiksa bersama."],
    ["selfie", "Rekaman liveness", "Gerakan mata, arah kepala, dan senyum diperiksa oleh server."],
  ].map(([kind, title, description]) => `<article><h3>${title}</h3><div class="supporting-document-image">${captured && sameApplication && flow[kind + "URL"] ? `<img src="${esc(flow[kind + "URL"])}" alt="Pratinjau ${title}">` : documentIllustration(kind)}</div><span class="badge ${captured ? "green" : "gray"}">${captured ? "Bukti KYC tersedia di server" : "Panduan · bukan bukti verifikasi"}</span><p>${description}</p></article>`).join("")}</div></div>`;
}
function registrationReview(draft) {
  return `${supportingDocuments()}<form id="registration-submit-form"><h2 class="registration-review-title">Tinjau data permohonan</h2><dl class="registration-summary">${[
    ["Jenis debitur", debtorTypes[applicationContext.debtorType]], ["Nama", draft.name],
    ["Email", draft.email], ["Nomor ponsel", draft.phone], ["Alamat", draft.address],
    ["Tujuan", purposeLabels[draft.purpose]],
  ].map(([label, value]) => `<div><dt>${label}</dt><dd>${esc(value)}</dd></div>`).join("")}</dl><label class="registration-agreement"><input type="checkbox" required> Saya telah meninjau data dan setuju menyimpan permohonan demo pada server lokal ini.</label><p class="text-error" id="step-error" role="alert"></p><div class="form-actions"><button type="button" class="button" data-edit-registration>Kembali ke data</button><button class="button service-primary" type="submit" ${registrationSubmitting ? "disabled" : ""}>${registrationSubmitting ? "Menyimpan…" : "Kirim pendaftaran demo"} ${icon("arrow")}</button></div></form>`;
}
function receiptView() {
  if (!registrationReceipt) return publicStatus();
  const r = registrationReceipt;
  return `<section class="public-form-panel receipt-panel"><div class="receipt-symbol">${icon("check")}</div><span class="home-kicker">BUKTI PENDAFTARAN DEMO</span><h1>Permohonan demo diterima</h1><p>Simpan nomor ini untuk melihat status layanan di aplikasi lokal.</p><div class="receipt-number"><small>NOMOR PENDAFTARAN</small><strong>${esc(r.id)}</strong></div><dl class="registration-summary"><div><dt>Pemohon</dt><dd>${esc(r.name)}</dd></div><div><dt>Jenis debitur</dt><dd>${debtorTypes[r.debtor_type]}</dd></div><div><dt>Waktu pendaftaran</dt><dd>${date(r.created)} WIB</dd></div><div><dt>Status</dt><dd><span class="badge orange">Diterima — mock</span></dd></div><div><dt>Verifikasi wajah</dt><dd>${r.kyc === "local_checks_passed" ? "Kontrol lokal terpenuhi" : r.kyc === "preview" ? "Pratinjau; KYC belum dijalankan" : "Tidak berlaku untuk jenis debitur ini"}</dd></div></dl><div class="registration-notice neutral">${icon("info")}<p>Ini bukan bukti pendaftaran OJK. ${r.application_id ? "Status penerbitan PDF SLIK demo mengikuti permohonan KYC yang terhubung. Dukcapil hanya lolos simulasi." : "Tidak ada laporan SLIK yang diterbitkan pada jalur mock/pratinjau ini."} Tidak ada email yang dikirim.</p></div><div class="receipt-actions"><button class="button" data-copy-registration>Salin kode pendaftaran</button><button class="button" data-download-receipt>${icon("download")} Unduh bukti demo</button><button class="button primary" data-page="status">Cek status layanan</button><button class="button link" data-page="home">Kembali ke beranda</button></div></section>`;
}
function serviceApplication() {
  const app = serviceStatus?.application;
  return app && selectedApplication?.id === app.id ? selectedApplication : app;
}
function serviceStatusDetails() {
  if (!serviceStatus) return "";
  const app = serviceApplication();
  const progress = app?.document_progress || serviceStatus.document_progress;
  const state = app?.state;
  return `<section class="service-request-summary"><div class="field"><label>Nomor pendaftaran / permohonan</label><div class="service-readonly">${esc(serviceStatus.id)}</div></div><div class="field"><label>Nama lengkap sesuai identitas</label><div class="service-readonly">${esc(app?.name || serviceStatus.name || "Identitas belum dibaca")}</div></div><div class="field"><label>Status layanan</label><div class="service-readonly">${esc(stateLabels[state] || "Formulir demo diterima — belum diverifikasi")}</div></div></section>${processTracker(progress)}${app ? `<div class="service-status-note" role="status"><strong>${esc(stateLabels[state] || state)}</strong><p>${esc(app.reason || "Pemeriksaan berlangsung pada server lokal.")}</p>${app.reservation ? `<p>Jadwal helpdesk: ${esc(app.reservation.day)} · ${esc(app.reservation.window)} WIB</p>` : ""}${state === "MANUAL_PENDING" ? `<p>${esc(app.manual_admission?.message || "Pilih Cek kuota hari ini untuk memeriksa ketersediaan pemeriksaan manual.")}</p>` : ""}${["REJECTED", "MANUAL_REJECTED"].includes(state) ? `<p>${esc(app.appeal)}</p>` : ""}</div>` : '<p class="service-status-note">Pendaftaran ini berupa mock/pratinjau. Tahap review dan penerbitan PDF tidak dijalankan.</p>'}<div class="service-status-actions"><button class="button" data-refresh-service>Perbarui status</button>${state === "MANUAL_PENDING" ? `<button class="button service-primary" data-try-today="${esc(app.id)}">Cek kuota hari ini</button>` : ""}${state === "MANUAL_SCHEDULED" ? `<button class="button danger" data-cancel-case="${esc(app.id)}">Batalkan reservasi</button>` : ""}${["CAPTURE_RETRY", "TECHNICAL_PENDING", "VERIFYING"].includes(state) ? `<button class="button service-primary" data-service-retry="${esc(app.id)}">${state === "CAPTURE_RETRY" ? "Perbaiki tahap yang diminta" : "Lanjutkan verifikasi"}</button>` : ""}${approvedStates.includes(state) ? `<button class="button service-primary" data-slik="${esc(app.id)}">${state === "SLIK_READY" ? "Unduh ulang PDF SLIK demo" : "Coba siapkan PDF kembali"}</button>` : ""}<button class="button" data-page="home">Kembali</button></div><p class="public-form-footnote">Status manual diperbarui otomatis setiap 5 detik selama halaman terbuka. PDF diunduh setelah tersedia. Tidak terhubung ke layanan OJK.</p>`;
}
function publicStatus() {
  let active = "";
  try { active = sessionStorage.getItem("mock_id_active_application") || ""; } catch {}
  return `<section class="public-form-panel process-page service-status-page"><header class="service-status-heading"><h1>Status layanan permintaan iDeb</h1><p>Masukkan nomor pendaftaran untuk memantau proses dokumen Anda.</p></header><form id="registration-status-form" class="service-status-lookup"><div class="field"><label for="registration-number">Nomor pendaftaran <em>*</em></label><input id="registration-number" name="registration_id" placeholder="APP-… atau DEMO-…" value="${esc(statusNumberDraft || serviceStatus?.id || registrationReceipt?.id || active)}" required maxlength="30" autocapitalize="characters" spellcheck="false"><small class="field-help">Permohonan dapat diakses melalui browser pemilik yang sama.</small></div><button type="submit" class="button service-primary">Cek status ${icon("arrow")}</button><p class="text-error" id="step-error" role="alert"></p></form><div id="service-status-result">${serviceStatusDetails()}</div>${!serviceStatus ? '<div class="service-status-empty">Belum ada status yang ditampilkan. Masukkan nomor permohonan, lalu pilih Cek status.</div><div class="form-actions"><button class="button" data-page="home">Kembali</button></div>' : ""}</section>`;
}
function updateServiceStatus() {
  const target = document.querySelector("#service-status-result");
  if (target) target.innerHTML = serviceStatusDetails();
  else render();
}
async function loadServiceStatus(id) {
  const requestRevision = ++statusLookupRevision, owner = authEpoch, navigation = navigationRevision, targetPage = page;
  stopDeliveryWatch();
  const stale = () => requestRevision !== statusLookupRevision || owner !== authEpoch || navigation !== navigationRevision || page !== targetPage;
  let result;
  try {
    result = id.startsWith("APP-")
      ? await api("/applications/" + encodeURIComponent(id))
      : await api("/registrations/" + encodeURIComponent(id));
  } catch (error) {
    if (stale()) return false;
    throw error;
  }
  if (stale()) return false;
  serviceStatus = id.startsWith("APP-") ? { id: result.id, application: result } : result;
  selectedApplication = serviceStatus.application || null;
  statusNumberDraft = serviceStatus.id;
  if (selectedApplication) rememberApplication(selectedApplication.id);
  return true;
}
async function startPostKycRegistration(app) {
  const owner = authEpoch, navigation = navigationRevision;
  const identity = await api(`/applications/${encodeURIComponent(app.id)}/registration-context`);
  if (owner !== authEpoch || navigation !== navigationRevision) return;
  applicationContext = { debtorType: "individual", preview: false };
  registrationIdentity = identity;
  registrationDraft = draftDefaults(false);
  registrationStep = 0;
  await goPublic("postkyc");
}
function showRegistrationSuccess() {
  modal("Pendaftaran berhasil — demo", `<div class="registration-success"><div class="receipt-symbol">${icon("check")}</div><h2>Pendaftaran demo berhasil</h2><p>Nomor pendaftaran Anda:</p><strong>${esc(registrationReceipt.id)}</strong><p>Salin nomor ini untuk memantau status di browser yang sama.</p><div class="buttons"><button class="button success-button" data-copy-registration>Salin kode pendaftaran</button><button class="button" data-close>Tutup</button></div><small>Permohonan disimpan lokal. Bukan pendaftaran resmi OJK.</small></div>`);
}
async function goPublic(target) {
  await navigate(target);
}
function clearRegistrationState() {
  registrationIdentity = null;
  registrationDraft = null;
  registrationReceipt = null;
  registrationStep = 0;
  serviceStatus = null;
  statusNumberDraft = "";
  statusLookupRevision++;
}
document.addEventListener("click", async (event) => {
  const button = event.target.closest("button");
  if (!button || button.disabled) return;
  try {
    if (button.hasAttribute("data-preview-postkyc")) {
      applicationContext = { debtorType: "individual", preview: true };
      registrationIdentity = null;
      registrationDraft = draftDefaults(true);
      registrationStep = 0;
      await goPublic("postkyc");
    } else if (button.hasAttribute("data-continue-registration")) {
      if (!approvedStates.includes(flow?.result?.application?.state)) return;
      await startPostKycRegistration(flow.result.application);
    } else if (button.hasAttribute("data-edit-registration")) {
      registrationStep = 0;
      render();
    } else if (button.hasAttribute("data-download-receipt")) {
      exportFile(
        registrationReceipt.id + ".json",
        JSON.stringify(registrationReceipt, null, 2),
        "application/json",
      );
    } else if (button.hasAttribute("data-copy-registration")) {
      try {
        await navigator.clipboard.writeText(registrationReceipt.id);
        toast("Kode pendaftaran disalin.");
      } catch {
        toast("Browser belum mengizinkan penyalinan. Salin nomor yang terlihat pada dialog.");
      }
    } else if (button.hasAttribute("data-refresh-service")) {
      if (await loadServiceStatus(serviceStatus.id)) {
        render();
        await observeDelivery(selectedApplication);
      }
    } else if (button.dataset.serviceRetry) {
      if (flow?.session?.application_id === button.dataset.serviceRetry && flow.result && ["CAPTURE_RETRY", "TECHNICAL_PENDING"].includes(selectedApplication?.state)) {
        page = "verify";
        history.replaceState(null, "", "#verify");
        await retry();
      } else if (flow?.session?.application_id === button.dataset.serviceRetry) {
        await goPublic("verify");
      } else if (await newFlow(false, button.dataset.serviceRetry)) await goPublic("verify");
    } else if (button.hasAttribute("data-public-info")) {
      modal(
        "Informasi demo",
        `<p>Demo ini menunjukkan penyisipan modul OCR KTP, KYC dan liveness pada pendaftaran perseorangan. Badan usaha dan debitur meninggal dunia menggunakan jalur mock dokumen.</p><p>Permohonan disimpan lokal dan tidak dikirim ke OJK. Gunakan data contoh untuk mencoba mock formulir. Status pada demo bukan laporan SLIK.</p><button class="button primary" data-close>Saya mengerti</button>`,
      );
    }
  } catch (error) {
    errorMessage(error);
  }
});
document.addEventListener("change", (event) => {
  if (event.target.id === "debtor-type") {
    applicationContext = { debtorType: event.target.value, preview: false };
    registrationDraft = null;
    registrationIdentity = null;
    registrationStep = 0;
    render();
  }
});
document.addEventListener("input", (event) => {
  if (event.target.id === "registration-number") statusNumberDraft = event.target.value;
});
document.addEventListener("submit", async (event) => {
  const form = event.target;
  if (
    ![
      "debtor-form",
      "registration-data-form",
      "registration-submit-form",
      "registration-status-form",
    ].includes(form.id)
  )
    return;
  event.preventDefault();
  if (!form.checkValidity()) {
    form.reportValidity();
    return;
  }
  const data = Object.fromEntries(new FormData(form));
  try {
    if (form.id === "debtor-form") {
      selectedApplication = null;
      applicationContext = { debtorType: data.debtorType, preview: false };
      registrationStep = 0;
      registrationDraft = null;
      registrationIdentity = null;
      if (data.debtorType === "individual") {
        if (await newFlow(false)) await goPublic("verify");
      } else {
        registrationDraft = {
          name: "",
          email: "",
          phone: "",
          address: "",
          purpose: "personal",
        };
        await goPublic("postkyc");
      }
    } else if (form.id === "registration-data-form") {
      registrationDraft = data;
      registrationStep = 1;
      render();
      window.scrollTo(0, 0);
    } else if (form.id === "registration-submit-form") {
      if (registrationSubmitting) return;
      if (!canContinueAfterKyc())
        throw new Error("KYC harus diselesaikan terlebih dahulu.");
      registrationSubmitting = true;
      render();
      try {
        const realIndividual =
          !applicationContext.preview &&
          applicationContext.debtorType === "individual";
        registrationReceipt = await api("/registrations", {
          method: "POST",
          body: JSON.stringify({
            ...registrationDraft,
            debtor_type: applicationContext.debtorType,
            preview: applicationContext.preview,
            ...(realIndividual
              ? {
                  application_id:
                    selectedApplication?.id || flow?.session?.application_id,
                  session_id: flow?.session?.id,
                  verification_id:
                    selectedApplication?.verification_id || flow?.result?.id,
                }
              : {}),
          }),
        });
        await goPublic("receipt");
        statusNumberDraft = registrationReceipt.id;
        serviceStatus = null;
        showRegistrationSuccess();
      } finally {
        registrationSubmitting = false;
        render();
      }
    } else {
      const requestedId = data.registration_id.trim().toUpperCase();
      statusNumberDraft = requestedId;
      const submit = form.querySelector('button[type="submit"]');
      submit.disabled = true;
      try {
        if (await loadServiceStatus(requestedId)) {
          render();
          await observeDelivery(selectedApplication);
        }
      } finally {
        if (submit.isConnected) submit.disabled = false;
      }
    }
  } catch (error) {
    errorMessage(error);
  }
});
