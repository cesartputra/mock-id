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
  assert.match(html, /tidak menentukan kelulusan/);
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
  });
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
    /Skor PAD rekaman wajah|Foto memegang KTP dinilai terpisah/,
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
