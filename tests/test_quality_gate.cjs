const test = require("node:test");
const assert = require("node:assert/strict");
const { QualityGate, LuminanceCheck } = require("../app/view/static/quality-gate.js");
function pixels(width, height, fn) {
  const data = new Uint8ClampedArray(width * height * 4);
  for (let y = 0; y < height; y++)
    for (let x = 0; x < width; x++) {
      const i = (y * width + x) * 4,
        v = fn(x, y);
      data[i] = data[i + 1] = data[i + 2] = v;
      data[i + 3] = 255;
    }
  return data;
}
test("local heuristic warns about dark, blank and glare images", () => {
  const gate = new QualityGate();
  for (const value of [0, 120, 255]) {
    const result = gate.pixels(
      pixels(32, 32, () => value),
      32,
      32,
    );
    assert.equal(result.ready, false);
    assert.equal(result.mode, "heuristic_demo");
    assert.equal(result.face_visibility, "server_required");
    assert.ok(result.warnings.length);
  }
});
test("textured well lit image can pass hints without pretending face detection", () => {
  const result = new QualityGate().pixels(
    pixels(32, 32, (x, y) => ((x + y) % 2 ? 80 : 160)),
    32,
    32,
  );
  assert.equal(result.ready, true);
  assert.equal(result.face_visibility, "server_required");
  assert.ok(result.blur > 0);
});
test("ONNX integration requires a real artifact and checksum", async () => {
  const gate = new QualityGate();
  await assert.rejects(() =>
    gate.loadOnnx({ ort: {}, bytes: new Uint8Array([1]) }),
  );
  assert.equal(gate.model, null);
});
test("old out-of-frame face box cannot veto a fresh holding frame", async (t) => {
  const oldDocument = global.document;
  t.after(() => {
    global.document = oldDocument;
  });
  global.document = {
    createElement: () => ({
      getContext: () => ({
        drawImage: () => {},
        getImageData: () => ({
          data: pixels(32, 32, (x, y) => ((x + y) % 2 ? 80 : 160)),
          width: 32,
          height: 32,
        }),
      }),
    }),
  };
  const gate = new QualityGate();
  // Reproduce the previously cached server box. Face position must be
  // evaluated by the server on the new image, not by this obsolete box.
  gate.lastFace = { box: [-20, 10, 100, 100], size: [640, 480] };
  const result = await gate.inspect(
    { videoWidth: 640, videoHeight: 480 },
    "holding",
  );
  assert.equal(result.ready, true);
  assert.equal(result.face_visibility, "server_required");
});

test("luminance rejects darkness immediately with exact warning and recovery hysteresis", () => {
  const light = new LuminanceCheck();
  const sample = v => light.pixels(pixels(16,16,() => v));
  assert.equal(sample(120).ready, true);
  assert.equal(sample(35).ready, false);
  assert.equal(sample(36).ready, false);
  assert.equal(sample(41).ready, true);
  assert.equal(sample(36).ready, true);
  assert.equal(sample(10).warnings[0].message, "Ruangan terlalu gelap, pindah ke tempat terang");
  assert.equal(light.pixels(new Uint8Array()).ready, false);
});

test("luminance uses RGB weights and never calls the optional quality model", () => {
  const light = new LuminanceCheck();
  assert.ok(Math.abs(light.pixels(new Uint8Array([100,200,50,255])).brightness - 153) < .01);
});

test("luminance samples the raw central video region, excluding bright UI and background", t => {
  const oldDocument = global.document;
  t.after(() => { global.document = oldDocument; });
  let args;
  global.document = {createElement: () => ({getContext: () => ({
    drawImage: (...items) => { args = items; },
    getImageData: () => ({data:pixels(96,96,() => 12)}),
  })})};
  const video = {videoWidth:1000,videoHeight:500,readyState:2};
  const light = new LuminanceCheck();
  assert.equal(light.inspect(video, "liveness").ready, false);
  assert.equal(args[0], video);
  assert.deepEqual(args.slice(1,5), [350,100,300.00000000000006,300.00000000000006]);
  assert.equal(light.inspect({readyState:0}).warnings[0].code, "camera_wait");
});
