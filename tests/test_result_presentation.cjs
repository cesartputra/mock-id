const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync("app/view/static/app.js", "utf8");
const context = vm.createContext({
  esc: (value) => String(value),
  pct: (value) =>
    typeof value === "number"
      ? (value * 100).toFixed(1) + "%"
      : "Belum diperiksa",
});
vm.runInContext(
  source.slice(
    source.indexOf("function checkRows("),
    source.indexOf("function resultView()"),
  ),
  context,
);
const result = {
  scores: { face_cosine: 0.62, liveness: 0.972, deepfake: 0.997 },
  rules: { face_cosine: 0.363 },
  checks: [
    { name: "Anti-spoof / PAD", status: "passed", mode: "real" },
    {
      name: "Classifier gambar AI (diagnostik)",
      status: "informational",
      effect: "advisory",
      mode: "real",
      detail: { message: "Belum dikalibrasi; tidak menentukan kelulusan." },
    },
    { name: "Dukcapil", status: "not_verified", mode: "mock" },
  ],
};
test("applicant results show core checks without a fake/manipulation verdict", () => {
  const html = context.scoreCards(result) + context.checkRows(result);
  assert.match(html, /0.620/);
  assert.match(html, /97.2%/);
  assert.match(html, /Anti-spoof/);
  assert.match(html, /MOCK · belum diverifikasi/);
  assert.doesNotMatch(
    html,
    /99.7%|Fake probability|Classifier|manipulasi|Belum terpenuhi/,
  );
});
test("operator diagnostics keep the raw score without labelling it a failed control", () => {
  const html =
    context.scoreCards(result, { diagnostics: true }) +
    context.checkRows(result, { diagnostics: true });
  assert.match(html, /99.7%/);
  assert.match(html, /Diagnostik/);
  assert.match(
    html,
    /Diagnostik opsional, tidak memengaruhi skor atau kelulusan KYC/,
  );
  assert.doesNotMatch(html, /Fake probability|Belum terpenuhi/);
});
test("a real core failure remains visible in applicant results", () => {
  const html = context.checkRows({
    ...result,
    checks: [
      {
        name: "Anti-spoof / PAD",
        status: "failed",
        mode: "real",
        detail: { message: "Risiko foto/layar" },
      },
    ],
  });
  assert.match(html, /Belum terpenuhi/);
  assert.match(html, /Risiko foto\/layar/);
});

test("mock Dukcapil pass is labelled simulation rather than official verification", () => {
  const html = context.checkRows({
    checks: [{ name: "Dukcapil", status: "passed", mode: "mock" }],
  });
  assert.match(html, /MOCK · lolos simulasi/);
  assert.doesNotMatch(html, /MOCK · belum diverifikasi|Terpenuhi/);
});

test("persistent applicant result displays demo Dukcapil pass with manual decision intact", () => {
  const workflow = fs.readFileSync("app/view/static/workflow-ui.js", "utf8");
  const panelContext = vm.createContext({
    esc: String,
    stateLabels: { MANUAL_PENDING: "Pemeriksaan manual diperlukan" },
    approvedStates: [],
    principal: null,
    flow: null,
    page: "result",
    routingExplanation: () => "",
  });
  vm.runInContext(workflow.slice(workflow.indexOf("function routingRequirements("), workflow.indexOf("function routingExplanation(")), panelContext);
  vm.runInContext(
    workflow.slice(
      workflow.indexOf("function applicationPanel("),
      workflow.indexOf("function deliveryView("),
    ),
    panelContext,
  );
  const html = panelContext.applicationPanel({
    id: "APP-PROTOCOL",
    state: "MANUAL_PENDING",
    identity_demo_passed: true,
    identity_verified: false,
  });
  assert.match(html, /MOCK · lolos simulasi/);
  assert.match(html, /Pemeriksaan manual diperlukan/);
  assert.doesNotMatch(
    html,
    /terverifikasi oleh prosedur berwenang|Unduh ulang PDF/,
  );
});

test("new webcam results explain recording score and full-frame diagnostics", () => {
  const current = {
    ...result,
    scores: { face_cosine: 0.632, liveness: 0.97, deepfake: 0.00132 },
    checks: [
      {
        name: "Anti-spoof / PAD",
        status: "passed",
        mode: "real",
        detail: {
          scope: "liveness_recording_and_selfie",
          minimum_live_probability: 0.0001,
        },
      },
      {
        name: "Classifier gambar AI (diagnostik)",
        effect: "advisory",
        status: "informational",
        detail: { input_scope: "full_camera_image" },
      },
    ],
  };
  const applicant = context.scoreCards(current);
  assert.match(
    applicant,
    /Skor PAD rekaman wajah|Foto memegang KTP menjadi kontrol terpisah/,
  );
  assert.doesNotMatch(applicant, /Minimum mentah|Classifier|0.1%/);
  const operator = context.scoreCards(current, { diagnostics: true });
  assert.match(operator, /gambar kamera utuh|Minimum mentah seluruh capture/);
  assert.match(operator, /bukan bukti manipulasi/);
});

test("historic results retain their original score and identify the legacy diagnostic input", () => {
  const html = context.scoreCards(result, { diagnostics: true });
  assert.match(html, /Skor PAD seluruh capture|input versi lama/);
  assert.match(html, /99.7%/);
  assert.doesNotMatch(html, /median|gambar kamera utuh/);
});

test("routing explanation exposes all five contributions and blocks uncertainty clearly", () => {
  const workflow = fs.readFileSync("app/view/static/workflow-ui.js", "utf8");
  const panel = vm.createContext({ esc: String });
  vm.runInContext(
    workflow.slice(
      workflow.indexOf("function routingExplanation("),
      workflow.indexOf("function applicationPanel("),
    ),
    panel,
  );
  const html = panel.routingExplanation({
    contributions: { face: 24, pad: 18, ocr: 9, ai: 0, controls: 25 },
    components: { face: 96, pad: 72, ocr: 90, ai: 0, controls: 83.333 },
    weights: { face: 0.25, pad: 0.25, ocr: 0.1, ai: 0.1, controls: 0.3 },
    ai_evidence_usable: false,
    assessment: {
      blocked_controls: [
        "Classifier gambar AI (diagnostik)",
        "session_nonce_proof",
      ],
    },
  });
  assert.match(html, /25.00%|30.00%|10.00%/);
  assert.match(html, /Poin heuristik|Semua kontrol wajib juga harus terpenuhi/);
  assert.match(html, /tidak mendapat poin bukti|Binding bukti sesi/);
  assert.doesNotMatch(html, /session_nonce_proof/);
  assert.equal(panel.routingExplanation({}), "");
});

test("current uncertain classifier evidence is shown as review without a fraud verdict", () => {
  const current = {
    ...result,
    checks: [
      {
        name: "Classifier gambar AI (diagnostik)",
        mode: "real",
        effect: "required",
        status: "review",
        detail: {
          reliable: false,
          input_scope: "full_camera_image",
          message: "Hasil antar input tidak konsisten",
        },
      },
    ],
  };
  const html =
    context.checkRows(current) +
    context.scoreCards(current, { diagnostics: true });
  assert.match(html, /Perlu tinjauan|antar input tidak konsisten/);
  assert.match(html, /Skor tinggi bukan bukti manipulasi/);
  assert.doesNotMatch(html, /tidak menentukan kelulusan/);
});

test("optional AI is hidden from applicant controls and cannot look like a failed validation", () => {
  const current = {
    ...result,
    ai_validation_required: false,
    checks: [
      {
        name: "Classifier gambar AI (diagnostik)",
        effect: "advisory",
        status: "review",
        mode: "real",
        detail: { reliable: false, message: "Diagnostik opsional" },
      },
    ],
  };
  assert.doesNotMatch(
    context.checkRows(current),
    /Classifier|Perlu tinjauan|Belum terpenuhi/,
  );
  const operator =
    context.checkRows(current, { diagnostics: true }) +
    context.scoreCards(current, { diagnostics: true });
  assert.match(
    operator,
    /badge blue|Diagnostik opsional|tidak memengaruhi skor atau kelulusan KYC/,
  );
  assert.doesNotMatch(operator, /badge orange|Perlu tinjauan|Belum terpenuhi/);
});

test("four-component score explains AI exclusion and normalized weights", () => {
  const workflow = fs.readFileSync("app/view/static/workflow-ui.js", "utf8");
  const panel = vm.createContext({ esc: String });
  vm.runInContext(
    workflow.slice(
      workflow.indexOf("function routingExplanation("),
      workflow.indexOf("function applicationPanel("),
    ),
    panel,
  );
  const html = panel.routingExplanation({
    contributions: { face: 26, pad: 27, ocr: 10, controls: 33 },
    components: { face: 93.6, pad: 97.2, ocr: 90, controls: 99 },
    weights: {
      face: 0.25 / 0.9,
      pad: 0.25 / 0.9,
      ocr: 0.1 / 0.9,
      controls: 0.3 / 0.9,
    },
    ai_validation_required: false,
    ai_evidence_usable: false,
  });
  assert.match(html, /27.78%|11.11%|33.33%/);
  assert.match(
    html,
    /Classifier AI hanya diagnostik opsional dan tidak memengaruhi skor atau kelulusan/,
  );
  assert.doesNotMatch(
    html,
    /tidak mendapat poin bukti dan memerlukan tinjauan|<td>Bukti classifier AI/,
  );
});

test("demo PAD approval explains the exception and preserves the 76.98 score", () => {
  const workflow = fs.readFileSync("app/view/static/workflow-ui.js", "utf8");
  const panel = vm.createContext({esc:String,approvedStates:['SLIK_READY'],stateLabels:{SLIK_READY:'PDF siap'},flow:null,page:'result',principal:null});
  vm.runInContext(workflow.slice(workflow.indexOf('function routingRequirements('),workflow.indexOf('function deliveryView(')),panel);
  const html = panel.applicationPanel({id:'APP-PAD-DEMO',state:'SLIK_READY',routing:{routing_score:76.98388,automatic_threshold:50,calibrated:false,demo_model_override:true,demo_pad_score_routing:true}});
  assert.match(html,/76\.98/);
  assert.match(html,/PAD dinilai melalui skor gabungan/);
  assert.match(html,/Nilai asli tetap tercatat/);
  assert.doesNotMatch(html,/dan seluruh kontrol wajib terpenuhi/);
  const old = panel.applicationPanel({id:'APP-OLD',capture_revision:3,state:'MANUAL_PENDING',demo_policy_recheck_available:true});
  assert.match(old,/data-demo-recheck="APP-OLD" data-revision="3"/);
  assert.match(old,/Terapkan aturan demo ≥50 pada bukti ini/);
});
