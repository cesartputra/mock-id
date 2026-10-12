// Exercise the shipped camera loops with protocol fixtures, not webcam/AI
// accuracy fixtures. No camera is activated and no private images are used.
const { test } = require("node:test");
const assert = require("node:assert/strict");
const vm = require("node:vm");
const fs = require("node:fs");
const { CaptureFeedback } = require("../app/view/static/capture-feedback.js");
const source = fs.readFileSync("app/view/static/app.js", "utf8");

function camera(kind = "liveness") {
  const elements = new Map();
  const events = {
    localChecks: 0,
    sent: [],
    drawn: [],
    feedback: [],
    starts: 0,
  };
  let clock = 0;
  const context = vm.createContext({
    Blob,
    FormData,
    AbortController,
    Error,
    stream: {},
    cameraKind: kind,
    cameraToken: 7,
    cameraCheckingPaused: false,
    cameraAutoStopped: false,
    recording: false,
    cameraCheckAbort: null,
    cameraCheckTimer: null,
    performance: { now: () => clock },
    setTimeout: () => 1,
    clearTimeout: () => {},
    delay: async () => {
      clock += 200;
    },
    $: (selector) => {
      if (!elements.has(selector)) elements.set(selector, { open: true });
      return elements.get(selector);
    },
    qualityGate: {
      inspect: async () => {
        events.localChecks++;
        return { ready: false, warnings: ["Blur / cahaya lokal"] };
      },
    },
    cameraFeedback: new CaptureFeedback(),
    cameraAutoGate: { reset: () => {}, observe: () => false },
    captureBlob: async (maxSide, quality) => {
      assert.equal(maxSide, 1920);
      assert.equal(quality, 0.95);
      const blob = new Blob([`public protocol frame ${events.sent.length}`]);
      events.sent.push(blob);
      return blob;
    },
    inspectBlob: async () => ({
      ready: true,
      warnings: [],
      face_box: [20, 20, 100, 100],
      image_size: [640, 480],
    }),
    inspectAutoBlob: async () => {
      throw new Error("Local quality should block auto-photo.");
    },
    drawFaceDetection: (...args) => events.drawn.push(args),
    showCameraFeedback: (feedback) => events.feedback.push(feedback),
    recordChallenges: () => {
      events.starts++;
    },
    completeAutomaticPhoto: async () => {
      throw new Error("Unexpected auto-photo.");
    },
    flow: {
      session: { id: "protocol-only", challenges: ["blink", "turn", "smile"] },
    },
    showLiveProgress: () => {},
    preview: () => "protocol-only-preview",
    CaptureState: { canVerify: () => true },
    runVerification: async () => {},
    stopCamera: () => {
      context.stream = null;
    },
    events,
  });
  context.$("#modal").close = () => {
    context.$("#modal").open = false;
  };
  vm.runInContext(
    source.slice(
      source.indexOf("async function monitorCamera("),
      source.indexOf("async function completeAutomaticPhoto("),
    ),
    context,
  );
  return { context, events };
}

test("liveness preview sends fresh frames despite local blur and starts only after two server checks", async () => {
  const { context, events } = camera();
  await context.monitorCamera(7);
  assert.equal(events.sent.length, 1);
  assert.equal(events.starts, 0);
  await context.monitorCamera(7);
  assert.equal(events.sent.length, 2);
  assert.equal(events.starts, 1);
  assert.equal(events.localChecks, 0);
});

test("a detected face with a server mask warning remains visible and does not start liveness", async () => {
  const { context, events } = camera();
  context.inspectBlob = async () => ({
    ready: false,
    warnings: [{ code: "mask", message: "Lepaskan masker" }],
    face_box: [20, 20, 100, 100],
    image_size: [640, 480],
  });
  await context.monitorCamera(7);
  await context.monitorCamera(7);
  assert.equal(events.starts, 0);
  assert.equal(events.drawn[1][2], false);
  assert.ok(events.drawn[1][0]);
  assert.equal(events.feedback[1].warnings[0].code, "mask");
});

test("missing face is rechecked and recovery still requires two fresh server checks", async () => {
  const { context, events } = camera();
  const good = context.inspectBlob;
  context.inspectBlob = async () => ({
    ready: false,
    warnings: [{ code: "face_missing", message: "Wajah belum ditemukan" }],
    face_box: null,
    image_size: [640, 480],
  });
  await context.monitorCamera(7);
  context.inspectBlob = good;
  await context.monitorCamera(7);
  assert.equal(events.starts, 0);
  await context.monitorCamera(7);
  assert.equal(events.sent.length, 3);
  assert.equal(events.starts, 1);
});

test("PAD review starts measured motion but keeps the warning and orange face box", async () => {
  const { context, events } = camera();
  context.inspectBlob = async () => ({
    ready: true,
    pad_review_required: true,
    warnings: [{ code: "pad_review", message: "Diperiksa manual" }],
    face_box: [20, 20, 100, 100],
    image_size: [1920, 1080],
  });
  await context.monitorCamera(7);
  await context.monitorCamera(7);
  assert.equal(events.starts, 1);
  assert.equal(events.drawn[1][2], false);
  assert.equal(events.feedback[1].warnings[0].code, "pad_review");
});

for (const kind of ["document", "holding"])
  test(`${kind} still waits for local quality before auto-photo/server capture`, async () => {
    const { context, events } = camera(kind);
    await context.monitorCamera(7);
    assert.equal(events.localChecks, 1);
    assert.equal(events.sent.length, 0);
    assert.equal(events.starts, 0);
    assert.match(context.$("#camera-feedback").textContent, /Blur/);
  });

function streamCamera({ passed = false, cancel = false } = {}) {
  const fixture = camera();
  const { context, events } = fixture;
  context.cameraFeedback.update({ ready: true, warnings: [] }, 0);
  context.cameraFeedback.update({ ready: true, warnings: [] }, 0);
  let active = 0;
  events.frames = [];
  events.maxActive = 0;
  events.verifications = 0;
  context.runVerification = async () => {
    events.verifications++;
  };
  context.api = async (path, options) => {
    if (path.endsWith("/start")) return { capture_nonce: "protocol-nonce" };
    active++;
    events.maxActive = Math.max(events.maxActive, active);
    await new Promise(setImmediate);
    const seq = Number(options.body.get("seq"));
    events.frames.push({ seq, nonce: options.body.get("capture_nonce") });
    active--;
    if (cancel) context.cameraToken++;
    // A missing sample must reach the server; the client never fabricates
    // completion from frame count, local hints, or a previous clean sample.
    return {
      selfie_seq: 0,
      done: seq === 3,
      passed: seq === 3 && passed,
      proof_token: seq === 3 && passed ? "server-protocol-proof" : null,
      reason: "Server menolak spoof fixture",
      image_size: [960, 720],
      feedback:
        seq === 1
          ? {
              ready: false,
              warnings: [
                { code: "face_missing", message: "Wajah belum ditemukan" },
              ],
              face_box: null,
            }
          : { ready: true, warnings: [], face_box: [20, 20, 100, 100] },
    };
  };
  vm.runInContext(
    source.slice(
      source.indexOf("async function recordChallenges()"),
      source.indexOf("function detail(id)"),
    ),
    context,
  );
  return fixture;
}

test("stream sends consecutive frames through detection gaps with one request in flight and respects server rejection", async () => {
  const { context, events } = streamCamera();
  await context.recordChallenges();
  assert.deepEqual(
    events.frames.map((frame) => frame.seq),
    [0, 1, 2, 3],
  );
  assert.ok(events.frames.every((frame) => frame.nonce === "protocol-nonce"));
  assert.equal(events.maxActive, 1);
  assert.equal(events.localChecks, 0);
  assert.equal(events.verifications, 0);
  assert.equal(context.flow.livenessResult.passed, false);
  assert.equal(context.flow.selfieBlob, null);
});

test("only server completion advances and preserves the exact server-selected selfie frame", async () => {
  const { context, events } = streamCamera({ passed: true });
  await context.recordChallenges();
  assert.equal(events.frames.length, 4);
  assert.equal(events.verifications, 1);
  assert.equal(context.flow.selfieBlob, events.sent[0]);
  assert.equal(
    context.flow.livenessResult.proof_token,
    "server-protocol-proof",
  );
});

test("stream ignores an old camera generation response", async () => {
  const { context, events } = streamCamera({ passed: true, cancel: true });
  await context.recordChallenges();
  assert.equal(events.frames.length, 1);
  assert.equal(events.verifications, 0);
  assert.equal(context.flow.selfieBlob, undefined);
});

test("valid server face box labels presence independently of quality; missing box clears it", () => {
  const { context } = camera();
  const labels = [];
  const canvas = {
    getContext: () => ({
      strokeRect: () => {},
      fillText: (text) => labels.push(text),
    }),
  };
  Object.defineProperty(canvas, "width", {
    set: () => {
      labels.length = 0;
    },
    get: () => 640,
  });
  context.$ = (selector) =>
    selector === "#camera-video"
      ? { clientWidth: 640, clientHeight: 480 }
      : canvas;
  vm.runInContext(
    source.slice(
      source.indexOf("function drawFaceDetection("),
      source.indexOf("function showLiveProgress("),
    ),
    context,
  );
  context.drawFaceDetection([20, 20, 100, 100], [640, 480], false);
  assert.match(labels[0], /^Wajah terdeteksi; periksa peringatan$/);
  context.drawFaceDetection(null, [640, 480], false);
  assert.equal(labels.length, 0);
});
