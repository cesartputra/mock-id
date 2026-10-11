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
  dashboard: "Ringkasan",
  verify: "Verifikasi baru",
  queue: "Antrean manual",
  audit: "Audit aktivitas",
  modules: "Modul & konfigurasi",
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
    "MiniFASNetV2 · ONNX",
    "Probabilitas live dari selfie dan sampel frame tantangan.",
    "verify",
  ],
  [
    "Risiko manipulasi",
    "ViT deepfake · ONNX",
    "Klasifikasi gambar wajah Real/Fake pada selfie dan foto KYC.",
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
  page = "dashboard",
  flow = null,
  busy = false,
  queueQuery = "",
  queueFilter = "all",
  stream = null,
  cameraKind = null,
  cameraToken = 0,
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
  const response = await fetch("/api" + path, {
    ...options,
    headers: {
      "X-Local-Client": "mock-id",
      ...(options.body instanceof FormData
        ? {}
        : { "Content-Type": "application/json" }),
      ...options.headers,
    },
  });
  const body = await response.json();
  if (!response.ok) {
    const detail = Array.isArray(body.detail)
      ? body.detail
          .map((e) => `${e.loc?.slice(-1)[0] || "Input"}: ${e.msg}`)
          .join("; ")
      : body.detail;
    throw new Error(detail || "Layanan lokal mengalami gangguan.");
  }
  return body;
}
async function reloadWorkspace() {
  workspace = await api("/workspace");
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
  for (const b of $$("nav button[data-page]")) {
    const key = b.dataset.page;
    b.innerHTML = `${icon(key)}<span>${names[key]}</span>${key === "queue" ? `<span class="count">${workspace.records.filter((r) => ["manual", "scheduled"].includes(r.status)).length}</span>` : ""}`;
    b.classList.toggle("active", key === page);
    if (key === page) b.setAttribute("aria-current", "page");
    else b.removeAttribute("aria-current");
  }
  $("#crumb").textContent = names[page];
}
function render() {
  updateNav();
  const views = {
    dashboard,
    verify: verifyView,
    queue: queueView,
    audit: auditView,
    modules: modulesView,
  };
  $("#app").innerHTML = `<div class="screen-enter">${views[page]()}</div>`;
}
async function navigate(target) {
  page = names[target] ? target : "dashboard";
  try {
    await reloadWorkspace();
    if (page === "verify" && !flow) await newFlow(false);
    render();
    window.scrollTo(0, 0);
  } catch (e) {
    $("#app").innerHTML =
      `${head("Backend belum terhubung", "Pastikan server Python sudah berjalan melalui npm start.")}<div class="callout">${esc(e.message)}</div>`;
  }
}
async function newFlow(show = true) {
  if (busy) return;
  stopCamera();
  $("#modal").close();
  releasePreviews();
  const session = await api("/sessions", { method: "POST" });
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
    )}</div><div class="grid-two"><section class="panel"><div class="panel-head"><div><h2>Pipeline pemeriksaan</h2><p>Tanpa pilihan skenario atau skor preset.</p></div><span class="new-tag">CPU INFERENCE</span></div><div class="panel-body">${[
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
      "Wajah, anti-spoof & manipulasi",
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
    )}</div></section><section class="panel"><div class="panel-head"><h2>Status runtime</h2></div><div class="panel-body"><div class="runtime-status">${workspace.health.ready ? icon("check") : icon("info")}<strong>${workspace.health.ready ? "Model tersedia" : "Perlu setup model"}</strong></div><p class="step-description">Inference menggunakan CPU pada komputer ini. Tidak ada foto yang dikirim ke penyedia model.</p><div class="result-control"><span>Penyimpanan</span><span class="badge green">SQLite lokal</span></div><div class="result-control"><span>Bobot model</span><span class="badge gray">SHA-256 pinned</span></div><div class="result-control"><span>Dukcapil</span><span class="badge orange">MOCK · belum terverifikasi</span></div><div class="callout" style="margin-top:20px">Hasil “kontrol lokal terpenuhi” tidak mengonfirmasi keaslian KTP atau identitas resmi. Foto memegang kartu menjadi bukti pendukung untuk ditinjau.</div></div></section></div><section class="panel table-panel"><div class="panel-head"><div><h2>Permohonan terbaru</h2><p>Dataset dimulai kosong; tidak ada permohonan fiktif yang dimuat otomatis.</p></div></div>${table(records.slice(0, 5))}</section>`;
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
  return `${head("Verifikasi identitas", "Capture dan analisis model open source, dijalankan secara lokal.", `<span class="badge green">REAL INFERENCE</span>`, "APPLICANT EXPERIENCE")}<div class="verification-layout"><section class="panel verification-panel"><div class="stepper">${stepNames.map((name, i) => `<div class="step ${flow.step === i ? "current" : flow.step > i ? "done" : ""}"><b>${flow.step > i ? "✓" : i + 1}</b>${name}</div>`).join("")}</div><div class="step-content">${busy ? '<h2>Memproses model…</h2><p class="step-description">OCR, landmark, face matching, anti-spoof, dan classifier gambar sedang diproses di server lokal.</p><span class="spinner"></span><p class="state-note">Tunggu hasil backend. Waktu proses bergantung perangkat dan ukuran capture.</p>' : [documentView, identityView, livenessView, holdingView, resultView][flow.step]()}</div></section><aside class="verification-aside"><section class="panel session-card"><h3>Sesi backend</h3><div class="session-row"><span>ID</span><strong class="session-id">${esc(flow.session.id.slice(0, 8).toUpperCase())}</strong></div><div class="session-row"><span>Percobaan</span><strong>${flow.session.attempt} / ${flow.session.max_attempts}</strong></div><div class="session-row"><span>Berlaku sampai</span><strong>${new Intl.DateTimeFormat("id-ID", { hour: "2-digit", minute: "2-digit", timeZone: "Asia/Jakarta" }).format(new Date(flow.session.expires_at * 1000))} WIB</strong></div><div class="state-note">Nonce sekali pakai dan batas percobaan diperiksa oleh server. Sesi capture berakhir setelah 15 menit atau saat server dimulai ulang.</div></section><section class="panel scenario-card"><h3>Model yang digunakan</h3><p>Semua analisis foto menjalankan model. Tidak ada pemilih hasil simulasi.</p>${["PaddleOCR melalui RapidOCR", "YuNet + SFace", "PIPNet + MediaPipe Hand ONNX", "MiniFASNetV2", "ViT deepfake classifier"].map((n) => `<div class="model-runtime-line"><span class="green-dot"></span>${n}</div>`).join("")}<div class="simulation-note">Dukcapil adalah satu-satunya adapter mock. Hasil identitas resmi tetap “belum diverifikasi”.</div></section></aside></div>`;
}
function documentView() {
  return `<h2>Foto KTP yang akan dibaca</h2><p class="step-description">Unggah atau ambil gambar KTP. Gunakan kartu utuh, teks tajam, dan pencahayaan yang merata.</p><div class="upload-zone">${icon("upload")}<h3>JPG, PNG, atau WebP</h3><p>Maksimal 5 MB / 16 megapiksel</p><div class="upload-buttons"><button class="button" data-camera="document">Buka kamera</button><button class="button primary" data-upload="document">Pilih gambar KTP</button><input type="file" id="document-file" accept="image/jpeg,image/png,image/webp" hidden aria-label="Unggah KTP"></div>${flow.documentURL ? `<img class="image-preview" src="${flow.documentURL}" alt="Pratinjau foto KTP">` : ""}</div><label class="scenario"><input type="checkbox" id="consent" ${flow.consent ? "checked" : ""}><span>Saya setuju memproses capture pada server lokal ini.<small>Foto tetap dalam memori sesi. Hasil dan audit disimpan di SQLite lokal.</small></span></label><p class="text-error" id="step-error" role="alert"></p><div class="form-actions"><span class="micro">NIK akan dibaca model, tanpa isian contoh.</span><button class="button primary" data-ocr ${flow.documentBlob && flow.consent ? "" : "disabled"}>Baca KTP ${icon("arrow")}</button></div>`;
}
function identityView() {
  const fields = flow.ocr.fields;
  return `<h2>Tinjau hasil OCR</h2><p class="step-description">Teks diekstrak oleh model. Nama, tanggal lahir, dan alamat dapat dikoreksi; NIK tetap mengikuti hasil pembacaan untuk dicocokkan dengan foto KYC.</p><div class="validation-note">Confidence pengenalan teks: ${pct(flow.ocr.confidence)} · blur: ${flow.ocr.quality.blur}<br>Confidence OCR bukan skor keaslian dokumen.</div><form id="identity-form"><div class="form-grid"><div class="field wide"><label for="nik">NIK hasil OCR</label><input id="nik" value="${esc(fields.nik)}" readonly></div><div class="field"><label for="name">Nama lengkap</label><input id="name" name="name" value="${esc(fields.name)}" minlength="2" maxlength="80" required></div><div class="field"><label for="birth">Tanggal lahir</label><input id="birth" name="birth" type="date" value="${esc(fields.birth)}"></div><div class="field wide"><label for="address">Alamat</label><input id="address" name="address" value="${esc(fields.address)}" maxlength="200"></div></div><details class="ocr-raw"><summary>Teks mentah OCR</summary><pre>${esc(flow.ocr.lines.join("\n"))}</pre></details><p class="text-error" id="step-error" role="alert"></p><div class="form-actions"><button type="button" class="button" data-back>Kembali</button><button class="button primary" type="submit">Lanjut ke liveness ${icon("arrow")}</button></div></form>`;
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
  return `<h2>Rekam tantangan liveness</h2><p class="step-description">Kamera mengambil frame gerakan. Backend menilai landmark mata, mulut, dan posisi kepala menggunakan PIPNet dan memeriksa anti-spoofing.</p><div class="challenge-list">${flow.session.challenges.map((c, i) => `<div class="challenge ${flow.frames.length ? "complete" : ""}">${flow.frames.length ? "✓" : i + 1} ${challengeText[c][0]}</div>`).join("")}</div><div class="capture capture-real">${flow.selfieURL ? `<img class="image-preview" src="${flow.selfieURL}" alt="Selfie dari rekaman liveness">` : `${icon("face")}<span>Wajah Anda akan muncul setelah rekaman.</span>`}</div><div class="upload-buttons" style="margin-top:18px"><button class="button primary" data-camera="liveness">${icon("face")} ${flow.frames.length ? "Rekam ulang tantangan" : "Buka kamera & rekam"}</button></div><p class="state-note">Setiap tantangan berlangsung ±5 detik. Ikuti ekspresi netral dahulu, kemudian instruksi gerakan. Semua frame diperiksa di backend; tidak ada tombol “lulus simulasi”.</p>${flow.frames.length ? `<div class="validation-note" style="margin-top:18px">${flow.frames.length} frame terekam. Hasil liveness ditentukan setelah pipeline dijalankan.</div>` : ""}<p class="text-error" id="step-error" role="alert"></p><div class="form-actions"><button class="button" data-back>Kembali</button><button class="button primary" data-next-holding ${flow.frames.length ? "" : "disabled"}>Foto bersama KTP ${icon("arrow")}</button></div>`;
}
function holdingView() {
  return `<h2>Foto diri sambil memegang KTP</h2><p class="step-description">Pegang KTP di bawah dagu. Wajah, tangan, empat sudut kartu, dan NIK harus terlihat jelas agar model dapat memeriksanya.</p><div class="kyc-preview">${flow.holdingURL ? `<img class="holding-image" src="${flow.holdingURL}" alt="Foto diri sambil memegang KTP">` : '<div class="kyc-placeholder"><span class="kyc-face-outline"></span><span class="kyc-card-outline">KTP</span><p>Wajah di atas · kartu dan tangan di bawah</p></div>'}</div><div class="kyc-guidance">${[
    ["Wajah tidak tertutup", "Model membandingkan wajah dengan selfie."],
    ["NIK kartu terbaca", "OCR mencocokkan kedua NIK."],
    ["Tangan terlihat", "Landmark tangan diperiksa di dekat kartu."],
  ]
    .map(
      ([title, desc], i) =>
        `<div><span>0${i + 1}</span><strong>${title}</strong><small>${desc}</small></div>`,
    )
    .join(
      "",
    )}</div><div class="upload-buttons"><button class="button primary" data-camera="holding">Ambil foto dengan kamera</button><button class="button" data-upload="holding">Pilih foto bersama KTP</button><input type="file" id="holding-file" accept="image/jpeg,image/png,image/webp" hidden aria-label="Unggah foto memegang KTP"></div><p class="state-note">Foto memegang kartu mendukung pemeriksaan penguasaan dokumen. Keaslian fisik kartu dan identitas resmi belum dikonfirmasi oleh Dukcapil.</p><p class="text-error" id="step-error" role="alert"></p><div class="form-actions"><button class="button" data-back>Kembali</button><button class="button primary" data-verify ${flow.holdingBlob ? "" : "disabled"}>${icon("verify")} Jalankan model</button></div>`;
}
function checkRows(record) {
  return `<div class="result-controls">${record.checks.map((c) => `<div class="result-control"><span>${esc(c.name)}</span><span class="badge ${c.mode === "mock" ? "orange" : c.status === "passed" ? "green" : c.status === "failed" ? "orange" : "blue"}">${c.mode === "mock" ? "MOCK · belum diverifikasi" : c.status === "passed" ? "Terpenuhi" : c.status === "failed" ? "Belum terpenuhi" : "Tidak tersedia"}</span></div>`).join("")}</div>`;
}
function resultView() {
  const r = flow.result;
  if (!r) return "";
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
  return `<div class="result-banner"><div class="result-symbol ${statuses[r.status][1]}">${r.status === "pass" ? "✓" : r.status === "attack" ? "!" : "↻"}</div><h2>${titles[r.status]}</h2><p>${esc(r.reason)}</p>${badge(r.status)}</div><div class="score-grid"><div class="score"><small>Cosine wajah</small><strong>${r.scores.face_cosine?.toFixed(3) ?? "—"}</strong></div><div class="score"><small>Live probability</small><strong>${pct(r.scores.liveness)}</strong></div><div class="score"><small>Fake probability</small><strong>${pct(r.scores.deepfake)}</strong></div></div>${checkRows(r)}<div class="simulation-note">Dukcapil: mock. Identitas resmi belum diverifikasi, termasuk jika seluruh kontrol lokal terpenuhi.</div><div class="state-note">${esc(r.id)} · ${(r.duration_ms / 1000).toFixed(2)} detik inference server<br>Probabilitas model dan ambang belum dikalibrasi untuk penggunaan operasional.</div><div class="form-actions"><button class="button" data-export-result>${icon("download")} Ekspor hasil</button>${["capture", "technical"].includes(r.status) ? `<button class="button primary" data-retry ${flow.session.attempt >= flow.session.max_attempts ? "disabled" : ""}>Ulangi capture (${flow.session.attempt}/${flow.session.max_attempts})</button>` : ["manual", "scheduled"].includes(r.status) ? '<button class="button primary" data-page="queue">Lihat antrean manual</button>' : `<button class="button primary" data-detail="${r.id}">Detail pemeriksaan</button>`}</div><div style="margin-top:20px"><button class="button link" data-new>Mulai sesi baru →</button></div>`;
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
function modulesView() {
  const settings = workspace.settings;
  return `${head("Modul & konfigurasi", "Model benar-benar dijalankan; ketersediaan bobot dapat diperiksa di bawah.", `<span class="badge ${workspace.health.ready ? "green" : "orange"}">${workspace.health.ready ? "Bobot tersedia" : "Setup diperlukan"}</span>`)}<div class="module-grid">${modules.map(([title, engine, desc, i], n) => `<section class="panel module-card">${icon(i)}<h3>${title}</h3><p>${desc}</p><div class="module-meta"><span>${engine}</span><span class="badge ${n === 6 ? "orange" : "green"}">${n === 6 ? "MOCK" : "REAL"}</span></div></section>`).join("")}</div><section class="panel config-panel"><h2>Ketersediaan bobot</h2><p>Unduhan berada di app/model/weights dan tidak dimasukkan ke Git.</p>${Object.entries(
    workspace.health.files,
  )
    .map(
      ([file, ready]) =>
        `<div class="result-control"><span>${esc(file)}</span><span class="badge ${ready ? "green" : "orange"}">${ready ? "Tersedia" : "Belum tersedia"}</span></div>`,
    )
    .join(
      "",
    )}${workspace.health.last_error ? `<p class="text-error">${esc(workspace.health.last_error)}</p>` : ""}<p class="state-note">Jalankan <code>npm run setup</code> pertama kali, kemudian <code>npm start</code>. Checksum bobot diperiksa sebelum inference.</p></section><section class="panel config-panel"><h2>Ambang pemeriksaan demo</h2><p>Nilai awal adalah ambang eksperimen. Ambang cosine bukan persentase kecocokan identitas.</p><form id="settings-form"><div class="settings-grid">${[
    ["face_cosine", "Minimum cosine SFace", 0.1, 0.9, 0.001],
    ["pad_probability", "Minimum live probability", 0.5, 0.99, 0.01],
    ["deepfake_risk", "Maximum fake probability", 0.01, 0.99, 0.01],
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
  if (!flow.holdingBlob || !flow.selfieBlob || !flow.frames.length) return;
  const data = new FormData();
  data.append("nonce", flow.session.nonce);
  data.append("manifest", JSON.stringify(flow.manifest));
  data.append("selfie", flow.selfieBlob, "selfie.jpg");
  data.append("holding", flow.holdingBlob, "holding.jpg");
  flow.frames.forEach((blob, i) =>
    data.append("frames", blob, `frame-${i}.jpg`),
  );
  await withBusy(async () => {
    flow.result = await api(`/sessions/${flow.session.id}/verify`, {
      method: "POST",
      body: data,
    });
    flow.step = 4;
    await reloadWorkspace();
  });
}
async function retry() {
  const updated = await api(`/sessions/${flow.session.id}/retry`, {
    method: "POST",
  });
  flow.session = updated;
  flow.step = 0;
  flow.result = null;
  flow.frames = [];
  flow.manifest = [];
  flow.selfieBlob = null;
  flow.selfieURL = null;
  flow.holdingBlob = null;
  flow.holdingURL = null;
  render();
  toast("Percobaan baru. Ambil ulang capture dan ikuti urutan tantangan baru.");
}
async function setImage(blob, kind) {
  if (!blob) return;
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
  flow[kind + "Blob"] = blob;
  flow[kind + "URL"] = url;
  render();
}
function stopCamera() {
  cameraToken++;
  if (stream) {
    stream.getTracks().forEach((t) => t.stop());
    stream = null;
  }
  cameraKind = null;
}
async function openCamera(kind) {
  if (busy) return;
  modal(
    kind === "liveness"
      ? "Rekam tantangan liveness"
      : kind === "holding"
        ? "Foto diri memegang KTP"
        : "Foto KTP",
    `<p>${kind === "liveness" ? "Ikuti tiga tantangan dari server. Setiap tantangan dimulai dengan wajah netral." : kind === "holding" ? "Pegang KTP di bawah dagu. Tampilkan wajah, tangan, dan seluruh teks kartu." : "Dekatkan KTP ke kamera agar teks terlihat tajam."}</p><div class="camera-preview"><video id="camera-video" autoplay playsinline muted aria-label="Pratinjau kamera"></video><div class="camera-overlay ${kind === "holding" ? "holding" : kind === "document" ? "document" : ""}"><span class="camera-face-guide"></span>${kind !== "liveness" ? '<span class="camera-card-guide">KTP</span>' : ""}</div></div><div class="camera-live-prompt" id="camera-prompt">Menunggu kamera…</div><p class="state-note" id="camera-status">Izinkan kamera jika browser meminta.</p><div class="form-actions"><button class="button" data-close>Batal</button><button class="button primary" ${kind === "liveness" ? "data-record" : "data-photo"} disabled>${kind === "liveness" ? "Mulai rekaman" : "Ambil foto"}</button></div>`,
  );
  cameraKind = kind;
  const token = cameraToken;
  try {
    const media = await navigator.mediaDevices.getUserMedia({
      video: {
        facingMode: { ideal: kind === "document" ? "environment" : "user" },
        width: { ideal: 1280 },
        height: { ideal: 720 },
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
    const enable = () => {
      const btn = $("[data-record]") || $("[data-photo]");
      if (btn) btn.disabled = false;
    };
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
async function captureBlob(maxWidth = 1280, quality = 0.85) {
  const video = $("#camera-video");
  if (!video || video.readyState < 2) throw new Error("Kamera belum siap.");
  const scale = Math.min(1, maxWidth / video.videoWidth);
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
async function takePhoto() {
  const kind = cameraKind;
  const blob = await captureBlob();
  stopCamera();
  $("#modal").close();
  await setImage(blob, kind);
  toast("Foto siap untuk diproses oleh model.");
}
const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
async function recordChallenges() {
  const button = $("[data-record]");
  if (!button || !stream) return;
  button.disabled = true;
  const token = cameraToken,
    currentFlow = flow,
    started = performance.now(),
    frames = [],
    manifest = [];
  let selfie = null;
  try {
    for (let group = 0; group < flow.session.challenges.length; group++) {
      const challenge = flow.session.challenges[group];
      for (let i = 0; i < 14; i++) {
        if (token !== cameraToken || flow !== currentFlow) return;
        $("#camera-prompt").textContent =
          `${group + 1}/3 · ${i < 4 ? "Wajah netral, lihat kamera" : challengeText[challenge][0]}`;
        $("#camera-status").textContent =
          `${i < 4 ? "Bersiap…" : challengeText[challenge][1]} · ${14 - i} frame tersisa`;
        const blob = await captureBlob(640, 0.75);
        frames.push(blob);
        manifest.push({
          challenge,
          t_ms: Math.round(performance.now() - started),
        });
        if (group === 0 && i === 2) selfie = await captureBlob(1280, 0.9);
        await delay(350);
      }
    }
    if (token !== cameraToken) return;
    stopCamera();
    $("#modal").close();
    flow.frames = frames;
    flow.manifest = manifest;
    flow.selfieBlob = selfie;
    flow.selfieURL = preview(selfie);
    render();
    toast("Frame terekam. Lanjutkan foto bersama KTP.");
  } catch (error) {
    if (token === cameraToken) {
      $("#camera-status").textContent = error.message;
      button.disabled = false;
    }
  }
}
function detail(id) {
  const r = workspace.records.find((r) => r.id === id);
  if (!r) return;
  modal(
    "Detail pemeriksaan",
    `<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:20px"><div><h2>${esc(r.name)}</h2><p>${esc(r.id)} · ${esc(r.nik_masked)}</p></div>${badge(r.status)}</div><p>${esc(r.reason)}</p>${checkRows(r)}<details class="ocr-raw"><summary>Data model lengkap</summary><pre>${esc(JSON.stringify(r, null, 2))}</pre></details>${r.schedule ? `<p class="validation-note">Jadwal: ${date(r.schedule)} WIB</p>` : ""}${r.note ? `<p>Catatan petugas: ${esc(r.note)}</p>` : ""}${["manual", "scheduled"].includes(r.status) ? `<form id="review-form" data-id="${r.id}"><div class="field"><label for="note">Catatan pemeriksaan</label><input id="note" name="note" minlength="5" maxlength="250" required></div><div class="buttons"><button class="button primary" type="submit" name="decision" value="approved">Setujui lokal</button><button class="button danger" type="submit" name="decision" value="rejected">Tidak setujui</button></div></form><form class="schedule" id="schedule-form" data-id="${r.id}"><div class="field"><label for="schedule-at">Jadwal pemeriksaan (WIB)</label><input id="schedule-at" name="at" type="datetime-local" required></div><button class="button" type="submit">Simpan jadwal</button></form><p class="text-error" id="modal-error" role="alert"></p>` : ""}<div class="simulation-note">Pemeriksaan Dukcapil belum dilakukan. Persetujuan petugas dalam aplikasi ini hanya keputusan lokal.</div><div class="form-actions"><button class="button" data-close>Tutup</button><button class="button" data-export-id="${r.id}">Ekspor JSON</button></div>`,
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
    `<p>Backend FastAPI menjalankan OCR, face matching, landmark wajah/tangan, anti-spoofing, dan classifier deepfake dari bobot open source lokal.</p><p>Dukcapil memakai mock dan selalu mengembalikan “belum diverifikasi”. Tidak ada pemilih skenario, hasil preset, atau skor buatan.</p><p>Foto dan frame berada dalam memori sesi; nama, NIK tersamarkan, hasil pemeriksaan, serta audit berada di SQLite. Model image deepfake dan pemeriksaan landmark belum menjamin ketahanan terhadap semua serangan.</p><p>API interaktif tersedia di <a href="/docs" target="_blank" rel="noopener">/docs</a>. Untuk request yang mengubah data, sertakan header X-Local-Client: mock-id.</p><button class="button primary" data-close>Tutup</button>`,
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
    else if (button.hasAttribute("data-photo")) await takePhoto();
    else if (button.hasAttribute("data-record")) await recordChallenges();
    else if (button.hasAttribute("data-ocr")) await readDocument();
    else if (button.hasAttribute("data-back")) {
      if (!busy) {
        flow.step = Math.max(0, flow.step - 1);
        render();
      }
    } else if (button.hasAttribute("data-next-holding")) {
      flow.step = 3;
      render();
    } else if (button.hasAttribute("data-verify")) await runVerification();
    else if (button.hasAttribute("data-retry")) await retry();
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
      flow.consent = target.checked;
      $("[data-ocr]").disabled = !flow.consent || !flow.documentBlob;
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
  event.preventDefault();
  const form = event.target;
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
      flow.step = 2;
      render();
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
$("#help").addEventListener("click", help);
window.addEventListener("hashchange", () => {
  if (location.hash.slice(1) !== page) navigate(location.hash.slice(1));
});
window.addEventListener("beforeunload", () => {
  stopCamera();
  releasePreviews();
});
navigate(location.hash.slice(1) || "dashboard");
