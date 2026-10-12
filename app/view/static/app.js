"use strict";
const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => [...root.querySelectorAll(s)];
const esc = (v) =>
  String(v ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const shapes = {
  dashboard:
    '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
  verify:
    '<path d="M12 3 3 7v6c0 4 4 7 9 9 5-2 9-5 9-9V7z"/><path d="m8 12 3 3 5-6"/>',
  queue:
    '<rect x="4" y="4" width="16" height="17" rx="2"/><path d="M8 9h8M8 13h8M8 17h5"/>',
  audit: '<path d="M3 12a9 9 0 1 0 3-7M3 3v5h5M12 7v6l4 2"/>',
  modules: '<path d="m12 3 9 5-9 5-9-5zM3 12l9 5 9-5M3 17l9 5 9-5"/>',
  arrow: '<path d="M5 12h14m-5-5 5 5-5 5"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  file: '<path d="M14 3H5v18h14V8zM14 3v5h5M8 12h8M8 16h6"/>',
  face: '<path d="M3 8V3h5M16 3h5v5M21 16v5h-5M8 21H3v-5"/><circle cx="12" cy="10" r="3"/><path d="M7 18c0-5 10-5 10 0"/>',
  upload: '<path d="M12 16V3m-5 5 5-5 5 5M4 15v5h16v-5"/>',
  download: '<path d="M12 3v13m-5-5 5 5 5-5M4 17v4h16v-4"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7v1"/>',
};
const icon = (name) =>
  `<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${shapes[name] || shapes.verify}</svg>`;
const names = {
  home: "Beranda",
  result: "Hasil verifikasi",
  registration: "Pendaftaran",
  postkyc: "Data permohonan",
  receipt: "Bukti pendaftaran",
  status: "Status layanan",
  verify: "Verifikasi baru",
};
const statuses = {
  pass: ["Kontrol lokal terpenuhi", "green"],
  capture: ["Perbaikan capture", "orange"],
  technical: ["Gangguan teknis", "blue"],
  manual: ["Pemeriksaan manual", "orange"],
  attack: ["Tinjauan keamanan", "red"],
  scheduled: ["Terjadwal", "blue"],
  approved: ["Disetujui petugas", "green"],
  rejected: ["Tidak disetujui", "red"],
};
const modules = [
  [
    "Penutup wajah",
    "FaceAttribNet · ONNX CPU",
    "Peringatan kacamata, masker, kacamata hitam, dan visibilitas wajah saat kamera aktif.",
    "face",
  ],
  [
    "OCR KTP",
    "RapidOCR · PaddleOCR ONNX",
    "Ekstraksi teks, pemetaan NIK/nama, dan pengukuran kualitas gambar.",
    "file",
  ],
  [
    "Wajah 1:1",
    "YuNet + SFace",
    "Deteksi wajah dan cosine similarity antara KTP, selfie, serta foto KYC.",
    "face",
  ],
  [
    "Tantangan gerakan",
    "PIPNet 68 · ONNX CPU",
    "Landmark mata/mulut dan perubahan posisi kepala dari frame kamera.",
    "face",
  ],
  [
    "KYC memegang KTP",
    "OpenCV + MediaPipe Hands",
    "Bingkai kartu, OCR NIK kedua, kecocokan wajah, dan kedekatan tangan.",
    "face",
  ],
  [
    "Anti-spoof / PAD",
    "CVPR 2024 Swin V2-B · CPU / CoreML / CUDA",
    "Probabilitas live dari selfie dan sampel frame tantangan.",
    "verify",
  ],
  [
    "Classifier gambar (diagnostik)",
    "ViT deepfake · ONNX",
    "Analisis tambahan untuk operator; belum dikalibrasi untuk KYC dan tidak menentukan kelulusan.",
    "verify",
  ],
  [
    "Sumber identitas",
    "Adapter Dukcapil mock",
    "Satu-satunya adapter simulasi. Tidak mengonfirmasi identitas resmi.",
    "modules",
  ],
];
let workspace = {
    records: [],
    audit: [],
    settings: {},
    health: { ready: false, files: {} },
  },
  page = "home",
  flow = null,
  busy = false,
  queueQuery = "",
  queueFilter = "all",
  stream = null,
  cameraKind = null,
  cameraToken = 0,
  cameraFeedback = new CaptureFeedback(),
  qualityGate = new QualityGate(),
  cameraAutoGate = null,
  cameraAutoStopped = false,
  cameraCheckTimer = null,
  cameraCheckAbort = null,
  recording = false,
  cameraCheckingPaused = false,
  exportURL = null,
  toastTimer;
const urls = new Set();
function preview(blob) {
  const url = URL.createObjectURL(blob);
  urls.add(url);
  return url;
}
function releasePreviews() {
  for (const u of urls) URL.revokeObjectURL(u);
  urls.clear();
}
function toast(text) {
  clearTimeout(toastTimer);
  $("#toast").textContent = text;
  $("#toast").classList.add("show");
  toastTimer = setTimeout(() => $("#toast").classList.remove("show"), 4000);
}
async function api(path, options = {}) {
  const epoch = authEpoch;
  const response = await fetch("/api" + path, {
    ...options,
    headers: {
      "X-Local-Client": "mock-id",
      "X-Workspace-Mode": "public",
      ...(flow && path.startsWith(`/sessions/${flow.session.id}/`)
        ? { "X-Capture-Revision": String(flow.session.revision) }
        : {}),
      ...(options.body instanceof FormData
        ? {}
        : { "Content-Type": "application/json" }),
      ...options.headers,
    },
  });
  const result = await readApiResponse(response);
  if (epoch !== authEpoch)
    throw new Error("Akun telah berubah; respons lama diabaikan.");
  return result;
}
async function reloadWorkspace() {
  const mode = "public";
  if (accessMode && accessMode !== mode) {
    authEpoch++;
    stopCamera();
    stopDeliveryWatch();
    releasePreviews();
    flow = null;
    selectedApplication = null;
    applicationRows = [];
  }
  accessMode = mode;
  try {
    try {
      principal = (await api("/auth/me")).principal;
    } catch (error) {
      if (mode !== "public" || error.status !== 401) throw error;
      principal = (await api("/auth/guest", { method: "POST" })).principal;
    }
  } catch (error) {
    if (error.status === 401) {
      principal = null;
      return;
    }
    throw error;
  }
  applicationRows = [];
  capacityCalendar = null;
  workspace = {
    records: [],
    audit: [],
    settings: {},
    health: await api("/health"),
  };
  operatorMetrics = null;
}
function badge(status) {
  const [text, color] = statuses[status] || [status, "gray"];
  return `<span class="badge ${color}"><span class="swatch" style="background:currentColor"></span>${text}</span>`;
}
const date = (v) =>
  new Intl.DateTimeFormat("id-ID", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "Asia/Jakarta",
  }).format(new Date(v));
const pct = (v) =>
  typeof v === "number" ? (v * 100).toFixed(1) + "%" : "Belum diperiksa";
function head(title, sub, action = "", eyebrow = "LOCAL IDENTITY INFERENCE") {
  return `<div class="page-head"><div><div class="eyebrow">${eyebrow}</div><h1>${title}</h1><p>${sub}</p></div>${action}</div>`;
}
function updateNav() {
  for (const b of $$(".sidebar nav button[data-page]")) {
    const key = b.dataset.page;
    b.innerHTML = `${icon(key)}<span>${names[key]}</span>${key === "queue" ? `<span class="count">${workspace.records.filter((r) => ["manual", "scheduled"].includes(r.status)).length}</span>` : ""}`;
    b.classList.toggle("active", key === page);
    if (key === page) b.setAttribute("aria-current", "page");
    else b.removeAttribute("aria-current");
  }
  if ($("#crumb")) $("#crumb").textContent = names[page];
}
function render() {
  document.body.classList.toggle("public-mode", publicPages.has(page));
  updateNav();
  const views = {
    result: deliveryView,
    home: publicHome,
    registration: publicRegistration,
    postkyc: postKycView,
    receipt: receiptView,
    status: publicStatus,
    dashboard,
    verify: verifyView,
    queue: operatorQueueView,
    audit: auditView,
    modules: modulesView,
  };
  if (principal) {
    const loginLabel = $("#profile-login"),
      roleLabel = $("#profile-role");
    if (loginLabel) loginLabel.textContent = principal.login;
    if (roleLabel) roleLabel.textContent = principal.role;
  }
  const view = views[page]();
  $("#app").innerHTML =
    `<div class="screen-enter">${page === "dashboard" ? adminMetricsView() : ""}${view}</div>`;
}
async function navigate(target) {
  page = names[target] ? target : "home";
  try {
    await reloadWorkspace();
    if (!principal)
      throw new Error("Sesi pemohon belum tersedia. Muat ulang halaman.");
    if (
      principal?.role === "applicant" &&
      ["dashboard", "queue", "audit", "modules"].includes(page)
    )
      page = "home";
    if (
      principal?.role === "helpdesk" &&
      ["dashboard", "audit", "modules"].includes(page)
    )
      page = "queue";
    if (page === "result" && !selectedApplication) {
      let active = null;
      try {
        active = sessionStorage.getItem("mock_id_active_application");
      } catch {}
      if (active)
        selectedApplication = await api(
          "/applications/" + encodeURIComponent(active),
        );
    }
    if (page === "verify" && !flow) await newFlow(false);
    history.replaceState(null, "", "#" + page);
    render();
    window.scrollTo(0, 0);
    if (page === "result") await observeDelivery(selectedApplication);
    else if (page !== "verify") stopDeliveryWatch();
  } catch (e) {
    document.body.classList.toggle("public-mode", publicPages.has(page));
    updateNav();
    $("#app").innerHTML =
      `${head(e.status >= 500 ? "Server mengalami gangguan" : "Backend belum terhubung", e.status >= 500 ? "Server belum dapat menyelesaikan permintaan. Coba kembali dan periksa log server." : "Pastikan server Python sudah berjalan melalui npm start.")}<div class="callout" role="alert">${esc(e.message)}</div>`;
  }
}
async function newFlow(show = true, applicationId = null) {
  if (busy || captureResetting) return;
  stopCamera();
  $("#modal").close();
  releasePreviews();
  selectedApplication = null;
  stopDeliveryWatch();
  if (!principal) {
    principal = (await api("/auth/guest", { method: "POST" })).principal;
  }
  const session = await api("/sessions", {
    method: "POST",
    body: JSON.stringify({ application_id: applicationId }),
  });
  rememberApplication(session.application_id);
  flow = {
    session,
    step: 0,
    documentBlob: null,
    documentURL: null,
    ocr: null,
    selfieBlob: null,
    selfieURL: null,
    holdingBlob: null,
    holdingURL: null,
    holdingFeedback: null,
    livenessResult: null,
    frames: [],
    manifest: [],
    consent: false,
    result: null,
  };
  if (show) {
    page = "verify";
    location.hash = "verify";
    render();
    window.scrollTo(0, 0);
  }
}
function table(records) {
  return `<div class="table-wrap"><table><thead><tr><th>PEMOHON</th><th>ID & WAKTU</th><th>STATUS</th><th>INFERENCE</th><th>AKSI</th></tr></thead><tbody>${records.map((r) => `<tr><td><div class="person-cell"><span class="person-avatar">${esc(r.name.slice(0, 2).toUpperCase())}</span><div><strong>${esc(r.name)}</strong><small>${esc(r.nik_masked)}</small></div></div></td><td><strong class="session-id">${esc(r.id)}</strong><small>${date(r.created)} WIB</small></td><td>${badge(r.status)}</td><td>${(r.duration_ms / 1000).toFixed(1)} detik<small>Hasil model lokal</small></td><td><button class="row-action" data-detail="${esc(r.id)}" aria-label="Detail ${esc(r.name)}">Detail ↗</button></td></tr>`).join("") || '<tr><td colspan="5" class="empty">Belum ada permohonan. Mulai capture untuk membuat hasil nyata.</td></tr>'}</tbody></table></div>`;
}
function dashboard() {
  const records = workspace.records,
    total = records.length,
    passed = records.filter((r) =>
      ["pass", "approved"].includes(r.status),
    ).length,
    manual = records.filter((r) =>
      ["manual", "scheduled"].includes(r.status),
    ).length,
    average = total
      ? (records.reduce((a, r) => a + r.duration_ms, 0) / total / 1000).toFixed(
          1,
        )
      : "—";
  return `${head("Ringkasan verifikasi", "Hasil berasal dari gambar dan frame yang diproses oleh model lokal.", `<button class="button primary" data-new>${icon("plus")} Verifikasi baru</button>`)}<div class="hero"><div class="hero-copy"><div class="hero-label"><span></span> OPEN SOURCE · REAL INFERENCE</div><h2>Capture nyata. Pemeriksaan lokal.</h2><p>OCR KTP, tantangan liveness, face matching, dan foto memegang KTP berjalan melalui model open source. Dukcapil memakai adapter mock.</p><div class="hero-bottom"><button class="button light" data-new>Mulai capture ${icon("arrow")}</button><small>Foto diproses di server lokal Anda</small></div></div><div class="hero-art" aria-hidden="true"><div class="orbit three"></div><div class="orbit two"></div><div class="orbit"></div><div class="shield">${icon("check")}</div><span class="floating-check">✓</span></div></div><div class="validation-note ${workspace.health.ready ? "" : "health-warn"}">${icon("info")} ${workspace.health.ready ? "Bobot model tersedia. Siap memproses gambar." : "Model belum lengkap. Jalankan npm run setup untuk mengunduh dependensi dan bobot."} <button class="button link" data-page="modules">Lihat modul →</button></div><div class="stats">${[
    ["Permohonan nyata", total, "file"],
    ["Kontrol lokal terpenuhi", passed, "verify"],
    ["Antrean manual", manual, "queue"],
    ["Rata-rata inference", average === "—" ? "—" : average + " dtk", "clock"],
  ]
    .map(
      ([label, value, i]) =>
        `<div class="stat"><div class="stat-top">${label} ${icon(i)}</div><div class="stat-number">${value}</div><div class="stat-meta">${i === "clock" ? "Waktu diukur server" : "Dari hasil tersimpan di SQLite"}</div></div>`,
    )
    .join(
      "",
    )}</div><div class="grid-two"><section class="panel"><div class="panel-head"><div><h2>Pipeline pemeriksaan</h2><p>Tanpa pilihan skenario atau skor preset.</p></div><span class="new-tag">LOCAL INFERENCE</span></div><div class="panel-body">${[
    ["OCR & kualitas KTP", "Teks, NIK 16 digit, blur, dan pencahayaan"],
    [
      "Selfie & tantangan gerakan",
      "Kamera merekam kedipan, putaran kepala, dan senyuman",
    ],
    [
      "KYC foto memegang KTP",
      "Baca NIK kedua, tangan dekat kartu, dan wajah pemohon",
    ],
    [
      "Wajah & anti-spoof",
      "Cosine SFace, probabilitas PAD, dan classifier ViT",
    ],
    [
      "Keputusan & audit",
      "Hasil lokal, perbaikan, teknis, manual, atau keamanan",
    ],
  ]
    .map(
      ([title, desc], i) =>
        `<div class="flow-item"><span class="flow-number">${i + 1}</span><div class="flow-info"><h3>${title}</h3><p>${desc}</p></div></div>`,
    )
    .join(
      "",
    )}</div></section><section class="panel"><div class="panel-head"><h2>Status runtime</h2></div><div class="panel-body"><div class="runtime-status">${workspace.health.ready ? icon("check") : icon("info")}<strong>${workspace.health.ready ? "Model tersedia" : "Perlu setup model"}</strong></div><p class="step-description">${esc(padRuntimeLabel())}. ${esc(workspace.health.other_runtime || "Model lain menggunakan CPU")}. Foto tetap diproses lokal.</p><div class="result-control"><span>Penyimpanan</span><span class="badge green">SQLite lokal</span></div><div class="result-control"><span>Bobot model</span><span class="badge gray">SHA-256 pinned</span></div><div class="result-control"><span>Dukcapil</span><span class="badge orange">MOCK · belum terverifikasi</span></div><div class="callout" style="margin-top:20px">Hasil “kontrol lokal terpenuhi” tidak mengonfirmasi keaslian KTP atau identitas resmi. Foto memegang kartu menjadi bukti pendukung untuk ditinjau.</div></div></section></div><section class="panel table-panel"><div class="panel-head"><div><h2>Permohonan terbaru</h2><p>Dataset dimulai kosong; tidak ada permohonan fiktif yang dimuat otomatis.</p></div></div>${table(records.slice(0, 5))}</section>`;
}
function verifyView() {
  if (!flow) return head("Menyiapkan sesi…", "Sesi dibuat oleh backend lokal.");
  const stepNames = [
    "Dokumen",
    "Data identitas",
    "Liveness",
    "Foto + KTP",
    "Hasil",
  ];
  return `${head("Verifikasi identitas", "Verifikasi identitas untuk pendaftaran debitur perseorangan.", `<span class="badge green">PERSEORANGAN · KYC LOKAL</span>`, "APPLICANT EXPERIENCE")}<div class="verification-layout"><section class="panel verification-panel"><div class="stepper">${stepNames.map((name, i) => `<div class="step ${flow.step === i ? "current" : flow.step > i ? "done" : ""}"><b>${flow.step > i ? "✓" : i + 1}</b>${name}</div>`).join("")}</div><div class="step-content">${flow.retryPlan && !busy && flow.step !== 4 ? `<div class="retry-notice"><strong>${esc(flow.retryPlan.label)}</strong><p>${esc(flow.retryPlan.reason)}</p><small>OCR, liveness, dan foto lain yang sudah tersedia dipertahankan. Pencocokan dengan capture baru tetap diperiksa ulang.</small></div>` : ""}${busy ? '<h2>Memproses model…</h2><p class="step-description">Model memproses gambar atau rekaman sesuai tahap pemeriksaan di server lokal.</p><span class="spinner"></span><p class="state-note">Tunggu hasil backend. Waktu proses bergantung perangkat dan ukuran capture.</p>' : [documentView, identityView, livenessView, holdingView, resultView][flow.step]()}</div></section><aside class="verification-aside"><section class="panel session-card"><h3>Sesi verifikasi</h3><div class="session-row"><span>ID</span><strong class="session-id">${esc(flow.session.id.slice(0, 8).toUpperCase())}</strong></div><div class="session-row"><span>Percobaan</span><strong>${flow.session.attempt} / ${flow.session.max_attempts}</strong></div><div class="session-row"><span>Berlaku sampai</span><strong>${new Intl.DateTimeFormat("id-ID", { hour: "2-digit", minute: "2-digit", timeZone: "Asia/Jakarta" }).format(new Date(flow.session.expires_at * 1000))} WIB</strong></div><div class="state-note">Nonce sekali pakai dan batas percobaan diperiksa oleh server. Sesi capture berakhir setelah 15 menit atau saat server dimulai ulang.</div></section><section class="panel scenario-card"><h3>Model yang digunakan</h3><p>Semua analisis foto menjalankan model. Tidak ada pemilih hasil simulasi.</p>${["PaddleOCR melalui RapidOCR", "YuNet + SFace", "PIPNet + MediaPipe Hand ONNX", "CVPR 2024 Swin V2-B (face)", "ViT classifier (diagnostik tambahan)", "FaceAttribNet: kacamata & masker"].map((n) => `<div class="model-runtime-line"><span class="green-dot"></span>${n}</div>`).join("")}<div class="simulation-note">Dukcapil belum terhubung. Data keuangan SLIK memakai adapter demo; identitas resmi tetap belum diverifikasi.</div></section></aside></div>`;
}
function documentView() {
  return `<h2>Foto KTP yang akan dibaca</h2><p class="step-description">Setujui pemrosesan lalu buka kamera. Foto dan OCR berjalan otomatis setelah NIK serta potret KTP terbaca. Gunakan kartu utuh dan pencahayaan merata; unggahan gambar tetap tersedia.</p><div class="upload-zone">${icon("upload")}<h3>JPG, PNG, atau WebP</h3><p>Maksimal 5 MB / 16 megapiksel</p><div class="upload-buttons"><button class="button primary" data-camera="document" ${flow.consent ? "" : "disabled"}>Buka kamera otomatis</button><button class="button" data-upload="document">Pilih gambar KTP</button><input type="file" id="document-file" accept="image/jpeg,image/png,image/webp" hidden aria-label="Unggah KTP"></div>${flow.documentURL ? `<img class="image-preview" src="${flow.documentURL}" alt="Pratinjau foto KTP">` : ""}</div><label class="scenario"><input type="checkbox" id="consent" ${flow.consent ? "checked" : ""}><span>Saya setuju memproses capture pada server lokal ini.<small>Saya meminta informasi untuk diri sendiri. Bukti yang diperlukan disimpan terenkripsi sesuai retensi demo untuk pemeriksaan manual.</small></span></label><p class="text-error" id="step-error" role="alert"></p><div class="form-actions"><span class="micro">NIK akan dibaca model, tanpa isian contoh.</span>${flow.documentBlob ? `<button class="button primary" data-ocr ${flow.consent ? "" : "disabled"}>Baca gambar unggahan ${icon("arrow")}</button>` : ""}</div>`;
}
function identityView() {
  const fields = flow.ocr.fields;
  return `<h2>Tinjau hasil OCR</h2><p class="step-description">Teks diekstrak oleh model. Nama, tanggal lahir, dan alamat dapat dikoreksi; NIK tetap mengikuti hasil pembacaan untuk dicocokkan dengan foto KYC. Setelah Anda melanjutkan, kamera liveness dibuka otomatis.</p><div class="validation-note">${principal?.role === "applicant" ? "Foto dapat dibaca. Pastikan nama, NIK dan tanggal lahir sesuai KTP Anda." : `Confidence pengenalan teks: ${pct(flow.ocr.confidence)} · blur: ${flow.ocr.quality?.blur}<br>Confidence OCR bukan skor keaslian dokumen.`}</div><form id="identity-form"><div class="form-grid"><div class="field wide"><label for="nik">NIK hasil OCR</label><input id="nik" value="${esc(fields.nik)}" readonly></div><div class="field"><label for="name">Nama lengkap</label><input id="name" name="name" value="${esc(fields.name)}" minlength="2" maxlength="80" required></div><div class="field"><label for="birth">Tanggal lahir</label><input id="birth" name="birth" type="date" required value="${esc(fields.birth)}"></div><div class="field wide"><label for="address">Alamat</label><input id="address" name="address" value="${esc(fields.address)}" maxlength="200"></div></div><details class="ocr-raw"><summary>Teks mentah OCR</summary><pre>${esc(flow.ocr.lines.join("\n"))}</pre></details><p class="text-error" id="step-error" role="alert"></p><div class="form-actions"><button type="button" class="button" data-back>Kembali</button><button class="button primary" type="submit">${CaptureState.canVerify(flow) ? "Periksa kembali" : flow.livenessResult?.passed ? "Lanjut ke foto bersama KTP" : "Lanjut ke liveness otomatis"} ${icon("arrow")}</button></div></form>`;
}
const challengeText = {
  blink: [
    "Pejamkan dan buka mata",
    "Mulai dengan mata terbuka, lalu pejamkan selama satu detik dan buka kembali.",
  ],
  turn: [
    "Putar kepala ke samping",
    "Mulai menghadap depan, lalu putar kepala ke kiri atau kanan.",
  ],
  smile: [
    "Tersenyum",
    "Mulai dengan ekspresi netral, lalu tersenyum dengan jelas.",
  ],
};
function livenessView() {
  return `<h2>Liveness dengan deteksi langsung</h2><p class="step-description">Video kamera berjalan terus. Pemeriksaan membaca gerakan mata, senyum, dan arah kepala, sekaligus memeriksa risiko penggunaan foto atau layar.</p><div class="challenge-list">${flow.session.challenges.map((c, i) => `<div class="challenge ${flow.livenessResult?.passed ? "complete" : ""}">${flow.livenessResult?.passed ? "✓" : i + 1} ${challengeText[c][0]}</div>`).join("")}</div><div class="capture capture-real">${flow.selfieURL ? `<img class="image-preview" src="${flow.selfieURL}" alt="Selfie dari rekaman liveness">` : `${icon("face")}<span>Wajah Anda akan muncul setelah rekaman.</span>`}</div><div class="upload-buttons" style="margin-top:18px"><button class="button primary" data-camera="liveness">${icon("face")} ${flow.livenessResult ? "Ulangi pemeriksaan" : "Buka kamera otomatis"}</button></div><p class="state-note">Pemeriksaan langsung dimulai saat kamera siap. Ikuti instruksi gerakan; app menyelesaikan liveness dan melanjutkan ke foto bersama KTP otomatis setelah semua gerakan lolos. Tidak perlu menekan tombol rekam.</p>${flow.livenessResult?.frames ? `<div class="state-note" style="margin-top:18px">${flow.livenessResult.frames} frame diperiksa langsung oleh model.</div>` : ""}${flow.livenessResult ? `<div class="capture-feedback ${flow.livenessResult.passed ? "clear" : "warning"}" role="status">${esc(flow.livenessResult.reason)}</div>` : `<div class="capture-feedback checking">Gunakan wajah langsung di kamera. Foto atau video pada layar akan diperiksa dengan tantangan gerakan dan anti-spoof.</div>`}<p class="text-error" id="step-error" role="alert"></p><div class="form-actions"><button class="button" data-back>Kembali</button><button class="button primary" data-next-holding ${flow.livenessResult?.passed ? "" : "disabled"}>${CaptureState.canVerify(flow) ? "Periksa kembali" : "Foto bersama KTP"} ${icon("arrow")}</button></div>`;
}
function holdingView() {
  return `<h2>Foto diri sambil memegang KTP</h2><p class="step-description">Pegang KTP di bawah dagu. Wajah, tangan, kartu yang cukup besar, dan NIK harus terlihat jelas agar model dapat memeriksanya.</p><div class="kyc-preview">${flow.holdingURL ? `<img class="holding-image" src="${flow.holdingURL}" alt="Foto diri sambil memegang KTP">` : '<div class="kyc-placeholder"><span class="kyc-face-outline"></span><span class="kyc-card-outline">KTP</span><p>Wajah di atas · kartu dan tangan di bawah</p></div>'}</div><div class="kyc-guidance">${[
    ["Wajah tidak tertutup", "Lepaskan kacamata, masker, dan penutup wajah."],
    ["NIK kartu terbaca", "OCR mencocokkan kedua NIK."],
    ["Tangan terlihat", "Landmark tangan diperiksa di dekat kartu."],
  ]
    .map(
      ([title, desc], i) =>
        `<div><span>0${i + 1}</span><strong>${title}</strong><small>${desc}</small></div>`,
    )
    .join(
      "",
    )}</div>${flow.holdingFeedback ? `<div class="capture-feedback ${flow.holdingFeedback.ready ? "clear" : "warning"}" role="status">${esc(flow.holdingFeedback.ready ? "Pemeriksaan wajah terpenuhi. Kartu dan NIK diperiksa saat menjalankan model." : flow.holdingFeedback.warnings.map((w) => w.message).join(" "))}</div>` : ""}<div class="upload-buttons"><button class="button primary" data-camera="holding">Buka kamera otomatis</button><button class="button" data-upload="holding">Pilih foto bersama KTP</button><input type="file" id="holding-file" accept="image/jpeg,image/png,image/webp" hidden aria-label="Unggah foto memegang KTP"></div><p class="state-note">Foto diambil otomatis setelah NIK cocok, tangan terlihat, dan pemeriksaan wajah terpenuhi. Foto memegang kartu mendukung pemeriksaan penguasaan dokumen. Keaslian fisik kartu dan identitas resmi belum dikonfirmasi oleh Dukcapil.</p><p class="text-error" id="step-error" role="alert"></p><div class="form-actions"><button class="button" data-back>Kembali</button><button class="button primary" data-verify ${flow.holdingBlob && flow.holdingFeedback?.ready ? "" : "disabled"}>${icon("verify")} Jalankan model</button></div>`;
}
function checkRows(record, { diagnostics = false } = {}) {
  const checks = record.checks.filter(
    (c) => diagnostics || c.effect !== "advisory",
  );
  return `<div class="result-controls">${checks.map((c) => `<div class="result-control"><div><span>${esc(c.name)}</span>${(c.status === "failed" || c.effect === "advisory") && c.detail?.message ? `<p class="check-reason">${esc(c.detail.message)}</p>` : ""}</div><span class="badge ${c.mode === "mock" ? "orange" : c.status === "passed" ? "green" : c.status === "failed" ? "orange" : "blue"}">${c.mode === "mock" ? "MOCK · belum diverifikasi" : c.effect === "advisory" ? (c.status === "unavailable" ? "Diagnostik tidak tersedia" : "Diagnostik") : c.status === "passed" ? "Terpenuhi" : c.status === "failed" ? "Belum terpenuhi" : "Tidak tersedia"}</span></div>`).join("")}</div>`;
}
function scoreCards(record, { diagnostics = false } = {}) {
  const scores = record.scores || {};
  const score = scores.face_cosine;
  return `<div class="score-grid ${diagnostics ? "with-diagnostics" : ""}"><div class="score"><small>Kemiripan wajah KTP ↔ selfie</small><strong>${typeof score === "number" ? score.toFixed(3) : "Belum diperiksa"}</strong><p>Skor cosine; semakin tinggi semakin mirip. Bukan persentase kepastian identitas.</p>${typeof record.rules?.face_cosine === "number" ? `<small>Ambang saat pemeriksaan: ${record.rules.face_cosine.toFixed(3)}</small>` : ""}</div><div class="score"><small>Live probability</small><strong>${pct(scores.liveness)}</strong><p>Skor model anti-spoof, bukan jaminan bahwa seluruh serangan terdeteksi.</p></div>${diagnostics ? `<div class="score"><small>Skor classifier gambar AI (diagnostik)</small><strong>${pct(scores.deepfake)}</strong><p>Skor kelas AI-generated dari model umum. Belum dikalibrasi untuk KYC; tidak menentukan kelulusan pada kebijakan terbaru.</p></div>` : ""}</div>`;
}
function resultView() {
  const r = flow.result;
  if (!r) return "";
  if (r.application)
    return `${applicationPanel(r.application)}<div class="form-actions">${["CAPTURE_RETRY", "TECHNICAL_PENDING"].includes(r.application.state) ? `<button class="button primary" data-retry ${flow.session.attempt >= flow.session.max_attempts ? "disabled" : ""}>${esc(r.retry?.label || "Ulangi tahap yang perlu diperbaiki")} (${flow.session.attempt}/${flow.session.max_attempts})</button>` : ""}<button class="button" data-page="home">Kembali ke beranda</button></div>${
      !["REJECTED", "MANUAL_REJECTED"].includes(r.application.state)
        ? `<details class="other-retakes"><summary>Ambil ulang tahap lain</summary><div class="retake-options">${[
            ["document", "OCR KTP"],
            ["liveness", "Liveness"],
            ["holding", "Foto + KTP"],
          ]
            .map(
              ([stage, label]) =>
                `<button class="button" data-retake="${stage}" ${flow.session.attempt >= flow.session.max_attempts ? "disabled" : ""}>${label}</button>`,
            )
            .join("")}</div></details>`
        : ""
    }`;
  const titles = {
    pass: "Kontrol lokal terpenuhi",
    capture: "Perbaiki capture Anda",
    technical: "Inference belum selesai",
    manual: "Perlu pemeriksaan petugas",
    attack: "Perlu tinjauan keamanan",
    approved: "Disetujui petugas lokal",
    rejected: "Belum disetujui",
    scheduled: "Pemeriksaan terjadwal",
  };
  return `<div class="result-banner"><div class="result-symbol ${statuses[r.status][1]}">${r.status === "pass" ? "✓" : r.status === "attack" ? "!" : "↻"}</div><h2>${titles[r.status]}</h2><p>${esc(r.reason)}</p>${badge(r.status)}</div>${scoreCards(r)}${checkRows(r)}<div class="simulation-note">Dukcapil: mock. Identitas resmi belum diverifikasi, termasuk jika seluruh kontrol lokal terpenuhi.</div><div class="state-note">${esc(r.id)} · ${(r.duration_ms / 1000).toFixed(2)} detik inference server<br>Probabilitas model dan ambang belum dikalibrasi untuk penggunaan operasional.</div>${r.status === "pass" ? `<div class="registration-notice success">${icon("check")}<div><strong>Verifikasi lokal berhasil</strong><p>Lanjutkan untuk melengkapi permohonan iDeb pada demo ini.</p></div><button class="button primary" data-continue-registration>Lanjut ke pendaftaran ${icon("arrow")}</button></div>` : ""}<div class="form-actions"><button class="button" data-export-result>${icon("download")} Ekspor hasil</button>${["capture", "technical"].includes(r.status) ? `<button class="button primary" data-retry ${flow.session.attempt >= flow.session.max_attempts ? "disabled" : ""}>${esc(r.retry?.label || "Perbaiki tahap yang gagal")} (${flow.session.attempt}/${flow.session.max_attempts})</button>` : ["manual", "scheduled"].includes(r.status) ? '<button class="button primary" data-page="queue">Lihat antrean manual</button>' : `<button class="button primary" data-detail="${r.id}">Detail pemeriksaan</button>`}</div><details class="other-retakes"><summary>Ambil ulang tahap lain (opsional)</summary><div class="retake-options">${[
    ["document", "OCR KTP"],
    ["liveness", "Liveness"],
    ["holding", "Foto + KTP"],
  ]
    .map(
      ([stage, label]) =>
        `<button class="button" data-retake="${stage}" ${flow.session.attempt >= flow.session.max_attempts ? "disabled" : ""}>${label}</button>`,
    )
    .join(
      "",
    )}</div></details><div style="margin-top:20px"><button class="button link" data-new>Mulai sesi baru →</button></div>`;
}
function queueRecords() {
  return workspace.records.filter(
    (r) =>
      ["manual", "scheduled"].includes(r.status) &&
      (queueFilter === "all" || r.status === queueFilter) &&
      `${r.name} ${r.id}`.toLowerCase().includes(queueQuery.toLowerCase()),
  );
}
function queueView() {
  return `${head("Antrean pemeriksaan manual", "Hasil yang belum pasti dapat dijadwalkan dan diperiksa petugas.", `<button class="button" data-export-queue>${icon("download")} Ekspor antrean</button>`)}<section class="panel"><div class="filters"><input id="queue-search" aria-label="Cari pemohon" placeholder="Cari nama atau ID…" value="${esc(queueQuery)}"><select id="queue-filter" aria-label="Filter antrean"><option value="all">Semua status</option><option value="manual" ${queueFilter === "manual" ? "selected" : ""}>Menunggu petugas</option><option value="scheduled" ${queueFilter === "scheduled" ? "selected" : ""}>Terjadwal</option></select></div><div id="queue-table">${table(queueRecords())}</div><div class="table-bottom">Keputusan petugas dicatat di backend. Status identitas resmi Dukcapil tetap belum diverifikasi.</div></section>`;
}
function auditView() {
  return `${head("Jejak aktivitas", "Audit berasal dari backend dan tersimpan di SQLite lokal.", `<button class="button" data-export-audit>${icon("download")} Ekspor audit</button>`)}<section class="panel">${workspace.audit.map((e) => `<div class="audit-event"><div class="event-icon">${icon("audit")}</div><div class="event-content"><h3>${esc(e.type)} <span class="badge gray">${esc(e.ref)}</span></h3><p>${esc(e.detail)}</p></div><time>${date(e.created)} WIB</time></div>`).join("") || '<div class="empty">Belum ada aktivitas.</div>'}</section><p class="state-note">Database lokal dapat diubah oleh pemilik komputer. Audit ini belum dirancang sebagai log tahan manipulasi.</p>`;
}
function padRuntimeLabel() {
  const runtime = workspace.health.pad_runtime;
  if (!runtime) return "Runtime PAD belum diperiksa";
  return `${runtime.runtime}${runtime.loaded ? " · model dimuat" : " · menunggu model dimuat"}`;
}
function runtimeView() {
  const runtime = workspace.health.pad_runtime;
  return `<section class="panel config-panel"><h2>Runtime pada perangkat ini</h2><div class="result-control"><span>Swin V2 anti-spoof</span><span class="badge blue">${esc(padRuntimeLabel())}</span></div><p>${esc(workspace.health.other_runtime || "Model lain menggunakan CPU")}</p><p class="state-note">Tier 2 PAD memakai CPU, CoreML pada Apple Silicon, atau CUDA pada Linux kompatibel. Operasi yang tidak didukung dapat memakai CPU. Runtime bukan jaminan perlindungan terhadap seluruh replay, deepfake atau injection.</p>${runtime?.fallback_reason ? `<p class="text-error">${esc(runtime.fallback_reason)}</p>` : ""}</section>`;
}
function modulesView() {
  const settings = workspace.settings;
  return `${head("Modul & konfigurasi", "Model benar-benar dijalankan; ketersediaan bobot dapat diperiksa di bawah.", `<span class="badge ${workspace.health.ready ? "green" : "orange"}">${workspace.health.ready ? "Bobot tersedia" : "Setup diperlukan"}</span>`)}<div class="module-grid">${modules.map(([title, engine, desc, i], n) => `<section class="panel module-card">${icon(i)}<h3>${title}</h3><p>${desc}</p><div class="module-meta"><span>${engine}</span><span class="badge ${n === 7 ? "orange" : n === 6 ? "blue" : "green"}">${n === 7 ? "MOCK" : n === 6 ? "DIAGNOSTIK" : "REAL"}</span></div></section>`).join("")}</div>${runtimeView()}<section class="panel config-panel"><h2>Ketersediaan bobot</h2><p>Unduhan berada di app/model/weights dan tidak dimasukkan ke Git.</p>${Object.entries(
    workspace.health.files,
  )
    .map(
      ([file, ready]) =>
        `<div class="result-control"><span>${esc(file)}</span><span class="badge ${ready ? "green" : "orange"}">${ready ? "Tersedia" : "Belum tersedia"}</span></div>`,
    )
    .join(
      "",
    )}${workspace.health.last_error ? `<p class="text-error">${esc(workspace.health.last_error)}</p>` : ""}<p class="state-note">Jalankan <code>npm run setup</code> pertama kali, kemudian <code>npm start</code>. Checksum bobot diperiksa sebelum inference.</p></section><section class="panel config-panel"><h2>Ambang pemeriksaan demo</h2><button class="button" data-capacity-config>Kapasitas, jadwal & retensi</button><p>Nilai awal adalah ambang eksperimen. Ambang cosine bukan persentase kecocokan identitas. Ambang classifier gambar hanya referensi diagnostik, tidak menggagalkan KYC.</p><form id="settings-form"><div class="settings-grid">${[
    ["face_cosine", "Minimum cosine SFace", 0.1, 0.9, 0.001],
    ["pad_probability", "Minimum live probability", 0.5, 0.99, 0.01],
    [
      "deepfake_risk",
      "Ambang referensi classifier (diagnostik)",
      0.01,
      0.99,
      0.01,
    ],
    ["blur_min", "Minimum variance Laplacian", 10, 300, 1],
  ]
    .map(
      ([key, label, min, max, step]) =>
        `<div class="field"><label for="${key}">${label}</label><input id="${key}" name="${key}" type="number" min="${min}" max="${max}" step="${step}" value="${settings[key]}" required></div>`,
    )
    .join(
      "",
    )}</div><div class="form-actions"><span class="micro">Tersimpan di backend untuk permohonan berikutnya.</span><button class="button primary" type="submit">Simpan konfigurasi</button></div></form></section>`;
}
function cleanupExport() {
  if (exportURL) {
    URL.revokeObjectURL(exportURL);
    exportURL = null;
  }
}
function modal(title, content) {
  stopCamera();
  cleanupExport();
  const d = $("#modal");
  d.innerHTML = `<div class="modal-head"><h2 id="modal-title">${title}</h2><button class="modal-close" data-close aria-label="Tutup dialog">×</button></div><div class="modal-content">${content}</div>`;
  d.setAttribute("aria-labelledby", "modal-title");
  if (!d.open) d.showModal();
}
function errorMessage(error) {
  const node = $("#step-error") || $("#modal-error");
  if (node) node.textContent = error.message;
  else toast(error.message);
}
async function withBusy(action) {
  if (busy) return;
  busy = true;
  render();
  try {
    await action();
  } catch (error) {
    toast(error.message);
    flow.error = error.message;
  } finally {
    busy = false;
    render();
    if (flow?.error) {
      errorMessage(new Error(flow.error));
      delete flow.error;
    }
  }
}
async function readDocument() {
  if (!flow.documentBlob || !flow.consent) return;
  if (flow.ocr || flow.result) await prepareCapture("document", true);
  const data = new FormData();
  data.append("image", flow.documentBlob, "ktp.jpg");
  await withBusy(async () => {
    flow.ocr = await api(`/sessions/${flow.session.id}/document`, {
      method: "POST",
      body: data,
    });
    flow.step = 1;
    await reloadWorkspace();
  });
}
async function runVerification() {
  if (!flow.livenessResult?.passed || !flow.holdingFeedback?.ready)
    throw new Error(
      "Selesaikan pemeriksaan liveness dan perbaiki foto wajah sebelum melanjutkan.",
    );
  if (!flow.holdingBlob || !flow.selfieBlob || !flow.livenessResult.proof_token)
    return;
  await withBusy(async () => {
    if (flow.pendingVerificationRetry) {
      flow.session = await api(`/sessions/${flow.session.id}/retry`, {
        method: "POST",
      });
      flow.pendingVerificationRetry = false;
    }
    const data = new FormData();
    data.append("nonce", flow.session.nonce);
    data.append("proof_token", flow.livenessResult.proof_token);
    data.append("selfie", flow.selfieBlob, "selfie.jpg");
    data.append("holding", flow.holdingBlob, "holding.jpg");
    try {
      flow.result = await api(`/sessions/${flow.session.id}/verify`, {
        method: "POST",
        body: data,
      });
    } catch (error) {
      if (error.retry?.stage === "verify") flow.pendingVerificationRetry = true;
      throw error;
    }
    flow.step = 4;
    selectedApplication = flow.result.application || null;
    await reloadWorkspace();
  });
  if (
    selectedApplication &&
    !["CAPTURE_RETRY", "TECHNICAL_PENDING"].includes(selectedApplication.state)
  ) {
    page = "result";
    history.replaceState(null, "", "#result");
    render();
  }
  await observeDelivery(selectedApplication);
}
let captureResetting = false;
async function prepareCapture(stage, keepInput = false) {
  if (busy || captureResetting)
    throw new Error("Tunggu pemeriksaan yang sedang berjalan.");
  captureResetting = true;
  stopCamera();
  const currentFlow = flow;
  try {
    const updated = await api(`/sessions/${flow.session.id}/retake`, {
      method: "POST",
      body: JSON.stringify({ stage, nonce: flow.session.nonce }),
    });
    if (flow !== currentFlow) return;
    flow.session = updated;
    flow.pendingVerificationRetry = false;
    flow.result = null;
    stopDeliveryWatch();
    CaptureState.reset(
      flow,
      stage,
      (url) => {
        URL.revokeObjectURL(url);
        urls.delete(url);
      },
      keepInput,
    );
  } finally {
    captureResetting = false;
  }
}
async function retry(stage = null) {
  if (busy || captureResetting) return;
  if (stage) {
    await prepareCapture(stage);
    flow.retryPlan = null;
  } else {
    captureResetting = true;
    const currentFlow = flow,
      previousResult = flow.result;
    try {
      const updated = await api(`/sessions/${flow.session.id}/retry`, {
        method: "POST",
      });
      if (flow !== currentFlow) return;
      stage = updated.retry.stage;
      flow.session = updated;
      flow.pendingVerificationRetry = false;
      flow.retryPlan = updated.retry;
      CaptureState.reset(flow, stage, (url) => {
        URL.revokeObjectURL(url);
        urls.delete(url);
      });
      if (stage === "verify") flow.result = previousResult;
    } finally {
      captureResetting = false;
    }
  }
  flow.step = CaptureState.step(stage);
  render();
  if (stage === "verify") await runVerification();
  else
    toast(
      "Ulangi hanya tahap ini. Capture lain dipertahankan dan akan diperiksa kembali.",
    );
}
async function setImage(blob, kind, checked = null, prepared = false) {
  if (!blob) return;
  const selectedFlow = flow;
  if (blob.size > 5 * 1024 * 1024)
    throw new Error("Ukuran gambar maksimal 5 MB.");
  if (!["image/jpeg", "image/png", "image/webp"].includes(blob.type))
    throw new Error("Gunakan JPG, PNG, atau WebP.");
  const url = preview(blob);
  const image = new Image();
  image.src = url;
  try {
    await image.decode();
  } catch {
    throw new Error("Gambar tidak dapat dibaca.");
  }
  if (image.width * image.height > 16_000_000)
    throw new Error("Gambar maksimal 16 megapiksel.");
  if (flow !== selectedFlow) {
    URL.revokeObjectURL(url);
    return;
  }
  if (!prepared) await prepareCapture(kind);
  if (flow !== selectedFlow) {
    URL.revokeObjectURL(url);
    return;
  }
  flow[kind + "Blob"] = blob;
  flow[kind + "URL"] = url;
  if (kind === "holding" && checked) {
    flow.holdingFeedback = checked;
    render();
    return;
  }
  if (kind === "holding") {
    const currentFlow = flow;
    flow.holdingFeedback = {
      ready: false,
      warnings: [{ message: "Memeriksa wajah dan anti-spoof pada foto…" }],
    };
    render();
    const canvas = document.createElement("canvas");
    const scale = Math.min(1, 640 / image.width);
    canvas.width = Math.round(image.width * scale);
    canvas.height = Math.round(image.height * scale);
    canvas.getContext("2d").drawImage(image, 0, 0, canvas.width, canvas.height);
    const sample = await new Promise((resolve) =>
      canvas.toBlob(resolve, "image/jpeg", 0.8),
    );
    try {
      const result = await inspectBlob(sample, "holding");
      if (flow === currentFlow && flow.holdingBlob === blob)
        flow.holdingFeedback = result;
    } catch (error) {
      if (flow === currentFlow && flow.holdingBlob === blob)
        flow.holdingFeedback = {
          ready: false,
          warnings: [{ message: error.message }],
        };
    }
  }
  render();
}
function stopCamera() {
  cameraToken++;
  clearTimeout(cameraCheckTimer);
  cameraCheckAbort?.abort();
  cameraCheckAbort = null;
  recording = false;
  cameraCheckingPaused = false;
  cameraFeedback = new CaptureFeedback();
  cameraAutoGate = null;
  cameraAutoStopped = false;
  if (stream) {
    stream.getTracks().forEach((t) => t.stop());
    stream = null;
  }
  cameraKind = null;
}
async function openCamera(kind) {
  if (busy || captureResetting) return;
  if (kind === "document" && !flow.consent)
    throw new Error(
      "Setujui pemrosesan lokal sebelum membuka kamera otomatis.",
    );
  await prepareCapture(kind);
  render();
  modal(
    kind === "liveness"
      ? "Pemeriksaan liveness langsung"
      : kind === "holding"
        ? "Foto diri memegang KTP"
        : "Foto KTP",
    `<p>${kind === "liveness" ? "Ikuti tiga tantangan dari server. Setiap tantangan dimulai dengan wajah netral." : kind === "holding" ? "Pegang KTP di bawah dagu. Tampilkan wajah, tangan, dan seluruh teks kartu." : "Dekatkan KTP ke kamera agar teks terlihat tajam."}</p><div class="camera-preview"><video id="camera-video" autoplay playsinline muted aria-label="Pratinjau kamera"></video><canvas id="camera-detection" aria-hidden="true"></canvas><div class="camera-overlay ${kind === "holding" ? "holding" : kind === "document" ? "document" : ""}"><span class="camera-face-guide"></span>${kind !== "liveness" ? '<span class="camera-card-guide">KTP</span>' : ""}</div></div><div class="live-challenge-progress" id="live-challenge-progress"></div><div class="camera-live-prompt" id="camera-prompt">Menunggu kamera…</div><div class="capture-feedback checking" id="camera-feedback" role="status" aria-live="polite">${kind === "document" ? "Dekatkan kartu agar NIK tajam." : "Memeriksa wajah dan risiko foto/layar…"}</div><p class="state-note" id="camera-status">Izinkan kamera jika browser meminta.</p><div class="auto-capture-status">${icon("check")} Pengambilan otomatis · tidak perlu menekan tombol foto atau rekam</div><div class="form-actions"><button class="button" data-close>Batal</button></div>`,
  );
  cameraKind = kind;
  cameraAutoGate = kind === "liveness" ? null : new AutoCaptureGate(kind);
  const token = cameraToken;
  try {
    const media = await navigator.mediaDevices.getUserMedia({
      video: {
        facingMode: { ideal: kind === "document" ? "environment" : "user" },
        width: { ideal: 1920 },
        height: { ideal: 1080 },
      },
      audio: false,
    });
    if (token !== cameraToken || !$("#modal").open) {
      media.getTracks().forEach((t) => t.stop());
      return;
    }
    stream = media;
    const video = $("#camera-video");
    video.srcObject = stream;
    await video.play();
    if (token !== cameraToken) return;
    $("#camera-status").textContent =
      "Kamera aktif. Frame dikirim hanya ke backend lokal untuk pemeriksaan model.";
    $("#camera-prompt").textContent =
      kind === "liveness"
        ? "Posisikan wajah di tengah bingkai."
        : "Pastikan teks KTP tajam dan wajah tidak tertutup.";
    const enable = () => monitorCamera(token);
    if (video.readyState >= 2) enable();
    else video.onloadeddata = enable;
  } catch (error) {
    if (token !== cameraToken) return;
    $("#camera-status").textContent =
      error.name === "NotAllowedError"
        ? "Izin kamera ditolak. Izinkan kamera melalui pengaturan browser untuk merekam liveness."
        : "Kamera tidak tersedia. Gunakan browser lokal dengan webcam yang aktif.";
  }
}
async function captureBlob(maxSide = 1920, quality = 0.95) {
  const video = $("#camera-video");
  if (!video || video.readyState < 2) throw new Error("Kamera belum siap.");
  const scale = Math.min(
    1,
    maxSide / Math.max(video.videoWidth, video.videoHeight),
  );
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(video.videoWidth * scale);
  canvas.height = Math.round(video.videoHeight * scale);
  canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
  return new Promise((resolve, reject) =>
    canvas.toBlob(
      (blob) =>
        blob ? resolve(blob) : reject(new Error("Foto gagal diambil.")),
      "image/jpeg",
      quality,
    ),
  );
}
async function inspectBlob(blob, context, signal) {
  const data = new FormData();
  data.append("image", blob, "preview.jpg");
  data.append("context", context === "holding" ? "holding" : "selfie");
  return api(`/sessions/${flow.session.id}/capture-check`, {
    method: "POST",
    body: data,
    signal,
  });
}
async function inspectAutoBlob(blob, context, signal) {
  const data = new FormData();
  data.append("image", blob, "camera-frame.jpg");
  data.append("context", context);
  return api(`/sessions/${flow.session.id}/auto-capture/check`, {
    method: "POST",
    body: data,
    signal,
  });
}
function showCameraFeedback(state) {
  const target = $("#camera-feedback");
  if (!target) return;
  target.className = `capture-feedback ${state.warnings?.length ? "warning" : state.ready ? "clear" : "checking"}`;
  target.textContent = state.warnings?.length
    ? state.warnings.map((w) => w.message).join(" ")
    : state.ready
      ? cameraKind === "document"
        ? "NIK dan potret KTP terbaca. Menyiapkan foto otomatis…"
        : cameraKind === "holding"
          ? "NIK cocok, tangan dan wajah terlihat. Menyiapkan foto otomatis…"
          : recording
            ? "Wajah terdeteksi. Ikuti instruksi gerakan di atas."
            : "Wajah terlihat jelas. Tantangan liveness dimulai otomatis."
      : "Tahan posisi sebentar untuk pemeriksaan berikutnya…";
}
async function monitorCamera(token) {
  if (
    token !== cameraToken ||
    !stream ||
    cameraCheckingPaused ||
    !$("#modal").open ||
    cameraAutoStopped
  )
    return;
  cameraCheckAbort = new AbortController();
  const timeout = setTimeout(
    () => cameraCheckAbort?.abort(),
    cameraKind === "liveness" ? 8000 : 15000,
  );
  try {
    const kind = cameraKind;
    // Liveness needs successive frames, including motion and recovery frames.
    // Browser sharpness/lighting hints must not starve the server detector.
    // Document/holding auto-capture still uses the local quality gate.
    const local =
      kind === "liveness"
        ? null
        : await qualityGate.inspect($("#camera-video"), kind);
    if (local && !local.ready) {
      cameraAutoGate?.reset();
      cameraFeedback.update(
        {
          ready: false,
          warnings: [
            { code: "client_quality", message: local.warnings.join(" ") },
          ],
        },
        performance.now(),
      );
      $("#camera-feedback").textContent =
        local.warnings.join(" ") + " (pemeriksaan ringan heuristik demo)";
      $("#camera-feedback").className = "capture-feedback warning";
      return;
    }
    // Preserve face texture for PAD. Preview and gesture inference must use
    // the same encoding; resizing/JPEG artifacts can shift model scores.
    const blob = await captureBlob(1920, 0.95);
    if (token !== cameraToken || cameraCheckingPaused) return;
    const result =
      kind === "liveness"
        ? await inspectBlob(blob, kind, cameraCheckAbort.signal)
        : await inspectAutoBlob(blob, kind, cameraCheckAbort.signal);
    clearTimeout(timeout);
    if (token !== cameraToken || cameraCheckingPaused) return;
    drawFaceDetection(
      result.face_box,
      result.image_size,
      result.ready && !result.pad_review_required,
      result.card_box,
    );
    const feedback = cameraFeedback.update(result, performance.now());
    showCameraFeedback(feedback);
    if (kind === "liveness" && feedback.ready) {
      // recordChallenges sets the pause synchronously before its first await;
      // this preview loop therefore cannot schedule a second inference loop.
      void recordChallenges();
    } else if (
      kind !== "liveness" &&
      cameraAutoGate.observe(result, performance.now())
    ) {
      await completeAutomaticPhoto(blob, kind, result, token);
    }
  } catch (error) {
    if (token !== cameraToken || cameraCheckingPaused) return;
    cameraAutoGate?.reset();
    if ([409, 410, 413, 429].includes(error.status)) cameraAutoStopped = true;
    showCameraFeedback(
      cameraFeedback.update(
        {
          ready: false,
          warnings: [
            {
              code: "check_unavailable",
              message:
                "Pemeriksaan kamera belum tersedia: " +
                (error.name === "AbortError"
                  ? "waktu pemeriksaan habis; mencoba lagi."
                  : error.message),
            },
          ],
        },
        performance.now(),
      ),
    );
  } finally {
    clearTimeout(timeout);
    if (token === cameraToken && !cameraCheckingPaused && !cameraAutoStopped)
      cameraCheckTimer = setTimeout(() => monitorCamera(token), 750);
  }
}
async function completeAutomaticPhoto(blob, kind, checked, token) {
  if (token !== cameraToken || !stream) return;
  cameraCheckingPaused = true;
  const currentFlow = flow;
  stopCamera();
  $("#modal").close();
  // Preserve the exact high-resolution blob inspected by the server.
  await setImage(blob, kind, checked, true);
  if (flow !== currentFlow) return;
  if (kind === "document") {
    await readDocument();
    toast("Foto KTP diambil dan dibaca otomatis. Tinjau hasil identitas.");
  } else {
    await runVerification();
  }
}

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
function drawFaceDetection(box, size, ready, cardBox = null) {
  const canvas = $("#camera-detection"),
    video = $("#camera-video");
  if (!canvas || !video) return;
  canvas.width = video.clientWidth;
  canvas.height = video.clientHeight;
  const ctx = canvas.getContext("2d");
  if (!box || !size?.[0] || !size?.[1]) return;
  // Map inference coordinates through object-fit: contain, including letterbox.
  const scale = Math.min(canvas.width / size[0], canvas.height / size[1]);
  const left = (canvas.width - size[0] * scale) / 2;
  const top = (canvas.height - size[1] * scale) / 2;
  ctx.strokeStyle = ready ? "#c4ef94" : "#ffbd79";
  ctx.lineWidth = 3;
  ctx.strokeRect(
    left + box[0] * scale,
    top + box[1] * scale,
    box[2] * scale,
    box[3] * scale,
  );
  ctx.fillStyle = ctx.strokeStyle;
  ctx.font = "600 13px sans-serif";
  ctx.fillText(
    cameraKind === "document"
      ? ready
        ? "Potret KTP terbaca"
        : "Potret KTP terdeteksi; perbaiki capture"
      : ready
        ? "Wajah terdeteksi"
        : "Wajah terdeteksi; periksa peringatan",
    left + box[0] * scale,
    Math.max(16, top + box[1] * scale - 8),
  );
  if (cardBox) {
    ctx.strokeRect(
      left + cardBox[0] * scale,
      top + cardBox[1] * scale,
      cardBox[2] * scale,
      cardBox[3] * scale,
    );
    ctx.fillText(
      "NIK KTP cocok",
      left + cardBox[0] * scale,
      Math.max(16, top + cardBox[1] * scale - 8),
    );
  }
}
function showLiveProgress(result) {
  const completed = result.completed.map((item) => item.challenge);
  $("#live-challenge-progress").innerHTML = flow.session.challenges
    .map(
      (c, i) =>
        `<span class="${completed.includes(c) ? "complete" : result.challenge === c ? "active" : ""}">${completed.includes(c) ? "✓" : i + 1} ${challengeText[c][0]}</span>`,
    )
    .join("");
  const action =
    result.challenge === "turn"
      ? `Putar kepala ke ${result.turn_direction > 0 ? "kiri" : "kanan"} Anda`
      : result.challenge === "blink" && result.blink_closed
        ? "Buka mata kembali"
        : result.challenge
          ? challengeText[result.challenge][0]
          : "Semua gerakan terbaca";
  $("#camera-prompt").textContent =
    result.phase === "neutral"
      ? "Wajah netral, mata terbuka, lihat kamera"
      : action;
  $("#camera-status").textContent =
    `${completed.length}/3 gerakan terpenuhi. ${result.phase === "neutral" ? "Tatap kamera dan rilekskan wajah sebelum gerakan berikutnya." : "Ikuti instruksi; tantangan berganti setelah gerakan terbaca."}`;
}
async function recordChallenges() {
  if (
    recording ||
    cameraAutoStopped ||
    !stream ||
    !cameraFeedback.state(performance.now()).ready
  )
    return;
  recording = true;
  cameraCheckingPaused = true;
  clearTimeout(cameraCheckTimer);
  cameraCheckAbort?.abort();
  const token = cameraToken,
    currentFlow = flow;
  let selfie = null;
  try {
    const capture = await api(`/sessions/${flow.session.id}/liveness/start`, {
      method: "POST",
    });
    if (token !== cameraToken || flow !== currentFlow) return;
    flow.session = { ...flow.session, ...capture };
    flow.livenessResult = null;
    const started = performance.now();
    for (let seq = 0; seq < 360; seq++) {
      if (token !== cameraToken || flow !== currentFlow || !stream) return;
      if (performance.now() - started > 90_000)
        throw new Error("Pemeriksaan terlalu lama. Ulangi liveness.");
      const frameStarted = performance.now();
      // Send every sampled frame. Server visibility, PAD and temporal rules
      // decide whether it contributes evidence; a browser hint cannot skip it.
      const blob = await captureBlob(1920, 0.95);
      const data = new FormData();
      data.append("capture_nonce", capture.capture_nonce);
      data.append("seq", String(seq));
      data.append("image", blob, "frame.jpg");
      cameraCheckAbort = new AbortController();
      const timeout = setTimeout(() => cameraCheckAbort?.abort(), 12000);
      let result;
      try {
        result = await api(`/sessions/${flow.session.id}/liveness/frame`, {
          method: "POST",
          body: data,
          signal: cameraCheckAbort.signal,
        });
      } finally {
        clearTimeout(timeout);
      }
      if (token !== cameraToken || flow !== currentFlow) return;
      if (result.selfie_seq === seq) selfie = blob;
      showLiveProgress(result);
      drawFaceDetection(
        result.feedback.face_box,
        result.image_size,
        result.feedback.ready && !result.feedback.pad_review_required,
      );
      showCameraFeedback(
        cameraFeedback.update(result.feedback, performance.now()),
      );
      if (result.done) {
        flow.livenessResult = result;
        if (!result.passed) throw new Error(result.reason);
        if (!selfie)
          throw new Error(
            "Selfie terikat rekaman belum tersedia. Ulangi pemeriksaan.",
          );
        flow.selfieBlob = selfie;
        flow.selfieURL = preview(selfie);
        stopCamera();
        $("#modal").close();
        if (CaptureState.canVerify(flow)) await runVerification();
        else {
          flow.step = 3;
          render();
          await openCamera("holding");
        }
        return;
      }
      // One request in flight. Camera video remains continuous; inference rate
      // follows CPU capacity, with no fixed duration for individual gestures.
      await delay(Math.max(0, 110 - (performance.now() - frameStarted)));
    }
    throw new Error("Batas frame tercapai. Ulangi pemeriksaan liveness.");
  } catch (error) {
    if (flow !== currentFlow || token !== cameraToken) return;
    flow.livenessResult = {
      passed: false,
      reason:
        error.name === "AbortError"
          ? "Pemeriksaan frame terputus. Ulangi liveness."
          : error.message,
    };
    flow.selfieBlob = null;
    flow.selfieURL = null;
    $("#camera-status").textContent = flow.livenessResult.reason;
    if ([409, 410, 413, 422, 429].includes(error.status))
      cameraAutoStopped = true;
    showCameraFeedback({
      ready: false,
      warnings: [{ message: flow.livenessResult.reason }],
    });
  } finally {
    if (token === cameraToken && flow === currentFlow) {
      recording = false;
      cameraCheckingPaused = false;
      if (stream && !cameraAutoStopped)
        cameraCheckTimer = setTimeout(() => monitorCamera(token), 750);
    }
  }
}

function detail(id) {
  const r = workspace.records.find((r) => r.id === id);
  if (!r) return;
  modal(
    "Detail pemeriksaan",
    `<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:20px"><div><h2>${esc(r.name)}</h2><p>${esc(r.id)} · ${esc(r.nik_masked)}</p></div>${badge(r.status)}</div><p>${esc(r.reason)}</p>${scoreCards(r, { diagnostics: true })}${checkRows(r, { diagnostics: true })}<details class="ocr-raw"><summary>Data model lengkap</summary><pre>${esc(JSON.stringify(r, null, 2))}</pre></details>${r.schedule ? `<p class="validation-note">Jadwal: ${date(r.schedule)} WIB</p>` : ""}${r.note ? `<p>Catatan petugas: ${esc(r.note)}</p>` : ""}${r.application ? `<button class="button primary" data-application="${r.application.id}">Buka permohonan persisten</button>` : "<p>Hasil historis ini tidak mempunyai keputusan permohonan yang berwenang.</p>"}<div class="simulation-note">Pemeriksaan Dukcapil belum dilakukan. Persetujuan petugas dalam aplikasi ini hanya keputusan lokal.</div><div class="form-actions"><button class="button" data-close>Tutup</button><button class="button" data-export-id="${r.id}">Ekspor JSON</button></div>`,
  );
}
function exportFile(name, text, type) {
  const blob = new Blob([text], { type }),
    url = URL.createObjectURL(blob);
  modal(
    "Ekspor hasil",
    `<p>${esc(name)} siap disimpan. Gunakan salin isi file jika browser membatasi unduhan.</p><div class="field"><label for="export-content">Isi file</label><textarea id="export-content" rows="12" readonly>${esc(text)}</textarea></div><div class="buttons"><a class="button primary" href="${url}" download="${esc(name)}">Unduh file</a><button class="button" data-copy>Salin isi file</button><button class="button" data-close>Tutup</button></div>`,
  );
  exportURL = url;
}
function csvCell(value) {
  let text = String(value ?? "");
  if (/^[=+\-@\t\r]/.test(text)) text = "'" + text;
  return '"' + text.replaceAll('"', '""') + '"';
}
function exportCSV(name, head, rows) {
  exportFile(
    name,
    "\uFEFF" +
      [head, ...rows].map((r) => r.map(csvCell).join(",")).join("\r\n"),
    "text/csv;charset=utf-8",
  );
}
function help() {
  modal(
    "Proyek real inference",
    `<p>Backend FastAPI menjalankan OCR, face matching, landmark wajah/tangan, anti-spoofing, dan classifier deepfake dari bobot open source lokal.</p><p>Dukcapil memakai mock dan selalu mengembalikan “belum diverifikasi”. Tidak ada hasil preset atau skor buatan pada pemeriksaan KYC. Halaman pratinjau formulir lanjutan diberi label dan tidak menerbitkan bukti KYC.</p><p>Bukti yang diperlukan, permohonan, hasil model dan catatan disimpan terenkripsi sesuai retensi. Sesi kamera sementara dipisahkan dari keputusan manual yang persisten. Model image deepfake dan pemeriksaan landmark belum menjamin ketahanan terhadap semua serangan.</p><p>API interaktif tersedia di <a href="/docs" target="_blank" rel="noopener">/docs</a>. API memerlukan login dan otorisasi peran/pemilik. Header X-Local-Client hanya marker tambahan, bukan autentikasi.</p><button class="button primary" data-close>Tutup</button>`,
  );
}
document.addEventListener("click", async (event) => {
  const button = event.target.closest("button");
  if (!button || button.disabled) return;
  try {
    if (button.hasAttribute("data-close")) {
      $("#modal").close();
      stopCamera();
    } else if (button.dataset.page) {
      location.hash = button.dataset.page;
      await navigate(button.dataset.page);
    } else if (button.hasAttribute("data-new")) await newFlow();
    else if (button.dataset.upload) $(`#${button.dataset.upload}-file`).click();
    else if (button.dataset.camera) await openCamera(button.dataset.camera);
    else if (button.hasAttribute("data-ocr")) await readDocument();
    else if (button.hasAttribute("data-back")) {
      if (!busy) {
        flow.step = Math.max(0, flow.step - 1);
        render();
      }
    } else if (button.hasAttribute("data-next-holding")) {
      if (!flow.livenessResult?.passed) return;
      if (CaptureState.canVerify(flow)) await runVerification();
      else {
        flow.step = 3;
        render();
      }
    } else if (button.hasAttribute("data-verify")) await runVerification();
    else if (button.hasAttribute("data-retry")) await retry();
    else if (button.dataset.retake) await retry(button.dataset.retake);
    else if (button.dataset.detail) detail(button.dataset.detail);
    else if (button.hasAttribute("data-export-result"))
      exportFile(
        flow.result.id + ".json",
        JSON.stringify(flow.result, null, 2),
        "application/json",
      );
    else if (button.dataset.exportId) {
      const r = workspace.records.find((r) => r.id === button.dataset.exportId);
      exportFile(
        r.id + ".json",
        JSON.stringify(r, null, 2),
        "application/json",
      );
    } else if (button.hasAttribute("data-export-queue"))
      exportCSV(
        "antrean.csv",
        ["ID", "Nama", "Status", "Jadwal"],
        queueRecords().map((r) => [
          r.id,
          r.name,
          statuses[r.status][0],
          r.schedule || "",
        ]),
      );
    else if (button.hasAttribute("data-export-audit"))
      exportCSV(
        "audit.csv",
        ["Waktu UTC", "Aktivitas", "Referensi", "Catatan"],
        workspace.audit.map((e) => [e.created, e.type, e.ref, e.detail]),
      );
    else if (button.hasAttribute("data-copy")) {
      const text = $("#export-content");
      try {
        await navigator.clipboard.writeText(text.value);
        toast("Isi file disalin.");
      } catch {
        text.select();
        toast("Salin teks yang sudah dipilih.");
      }
    }
  } catch (error) {
    errorMessage(error);
  }
});
document.addEventListener("change", async (event) => {
  const target = event.target;
  try {
    if (target.id === "consent") {
      await api(`/applications/${flow.session.application_id}/attest`, {
        method: "POST",
        body: JSON.stringify({ accepted: target.checked }),
      });
      flow.consent = target.checked;
      const readButton = $("[data-ocr]");
      if (readButton) readButton.disabled = !flow.consent || !flow.documentBlob;
      $('[data-camera="document"]').disabled = !flow.consent;
    }
    if (target.id === "document-file" || target.id === "holding-file")
      await setImage(target.files[0], target.id.replace("-file", ""));
    if (target.id === "queue-filter") {
      queueFilter = target.value;
      $("#queue-table").innerHTML = table(queueRecords());
    }
  } catch (error) {
    errorMessage(error);
  }
});
document.addEventListener("input", (event) => {
  if (event.target.id === "queue-search") {
    queueQuery = event.target.value;
    $("#queue-table").innerHTML = table(queueRecords());
  }
});
document.addEventListener("submit", async (event) => {
  const form = event.target;
  if (
    [
      "manual-booking-form",
      "manual-review-form",
      "capacity-config-form",
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
    if (form.id === "identity-form") {
      flow.ocr.fields = await api(`/sessions/${flow.session.id}/identity`, {
        method: "PATCH",
        body: JSON.stringify(data),
      });
      if (CaptureState.canVerify(flow)) await runVerification();
      else {
        flow.step = flow.livenessResult?.passed ? 3 : 2;
        render();
        await openCamera(flow.livenessResult?.passed ? "holding" : "liveness");
      }
    } else if (form.id === "settings-form") {
      workspace.settings = await api("/settings", {
        method: "PUT",
        body: JSON.stringify(
          Object.fromEntries(
            Object.entries(data).map(([k, v]) => [k, Number(v)]),
          ),
        ),
      });
      toast("Ambang backend tersimpan.");
    } else if (form.id === "review-form") {
      await api(`/records/${form.dataset.id}/review`, {
        method: "POST",
        body: JSON.stringify({ ...data, decision: event.submitter.value }),
      });
      $("#modal").close();
      await reloadWorkspace();
      if (flow?.result?.id === form.dataset.id)
        flow.result = workspace.records.find((r) => r.id === form.dataset.id);
      render();
      toast("Keputusan petugas tersimpan.");
    } else if (form.id === "schedule-form") {
      await api(`/records/${form.dataset.id}/schedule`, {
        method: "POST",
        body: JSON.stringify({ at: data.at + "+07:00" }),
      });
      await reloadWorkspace();
      if (flow?.result?.id === form.dataset.id)
        flow.result = workspace.records.find((r) => r.id === form.dataset.id);
      render();
      detail(form.dataset.id);
      toast("Jadwal tersimpan dalam WIB.");
    }
  } catch (error) {
    errorMessage(error);
  }
});
$("#modal").addEventListener("close", () => {
  stopCamera();
  cleanupExport();
});
$("#help")?.addEventListener("click", help);
window.addEventListener("hashchange", () => {
  if (location.hash.slice(1) !== page) navigate(location.hash.slice(1));
});
window.addEventListener("beforeunload", () => {
  stopCamera();
  releasePreviews();
  stopDeliveryWatch();
});
navigate(location.hash.slice(1) || "home");
