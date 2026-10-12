const { test } = require("node:test");
const assert = require("node:assert/strict");
const { AutoCaptureGate } = require("../app/view/static/auto-capture.js");
function ready(context = "holding", subject = "card-a") {
  return {
    context,
    ready: true,
    complete: true,
    nik_readable: true,
    nik_matches: true,
    hand_detected: true,
    subject_key: subject,
  };
}
test("a clean face alone cannot cause automatic held-card capture", () => {
  const gate = new AutoCaptureGate("holding");
  for (let n = 0; n < 5; n++)
    assert.equal(
      gate.observe({ context: "holding", ready: true }, n * 900),
      false,
    );
  for (const missing of [
    "complete",
    "nik_readable",
    "nik_matches",
    "hand_detected",
  ]) {
    gate.reset();
    const result = { ...ready(), [missing]: false };
    assert.equal(gate.observe(result, 1000), false);
    assert.equal(gate.observe(result, 2000), false);
  }
});
test("auto capture needs two complete readings of the same card and fires once", () => {
  const gate = new AutoCaptureGate("holding");
  assert.equal(gate.observe(ready(), 1000), false);
  assert.equal(gate.observe(ready("holding", "card-b"), 2000), false);
  assert.equal(gate.observe(ready("holding", "card-b"), 3000), true);
  assert.equal(gate.observe(ready("holding", "card-b"), 4000), false);
});
test("warning, stale interval, cancellation or duplicate callback cannot complete capture", () => {
  const gate = new AutoCaptureGate("document");
  assert.equal(gate.observe(ready("document"), 1000), false);
  assert.equal(gate.observe(ready("document"), 1000), false);
  assert.equal(
    gate.observe({ ...ready("document"), ready: false }, 2000),
    false,
  );
  assert.equal(gate.observe(ready("document"), 3000), false);
  assert.equal(gate.observe(ready("document"), 12000), false);
  gate.reset();
  assert.equal(gate.observe(ready("document"), 13000), false);
  assert.equal(gate.observe(ready("document"), 14000), true);
});
test("another camera context never satisfies the document gate", () => {
  const gate = new AutoCaptureGate("document");
  assert.equal(gate.observe(ready("holding"), 1000), false);
  assert.equal(gate.observe(ready("holding"), 2000), false);
});
