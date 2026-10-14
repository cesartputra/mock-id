"use strict";
let operatorQuery = "", operatorFilter = "all", cleanupPlan = null;
const operatorPages = new Set(["dashboard", "queue", "audit", "modules"]);
function updateOperatorNav() {
  const active = operatorPages.has(page);
  document.body.classList.toggle("operator-mode", active);
  const nav = $("#operator-nav");
  if (!nav) return;
  nav.hidden = !active;
  if (!active) { cleanupPlan = null; return; }
  const tabs = principal?.role === "helpdesk"
    ? [["queue", "Kasus helpdesk"]]
    : [["dashboard", "Ringkasan"], ["queue", "Data pemohon"], ["audit", "Jejak aktivitas"], ["modules", "Modul & konfigurasi"]];
  nav.innerHTML = tabs.map(([key, label]) => `<button data-page="${key}" class="${key === page ? "active" : ""}" ${key === page ? 'aria-current="page"' : ""}>${icon(key)}${label}</button>`).join("");
  const account = $("#operator-account-label");
  if (account) account.textContent = `${principal?.login || "Operator"} · ${principal?.role || ""}`;
}
function operatorHeading(number, title, text) {
  return registrationHeader(number, title, text);
}
function operatorTable(rows) {
  return `<div class="operator-table-scroll"><table class="operator-table"><thead><tr><th>Pemohon</th><th>Status permohonan</th><th>Skor demo</th><th>Diperbarui</th><th>Tindakan</th></tr></thead><tbody>${rows.map(app => `<tr><td><strong>${esc(app.name || "Identitas belum dibaca")}</strong><small>${esc(app.nik_masked || "—")}<br>${esc(app.id)}</small></td><td><span class="badge ${app.state === "SLIK_READY" ? "green" : app.state.startsWith("MANUAL_") ? "orange" : "blue"}">${esc(stateLabels[app.state] || app.state)}</span></td><td>${typeof app.routing?.routing_score === "number" ? (Math.floor(app.routing.routing_score * 100) / 100).toFixed(2) + "/100" : "—"}</td><td>${date(app.updated)} WIB</td><td><button class="button service-primary" data-application="${esc(app.id)}">Lihat bukti</button>${principal?.role === "admin" ? `<button class="button cleanup-button" data-cleanup="${esc(app.id)}">Clean data</button>` : ""}</td></tr>`).join("") || '<tr><td colspan="5" class="empty">Tidak ada permohonan yang sesuai.</td></tr>'}</tbody></table></div>`;
}
function operatorDashboardView() {
  const counts = operatorMetrics?.volume || {};
  const total = Object.values(counts).reduce((a, b) => a + b, 0);
  const manual = Object.entries(counts).filter(([key]) => key.startsWith("MANUAL_")).reduce((a, [, b]) => a + b, 0);
  const latency = operatorMetrics?.verification_latency_ms_mean;
  return `<section class="operator-page">${operatorHeading(1, "Ringkasan layanan", "Workspace operator · pengelolaan permohonan, bukti, dan pemeriksaan manual")}<div class="operator-stats">${[["Total permohonan", total], ["PDF demo tersedia", counts.SLIK_READY || 0], ["Pemeriksaan manual", manual], ["Rata-rata verifikasi", latency == null ? "—" : (latency / 1000).toFixed(2) + " dtk"]].map(([label, value]) => `<div><span>${label}</span><strong>${value}</strong></div>`).join("")}</div><div class="operator-overview"><section class="panel config-panel"><h2>Permohonan dan bukti</h2><p>Tinjau foto asli, crop KTP, selfie, dan hasil verifikasi pada satu permohonan.</p><div class="buttons"><button class="button service-primary" data-page="queue">Buka data pemohon</button><button class="button" data-page="modules">Konfigurasi layanan</button></div><p class="state-note">Clean data hanya tersedia bagi administrator. Penghapusan tidak mencakup permohonan lain, termasuk pemohon dengan NIK yang sama.</p></section><section class="panel config-panel"><h2>Server lokal</h2><div class="result-control"><span>Bobot model</span><span class="badge ${workspace.health.ready ? "green" : "orange"}">${workspace.health.ready ? "Tersedia" : "Perlu setup"}</span></div><div class="result-control"><span>Anti-spoof</span><span>${esc(padRuntimeLabel())}</span></div><p class="state-note">Ambang routing demo ≥${workspace.routing_policy?.automatic_threshold ?? 50}/100. Dukcapil mock; laporan keuangan sintetis.</p></section></div><section class="panel operator-data-panel"><div class="panel-head"><h2>Permohonan terbaru</h2><button class="button" data-page="queue">Lihat semua</button></div>${operatorTable(applicationRows.slice(0, 5))}</section></section>`;
}
function operatorDataView() {
  const rows = applicationRows.filter(app =>
    (operatorFilter === "all" || (operatorFilter === "manual" ? app.state.startsWith("MANUAL_") : app.state === operatorFilter)) &&
    `${app.name || ""} ${app.id} ${app.nik_masked || ""}`.toLowerCase().includes(operatorQuery.toLowerCase()));
  return `<section class="operator-page">${operatorHeading(2, principal?.role === "admin" ? "Data pemohon dan pemeriksaan" : "Kasus pemeriksaan helpdesk", "Pilih satu permohonan untuk meninjau dokumen, hasil verifikasi, dan status layanan.")}<section class="panel operator-data-panel"><form id="operator-search-form" class="operator-filters"><div class="field"><label for="operator-search">Cari nama / nomor permohonan</label><input id="operator-search" name="query" value="${esc(operatorQuery)}" placeholder="Nama pemohon atau APP-…"></div><div class="field"><label for="operator-filter">Status layanan</label><select id="operator-filter" name="filter">${[["all", "Semua status"], ["manual", "Pemeriksaan manual"], ["SLIK_READY", "PDF tersedia"], ["CAPTURE_RETRY", "Perbaikan capture"], ["TECHNICAL_PENDING", "Gangguan teknis"]].map(([key, label]) => `<option value="${key}" ${operatorFilter === key ? "selected" : ""}>${label}</option>`).join("")}</select></div><button class="button service-primary">Tampilkan</button></form>${operatorTable(rows)}<p class="operator-table-note">${rows.length} permohonan ditampilkan · waktu Asia/Jakarta</p></section>${selectedApplication ? applicationPanel(selectedApplication, true) : '<div class="operator-selection-note">Pilih <strong>Lihat bukti</strong> untuk membuka detail permohonan.</div>'}${capacityCalendar ? capacitySummary(capacityCalendar) : ""}</section>`;
}
function operatorEvidenceView(app) {
  const images = (app.evidence || []).filter(e => !["identity", "verification", "manual-review"].includes(e.kind));
  const labels = {document: "Foto KTP asli", "document-crop": "Crop KTP · hanya area kartu", selfie: "Selfie pemohon", holding: "Foto memegang KTP"};
  const photo = e => `<figure>${e.deleted_at ? '<div class="deleted-photo">Foto telah dihapus</div>' : `<button class="evidence-image-button" data-photo="${esc(e.id)}" data-photo-title="${esc(labels[e.kind] || "Frame gerakan")}"><img src="/api/evidence/${encodeURIComponent(e.id)}" alt="${esc(labels[e.kind] || "Frame gerakan")}" loading="lazy"></button>`}<figcaption><strong>${esc(labels[e.kind] || "Frame gerakan " + (Number(e.kind.split("-")[1]) + 1))}</strong><small>${date(e.created)} WIB · versi ${e.revision}</small><small>${e.deleted_at ? "Dihapus " + date(e.deleted_at) : "Retensi sampai " + date(e.expires * 1000)} WIB</small></figcaption></figure>`;
  const document = images.filter(e => ["document", "document-crop"].includes(e.kind));
  const canCrop = document.some(e => e.kind === "document" && !e.deleted_at && e.expires * 1000 > Date.now()) && !document.some(e => e.kind === "document-crop" && !e.deleted_at);
  return `<section class="operator-evidence-section"><div class="panel-head"><div><h3>Dokumen identitas</h3><p>Foto asli dipertahankan bersama turunan crop pada versi bukti yang sama.</p></div>${principal?.role === "admin" ? `<button class="button cleanup-button" data-cleanup="${esc(app.id)}">Clean data permohonan</button>` : ""}</div>${app.photo_cleanup ? `<p class="callout">Foto permohonan ini telah dihapus pada ${date(app.photo_cleanup.at)} WIB. Identitas, hasil pemeriksaan, dan laporan tetap disimpan.</p>` : ""}<div class="evidence-grid document-evidence">${document.map(photo).join("") || '<p class="state-note">Foto KTP belum tersimpan.</p>'}</div>${canCrop ? `<p class="state-note">${app.document_crop_status === "not_located" ? "Bingkai kartu belum berhasil dipisahkan saat OCR. " : ""}Untuk bukti yang sudah tersimpan, buat crop melalui OCR lokal.</p><button class="button service-primary" data-generate-crop="${esc(app.id)}">Buat crop KTP dari foto tersimpan</button>` : ""}</section><section class="operator-evidence-section"><h3>Selfie dan bukti gerakan</h3><div class="evidence-grid">${images.filter(e => !["document", "document-crop"].includes(e.kind)).map(photo).join("") || '<p class="state-note">Belum ada foto selfie atau frame gerakan tersimpan.</p>'}</div></section><div class="buttons">${(app.evidence || []).filter(e => ["identity", "verification"].includes(e.kind)).map(e => `<button class="button" data-evidence="${esc(e.id)}">Lihat ${e.kind === "identity" ? "identitas server" : "hasil model & pengikat bukti"}</button>`).join("")}</div>`;
}
function cleanupDialog(plan) {
  return `<form id="cleanup-form" data-id="${esc(plan.application_id)}"><div class="cleanup-target"><strong>${esc(plan.name || "Identitas belum dibaca")}</strong><span>${esc(plan.application_id)}</span><small>Bukti versi ${plan.capture_revision} · satu permohonan yang dipilih</small></div><fieldset class="cleanup-options"><legend>Pilih data yang akan dihapus</legend><label><input type="radio" name="mode" value="photos" checked required><span><strong>Hapus foto saja</strong><small>${plan.photos} foto: KTP asli, crop, selfie, foto KYC, dan frame gerakan dari seluruh versi. Identitas, hasil, dan PDF tetap disimpan.</small></span></label><label><input type="radio" name="mode" value="full" required><span><strong>Hapus seluruh data permohonan</strong><small>Termasuk foto, identitas, ${plan.results} hasil pemeriksaan, ${plan.registrations} pendaftaran, ${plan.reports} laporan, serta kasus/jadwal terkait.</small></span></label></fieldset><p class="state-note">Penghapusan tidak dapat dibatalkan. Akun login dan permohonan lain tetap disimpan. File yang sudah diunduh ke perangkat berada di luar penyimpanan server.</p><label class="cleanup-confirm"><input type="checkbox" name="confirmed" required> Saya memastikan nomor permohonan di atas adalah data yang ingin saya hapus.</label><p class="text-error" id="modal-error" role="alert"></p><div class="buttons"><button type="button" class="button" data-close>Batal</button><button class="button danger" type="submit">Hapus data terpilih</button></div></form>`;
}
async function applyCleanup(plan, mode) {
  const owner = authEpoch, navigation = navigationRevision;
  const outcome = await api(`/operator/applications/${encodeURIComponent(plan.application_id)}/cleanup`, {
    method: "POST", body: JSON.stringify({mode, capture_revision: plan.capture_revision, expected_updated_at: plan.updated_at, confirm_application_id: plan.application_id}),
  });
  if (owner !== authEpoch || navigation !== navigationRevision) return;
  cleanupPlan = null;
  $("#modal").close();
  if (flow?.session?.application_id === plan.application_id) { stopCamera(); releasePreviews(); flow = null; }
  const refreshed = outcome.application_deleted ? null : await api(`/applications/${encodeURIComponent(plan.application_id)}`);
  if (owner !== authEpoch || navigation !== navigationRevision) return;
  if (selectedApplication?.id === plan.application_id) selectedApplication = refreshed;
  await reloadWorkspace();
  if (owner !== authEpoch || navigation !== navigationRevision) return;
  render();
  toast(outcome.application_deleted ? "Seluruh data permohonan terpilih telah dihapus." : `${outcome.deleted_photos} foto dihapus. Identitas dan hasil tetap tersimpan.`);
}
document.addEventListener("click", async event => {
  const button = event.target.closest("button");
  if (!button || button.disabled) return;
  const owner = authEpoch, navigation = navigationRevision;
  try {
    if (button.dataset.cleanup) {
      button.disabled = true;
      const plan = await api(`/operator/applications/${encodeURIComponent(button.dataset.cleanup)}/cleanup`);
      if (owner !== authEpoch || navigation !== navigationRevision) return;
      cleanupPlan = plan;
      modal("Clean data permohonan", cleanupDialog(plan));
    } else if (button.dataset.generateCrop) {
      button.disabled = true;
      const app = await api(`/applications/${encodeURIComponent(button.dataset.generateCrop)}/document-crop`, {method: "POST"});
      if (owner !== authEpoch || navigation !== navigationRevision || selectedApplication?.id !== app.id) return;
      selectedApplication = app;
      render();
      toast("Crop KTP tersimpan bersama foto asli.");
    } else if (button.dataset.photo) {
      modal(button.dataset.photoTitle || "Foto bukti", `<img class="operator-photo-full" src="/api/evidence/${encodeURIComponent(button.dataset.photo)}" alt="${esc(button.dataset.photoTitle)}"><button class="button" data-close>Tutup</button>`);
    }
  } catch (error) { if (owner === authEpoch && navigation === navigationRevision) errorMessage(error); }
  finally { if (button.isConnected) button.disabled = false; }
});
document.addEventListener("submit", async event => {
  const form = event.target;
  if (!["operator-search-form", "cleanup-form"].includes(form.id)) return;
  event.preventDefault();
  if (!form.checkValidity()) return form.reportValidity();
  const data = Object.fromEntries(new FormData(form));
  if (form.id === "operator-search-form") {
    operatorQuery = data.query || ""; operatorFilter = data.filter || "all";
    render(); return;
  }
  const button = form.querySelector('[type="submit"]');
  if (button.disabled || !cleanupPlan || cleanupPlan.application_id !== form.dataset.id) return;
  button.disabled = true;
  try { await applyCleanup(cleanupPlan, data.mode); }
  catch (error) { errorMessage(error); }
  finally { if (button.isConnected) button.disabled = false; }
});
