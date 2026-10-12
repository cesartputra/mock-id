const { test } = require("node:test");
const assert = require("node:assert/strict");
const { CaptureState } = require("../app/view/static/capture-state.js");
function completed() {
  return {
    documentBlob: { kind: "document" },
    documentURL: "document-url",
    ocr: { fields: { nik: "test" } },
    selfieBlob: { kind: "selfie" },
    selfieURL: "selfie-url",
    livenessResult: { passed: true, proof_token: "server-proof" },
    holdingBlob: { kind: "holding" },
    holdingURL: "holding-url",
    holdingFeedback: { ready: true },
    frames: [{ frame: true }],
    manifest: [{}],
    result: { status: "capture" },
  };
}
test("held-photo retry retains exact document, selfie and server proof", () => {
  const state = completed(),
    before = { ...state },
    released = [];
  CaptureState.reset(state, "holding", (url) => released.push(url));
  assert.equal(state.documentBlob, before.documentBlob);
  assert.equal(state.ocr, before.ocr);
  assert.equal(state.selfieBlob, before.selfieBlob);
  assert.equal(state.livenessResult, before.livenessResult);
  assert.equal(state.holdingBlob, null);
  assert.equal(state.holdingFeedback, null);
  assert.deepEqual(released, ["holding-url"]);
  assert.equal(CaptureState.canVerify(state), false);
  state.holdingBlob = { kind: "replacement" };
  state.holdingFeedback = { ready: true };
  assert.equal(CaptureState.canVerify(state), true);
});
test("liveness retry clears its proof but keeps the independently captured held photo", () => {
  const state = completed(),
    held = state.holdingBlob,
    document = state.ocr;
  CaptureState.reset(state, "liveness");
  assert.equal(state.selfieBlob, null);
  assert.equal(state.livenessResult, null);
  assert.equal(state.holdingBlob, held);
  assert.equal(state.ocr, document);
  assert.equal(CaptureState.canVerify(state), false);
  state.selfieBlob = { kind: "new-selfie" };
  state.livenessResult = { passed: true, proof_token: "new-proof" };
  assert.equal(CaptureState.canVerify(state), true);
});
test("document retry preserves live-person evidence but requires fresh OCR and comparisons", () => {
  const state = completed(),
    proof = state.livenessResult,
    held = state.holdingBlob;
  CaptureState.reset(state, "document");
  assert.equal(state.ocr, null);
  assert.equal(state.documentBlob, null);
  assert.equal(state.livenessResult, proof);
  assert.equal(state.holdingBlob, held);
  assert.equal(CaptureState.canVerify(state), false);
});
test("technical retry preserves all capture inputs; failed liveness evidence is never retained", () => {
  const state = completed(),
    before = { ...state };
  CaptureState.reset(state, "verify");
  assert.equal(state.selfieBlob, before.selfieBlob);
  assert.equal(state.holdingBlob, before.holdingBlob);
  assert.equal(CaptureState.canVerify(state), true);
  state.livenessResult = { passed: false, proof_token: "stale" };
  CaptureState.reset(state, "document");
  assert.equal(state.livenessResult, null);
  assert.equal(state.selfieBlob, null);
  assert.deepEqual(state.frames, []);
  assert.equal(CaptureState.canVerify(state), false);
});
