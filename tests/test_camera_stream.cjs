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
    lightChecks: 0,
  };
  let clock = 0;
  const context = vm.createContext({
    Blob,
    FormData,
    AbortController,
    Error,
    CaptureFeedback,
    stream: {},
    cameraKind: kind,
    cameraToken: 7,
    cameraCheckingPaused: false,
    cameraAutoStopped: false,
    recording: false,
    cameraCheckAbort: null,
    cameraCheckTimer: null,
    cameraLightBlocked: false,
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
    cameraLightGate: { inspect: () => {
      events.lightChecks++;
      return { ready: true, brightness: 120, warnings: [] };
    } },
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
    inspectAutoBlob: async () => ({
      ready: false,
      complete: false,
      context: kind,
      warnings: [
        { code: "document_quality", message: "Teks kartu belum fokus." },
      ],
    }),
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
  vm.runInContext(source.slice(source.indexOf("function checkCameraLight()"),
    source.indexOf("async function captureBlob(")), context);
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
  test(`${kind} sends fresh frames for actual server ROI quality checks`, async () => {
    const { context, events } = camera(kind);
    await context.monitorCamera(7);
    assert.equal(events.localChecks, 0);
    assert.equal(events.sent.length, 1);
    assert.equal(events.starts, 0);
    assert.equal(events.feedback[0].warnings[0].code, "document_quality");
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

test("dark preview never captures/uploads a frame, resets readiness, and needs fresh server checks after recovery", async () => {
  const { context, events } = camera();
  await context.monitorCamera(7);
  const bright = context.cameraLightGate.inspect;
  context.cameraLightGate.inspect = () => ({ready:false,
    warnings:[{code:"too_dark",message:"Ruangan terlalu gelap, pindah ke tempat terang"}]});
  await context.monitorCamera(7);
  assert.equal(events.sent.length, 1);
  assert.equal(events.starts, 0);
  assert.equal(events.feedback.at(-1).warnings[0].code, "too_dark");
  assert.equal(events.drawn.at(-1)[0], null);
  context.cameraLightGate.inspect = bright;
  context.checkCameraLight();
  assert.equal(events.feedback.at(-1).warnings.length, 0);
  assert.equal(events.feedback.at(-1).ready, false);
  await context.monitorCamera(7);
  assert.equal(events.starts, 0);
  await context.monitorCamera(7);
  assert.equal(events.starts, 1);
});

test("a bright in-flight preview cannot auto-capture after the camera becomes dark", async () => {
  const { context, events } = camera("holding");
  context.inspectAutoBlob = async () => {
    context.cameraLightGate.inspect = () => ({ready:false,
      warnings:[{code:"too_dark",message:"Ruangan terlalu gelap, pindah ke tempat terang"}]});
    return {ready:true,complete:true,warnings:[]};
  };
  let captures = 0;
  context.completeAutomaticPhoto = async () => { captures++; };
  context.cameraAutoGate.observe = () => true;
  await context.monitorCamera(7);
  assert.equal(events.sent.length, 1);
  assert.equal(captures, 0);
  assert.equal(events.feedback.at(-1).warnings[0].code, "too_dark");
});

test("darkness pauses stream once without sending photos or consuming frame sequence, then resumes", async () => {
  const { context, events } = streamCamera({passed:true});
  let dark = true, pauses = 0;
  const bright = context.cameraLightGate.inspect;
  context.cameraLightGate.inspect = () => dark ? {ready:false,
    warnings:[{code:"too_dark",message:"Ruangan terlalu gelap, pindah ke tempat terang"}]} : bright();
  const api = context.api;
  context.api = async (path, options) => {
    if (path.endsWith("/pause")) {
      pauses++;
      assert.equal(options.body.get("seq"), "0");
      assert.equal(options.body.get("image"), null);
      return {paused:true};
    }
    return api(path, options);
  };
  let waits = 0;
  context.delay = async () => {
    if (++waits === 2) {
      assert.equal(events.sent.length, 0);
      assert.equal(pauses, 1);
      dark = false;
    }
  };
  await context.recordChallenges();
  assert.equal(pauses, 1);
  assert.deepEqual(events.frames.map(f => f.seq), [0,1,2,3]);
  assert.equal(events.verifications, 1);
});

test("cancelling during exposure pause cannot submit a later frame or verify", async () => {
  const { context, events } = streamCamera();
  context.cameraLightGate.inspect = () => ({ready:false,warnings:[]});
  const api = context.api;
  context.api = async (path, options) => {
    if (path.endsWith("/pause")) { context.cameraToken++; return {paused:true}; }
    return api(path, options);
  };
  await context.recordChallenges();
  assert.equal(events.sent.length, 0);
  assert.equal(events.verifications, 0);
});

test("white lightbox surrounds only face camera modes and is removed on camera close", async () => {
  const { LuminanceCheck } = require("../app/view/static/quality-gate.js");
  const classes = () => {
    const set = new Set();
    return {add: (...items) => items.forEach(c => set.add(c)),remove: (...items) => items.forEach(c => set.delete(c)),contains: c => set.has(c),toggle: (c,on) => on ? set.add(c) : set.delete(c)};
  };
  const body = {classList:classes()};
  const modal = {classList:classes(),open:true};
  const video = {videoWidth:1920,videoHeight:1080,readyState:2,play:async () => {}};
  const properties = new Map();
  const preview = {classList:classes(),style:{setProperty:(k,v) => properties.set(k,v)}};
  const nodes = new Map([["#modal",modal],["#camera-video",video],
    ["#camera-status",{}],["#camera-prompt",{}],[".camera-preview",preview]]);
  let stopped = 0, cleared = [];
  const context = vm.createContext({
    document:{body}, $: s => nodes.get(s), CaptureFeedback, LuminanceCheck,
    cameraToken:0,cameraCheckTimer:1,cameraLightTimer:2,cameraLightBlocked:false,
    cameraCheckAbort:null,cameraFeedback:null,cameraAutoGate:null,
    cameraAutoStopped:false, cameraCheckingPaused:false,
    cameraLightGate:new LuminanceCheck(),cameraKind:null,recording:false,stream:null,
    busy:false,captureResetting:false,flow:{consent:true},
    AutoCaptureGate:class {}, prepareCapture:async () => {},render:() => {},icon:() => "",
    clearTimeout: id => cleared.push(id),
    navigator:{mediaDevices:{getUserMedia:async () => ({getTracks:() => [{stop:() => stopped++}]})}},
    monitorCameraLight:() => {}, monitorCamera:async () => {},
  });
  context.modal = () => { context.stopCamera(); modal.open = true; };
  vm.runInContext(source.slice(source.indexOf("function stopCamera()"),
    source.indexOf("function checkCameraLight()")), context);
  for (const kind of ["liveness","holding","document"]) {
    await context.openCamera(kind);
    assert.equal(modal.classList.contains("camera-dialog"), true);
    assert.equal(Number(properties.get("--camera-ratio")), 1920/1080);
    video.videoWidth=720; video.videoHeight=1280; video.onresize();
    assert.equal(preview.classList.contains("portrait-video"), true);
    assert.equal(Number(properties.get("--camera-ratio")), 720/1280);
    video.videoWidth=1920; video.videoHeight=1080; video.onresize();
    assert.equal(body.classList.contains("screen-lightbox"), kind !== "document");
    assert.equal(modal.classList.contains("screen-lightbox"), kind !== "document");
    const gate = context.cameraLightGate;
    context.stopCamera();
    assert.equal(body.classList.contains("screen-lightbox"), false);
    assert.equal(modal.classList.contains("screen-lightbox"), false);
    assert.equal(modal.classList.contains("camera-dialog"), false);
    assert.notEqual(context.cameraLightGate, gate);
  }
  assert.equal(stopped, 3);
  assert.ok(cleared.includes(2));
});
