const { test } = require("node:test");
const assert = require("node:assert/strict");
const { CaptureFeedback } = require("../app/view/static/capture-feedback.js");
test("capture needs two fresh clean frames and expires", () => {
  const policy = new CaptureFeedback();
  assert.equal(policy.state(0).ready, false);
  assert.equal(policy.update({ ready: true, warnings: [] }, 10).ready, false);
  assert.equal(policy.update({ ready: true, warnings: [] }, 800).ready, true);
  assert.equal(policy.state(5000).ready, false);
});
test("an occluder immediately disables capture; two repeated warnings stop recording", () => {
  const policy = new CaptureFeedback();
  policy.update({ ready: true, warnings: [] }, 1);
  policy.update({ ready: true, warnings: [] }, 2);
  const bad = {
    ready: false,
    warnings: [{ code: "eyeglasses", message: "Lepaskan kacamata" }],
  };
  assert.equal(policy.update(bad, 100).ready, false);
  assert.equal(policy.mustStopRecording(100), false);
  policy.update(bad, 800);
  assert.equal(policy.mustStopRecording(800), true);
  assert.equal(policy.mustStopRecording(6000), false);
  assert.equal(policy.update({ ready: true, warnings: [] }, 6100).ready, false);
  assert.equal(policy.update({ ready: true, warnings: [] }, 6800).ready, true);
});
test("normal head movement and blinking do not abort the gesture recording", () => {
  const policy = new CaptureFeedback();
  policy.update(
    { ready: false, warnings: [{ code: "blur", message: "blur" }] },
    100,
  );
  policy.update(
    { ready: false, warnings: [{ code: "blur", message: "blur" }] },
    800,
  );
  assert.equal(policy.mustStopRecording(800), false);
});
test("two repeated spoof warnings stop recording", () => {
  const policy = new CaptureFeedback();
  const bad = {
    ready: false,
    warnings: [{ code: "spoof_risk", message: "foto/layar" }],
  };
  policy.update(bad, 100);
  policy.update(bad, 800);
  assert.equal(policy.mustStopRecording(800), true);
});
