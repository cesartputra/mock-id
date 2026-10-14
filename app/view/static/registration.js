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
  return `<section class="public-form-panel">${registrationHeader(1, "Cek ketersediaan layanan", "Pilih jenis debitur untuk memulai pendaftaran.")}<form id="debtor-form"><div class="field"><label for="debtor-type">Jenis debitur <em>*</em></label><select id="debtor-type" name="debtorType" required>${Object.entries(
    debtorTypes,
  )
    .map(
      ([key, name]) =>
        `<option value="${key}" ${kind === key ? "selected" : ""}>${name}</option>`,
    )
    .join(
      "",
    )}</select></div><div class="field"><label for="debtor-citizenship">${kind === "business" ? "Kategori badan usaha" : "Kewarganegaraan debitur"} <em>*</em></label><select id="debtor-citizenship"><option>${kind === "business" ? "Badan usaha Indonesia" : "Warga Negara Indonesia"}</option></select></div><div class="field"><label for="debtor-identity-type">Jenis identitas debitur</label><input id="debtor-identity-type" value="${kind === "business" ? "NPWP badan usaha (mock)" : "Kartu Tanda Penduduk (KTP)"}" readonly></div><div class="registration-notice ${kind === "individual" ? "" : "neutral"}">${icon(kind === "individual" ? "verify" : "file")}<div><strong>${kind === "individual" ? "Verifikasi identitas perseorangan" : "Pendaftaran dokumen"}</strong><p>${kind === "individual" ? "Anda akan membaca KTP, melakukan liveness, dan mengambil foto diri bersama KTP sebelum melanjutkan." : "Jalur ini menampilkan mock formulir dokumen. KYC dan liveness tidak dijalankan untuk jenis debitur ini."}</p></div></div><div class="registration-route">${kind === "individual" ? "Jenis debitur → KYC & liveness → Data permohonan → Bukti pendaftaran" : "Jenis debitur → Data permohonan → Dokumen pendukung → Bukti pendaftaran"}</div><p class="text-error" id="step-error" role="alert"></p><div class="form-actions"><button type="button" class="button" data-page="home">Kembali</button><button class="button primary" type="submit">Lanjutkan ${icon("arrow")}</button></div></form><div class="public-form-footnote">Demo integrasi. Ketersediaan layanan dan pendaftaran OJK tidak diperiksa pada aplikasi lokal ini.</div></section>`;
}
function draftDefaults(preview) {
  return {
    name: preview
      ? "PEMOHON DEMO"
      : selectedApplication?.name || flow?.ocr?.fields?.name || "",
    email: preview ? "pemohon@example.com" : "",
    phone: preview ? "081234567890" : "",
    address: preview
      ? "Jalan Contoh No. 1, Jakarta"
      : flow?.ocr?.fields?.address || "",
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
  return `<section class="public-form-panel wide">${registrationHeader(registrationStep ? 3 : 2, registrationStep ? "Tinjau permohonan" : "Lengkapi data permohonan", debtorTypes[applicationContext.debtorType])}<div class="registration-steps"><span class="done">✓ Jenis debitur</span>${individual ? `<span class="${preview ? "preview" : "done"}">${preview ? "◌ Pratinjau" : "✓ KYC & liveness"}</span>` : ""}<span class="${registrationStep ? "done" : "current"}">${registrationStep ? "✓" : "2"} Data permohonan</span><span class="${registrationStep ? "current" : ""}">3 Konfirmasi</span></div><div class="registration-notice ${preview || !individual ? "neutral" : "success"}">${icon(preview ? "info" : individual ? "check" : "file")}<div><strong>${state}</strong><p>${preview ? "Ini hanya contoh tampilan setelah verifikasi. Tidak ada hasil KYC yang dibuat atau diluluskan." : individual ? "Pemeriksaan capture lokal berhasil. Identitas resmi Dukcapil tetap belum diverifikasi." : "Alur ini memakai formulir demo tanpa pemeriksaan wajah."}</p></div></div>${registrationStep ? registrationReview(draft) : registrationFields(draft)}<div class="public-form-footnote">Data disimpan pada server lokal untuk demo. Tidak ada permohonan atau email yang dikirim ke OJK.</div></section>`;
}
function registrationFields(draft) {
  const kind = applicationContext.debtorType;
  return `<form id="registration-data-form"><div class="form-grid"><div class="field wide"><label for="registration-name">${kind === "business" ? "Nama badan usaha" : "Nama pemohon"} <em>*</em></label><input id="registration-name" name="name" value="${esc(draft.name)}" required minlength="2" maxlength="100" autocomplete="name" ${kind === "individual" && !applicationContext.preview ? "readonly" : ""}></div><div class="field"><label for="registration-email">Email tujuan <em>*</em></label><input id="registration-email" name="email" value="${esc(draft.email)}" type="email" maxlength="120" required autocomplete="email"></div><div class="field"><label for="registration-phone">Nomor ponsel <em>*</em></label><input id="registration-phone" name="phone" value="${esc(draft.phone)}" type="tel" inputmode="tel" pattern="\\+?[0-9]{9,16}" required autocomplete="tel" placeholder="08xxxxxxxxxx"></div><div class="field wide"><label for="registration-address">Alamat pemohon <em>*</em></label><input id="registration-address" name="address" value="${esc(draft.address)}" minlength="5" maxlength="250" required autocomplete="street-address"></div><div class="field wide"><label for="registration-purpose">Tujuan permohonan <em>*</em></label><select id="registration-purpose" name="purpose">${Object.entries(
    purposeLabels,
  )
    .map(
      ([key, label]) =>
        `<option value="${key}" ${draft.purpose === key ? "selected" : ""}>${label}</option>`,
    )
    .join(
      "",
    )}</select></div></div>${kind !== "individual" ? `<div class="document-checklist"><h3>Dokumen pendukung — mock</h3><p>${kind === "business" ? "Contoh tahap untuk NPWP badan usaha, akta perusahaan, identitas pengurus, dan surat kuasa." : "Contoh tahap untuk identitas debitur, identitas ahli waris, bukti kematian, dan bukti hubungan keluarga."}</p><label><input type="checkbox" name="documents" required> Saya memahami tahap unggah dokumen pada jalur ini masih berupa mock.</label></div>` : ""}<p class="text-error" id="step-error" role="alert"></p><div class="form-actions"><button type="button" class="button" data-page="registration">Kembali</button><button class="button primary" type="submit">Tinjau permohonan ${icon("arrow")}</button></div></form>`;
}
function registrationReview(draft) {
  return `<form id="registration-submit-form"><dl class="registration-summary">${[
    ["Jenis debitur", debtorTypes[applicationContext.debtorType]],
    ["Nama", draft.name],
    ["Email", draft.email],
    ["Nomor ponsel", draft.phone],
    ["Alamat", draft.address],
    ["Tujuan", purposeLabels[draft.purpose]],
  ]
    .map(
      ([label, value]) => `<div><dt>${label}</dt><dd>${esc(value)}</dd></div>`,
    )
    .join(
      "",
    )}</dl><label class="registration-agreement"><input type="checkbox" required> Saya telah meninjau data dan setuju menyimpan permohonan demo pada server lokal ini.</label><p class="text-error" id="step-error" role="alert"></p><div class="form-actions"><button type="button" class="button" data-edit-registration>Kembali ke data</button><button class="button primary" type="submit" ${registrationSubmitting ? "disabled" : ""}>${registrationSubmitting ? "Menyimpan…" : "Kirim pendaftaran demo"} ${icon("arrow")}</button></div></form>`;
}
function receiptView() {
  if (!registrationReceipt) return publicStatus();
  const r = registrationReceipt;
  return `<section class="public-form-panel receipt-panel"><div class="receipt-symbol">${icon("check")}</div><span class="home-kicker">BUKTI PENDAFTARAN DEMO</span><h1>Permohonan demo diterima</h1><p>Simpan nomor ini untuk melihat status layanan di aplikasi lokal.</p><div class="receipt-number"><small>NOMOR PENDAFTARAN</small><strong>${esc(r.id)}</strong></div><dl class="registration-summary"><div><dt>Pemohon</dt><dd>${esc(r.name)}</dd></div><div><dt>Jenis debitur</dt><dd>${debtorTypes[r.debtor_type]}</dd></div><div><dt>Waktu pendaftaran</dt><dd>${date(r.created)} WIB</dd></div><div><dt>Status</dt><dd><span class="badge orange">Diterima — mock</span></dd></div><div><dt>Verifikasi wajah</dt><dd>${r.kyc === "local_checks_passed" ? "Kontrol lokal terpenuhi" : r.kyc === "preview" ? "Pratinjau; KYC belum dijalankan" : "Tidak berlaku untuk jenis debitur ini"}</dd></div></dl><div class="registration-notice neutral">${icon("info")}<p>Ini bukan bukti pendaftaran OJK. Tidak ada laporan SLIK yang diterbitkan atau email yang dikirim. Pengecekan Dukcapil belum dilakukan.</p></div><div class="receipt-actions"><button class="button" data-download-receipt>${icon("download")} Unduh bukti demo</button><button class="button primary" data-page="status">Cek status layanan</button><button class="button link" data-page="home">Kembali ke beranda</button></div></section>`;
}
function publicStatus() {
  return `<section class="public-form-panel">${registrationHeader("?", "Status layanan", "Masukkan nomor permohonan untuk mengecek pemeriksaan atau mengunduh PDF.")}<form id="registration-status-form"><div class="field"><label for="registration-number">Nomor permohonan / pendaftaran <em>*</em></label><input id="registration-number" name="registration_id" placeholder="APP-… atau DEMO-…" value="${esc(registrationReceipt?.id || "")}" required maxlength="30"></div><p class="text-error" id="step-error" role="alert"></p><div class="form-actions"><button type="button" class="button" data-page="home">Kembali</button><button type="submit" class="button primary">Cek status ${icon("arrow")}</button></div></form></section>`;
}
async function goPublic(target) {
  location.hash = target;
  await navigate(target);
}
document.addEventListener("click", async (event) => {
  const button = event.target.closest("button");
  if (!button || button.disabled) return;
  try {
    if (button.hasAttribute("data-preview-postkyc")) {
      applicationContext = { debtorType: "individual", preview: true };
      registrationDraft = draftDefaults(true);
      registrationStep = 0;
      await goPublic("postkyc");
    } else if (button.hasAttribute("data-continue-registration")) {
      if (!approvedStates.includes(flow?.result?.application?.state)) return;
      applicationContext = { debtorType: "individual", preview: false };
      registrationDraft = draftDefaults(false);
      registrationStep = 0;
      await goPublic("postkyc");
    } else if (button.hasAttribute("data-edit-registration")) {
      registrationStep = 0;
      render();
    } else if (button.hasAttribute("data-download-receipt")) {
      exportFile(
        registrationReceipt.id + ".json",
        JSON.stringify(registrationReceipt, null, 2),
        "application/json",
      );
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
    registrationStep = 0;
    render();
  }
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
      } finally {
        registrationSubmitting = false;
        render();
      }
    } else {
      const requestedId = data.registration_id.trim().toUpperCase();
      if (requestedId.startsWith("APP-")) {
        selectedApplication = await api(
          "/applications/" + encodeURIComponent(requestedId),
        );
        rememberApplication(selectedApplication.id);
        await goPublic("result");
        return;
      }
      registrationReceipt = await api(
        `/registrations/${encodeURIComponent(data.registration_id.trim().toUpperCase())}`,
      );
      await goPublic("receipt");
    }
  } catch (error) {
    errorMessage(error);
  }
});
