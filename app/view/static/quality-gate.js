"use strict";
// Local hints never authorize KYC. Server rechecks all decision controls.
class QualityGate {
  constructor() {
    this.model = null;
    this.mode = "heuristic_demo";
    this.lastFace = null;
  }
  async loadOnnx({
    ort,
    bytes,
    sha256,
    inputSize = 224,
    outputName = "quality",
    threshold = 0.8,
    executionProviders = ["wasm"],
  }) {
    if (!ort?.InferenceSession || !bytes || !/^[a-f0-9]{64}$/.test(sha256))
      throw new Error("Runtime/model kualitas beserta SHA-256 diperlukan.");
    const digest = Array.from(
      new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)),
      (b) => b.toString(16).padStart(2, "0"),
    ).join("");
    if (digest !== sha256)
      throw new Error("Checksum model kualitas tidak sesuai.");
    this.session = await ort.InferenceSession.create(bytes, {
      executionProviders,
    });
    this.model = { ort, inputSize, outputName, threshold };
    this.mode = "onnx_quality";
  }
  pixels(data, width, height) {
    const gray = new Float32Array(width * height);
    let total = 0,
      glare = 0;
    for (let i = 0; i < gray.length; i++) {
      const j = i * 4;
      const v = 0.299 * data[j] + 0.587 * data[j + 1] + 0.114 * data[j + 2];
      gray[i] = v;
      total += v;
      if (v > 248) glare++;
    }
    let sum = 0,
      sum2 = 0,
      count = 0;
    for (let y = 1; y < height - 1; y++)
      for (let x = 1; x < width - 1; x++) {
        const i = y * width + x,
          v =
            4 * gray[i] -
            gray[i - 1] -
            gray[i + 1] -
            gray[i - width] -
            gray[i + width];
        sum += v;
        sum2 += v * v;
        count++;
      }
    const brightness = total / gray.length,
      blur = count ? sum2 / count - (sum / count) ** 2 : 0,
      glareFraction = glare / gray.length;
    const warnings = [];
    if (brightness < 35) warnings.push("Tambahkan pencahayaan di depan Anda.");
    if (brightness > 235 || glareFraction > 0.35)
      warnings.push("Hindari silau atau cahaya langsung ke kamera.");
    if (blur < 8) warnings.push("Tahan posisi dan dekatkan objek agar tajam.");
    return {
      ready: warnings.length === 0,
      warnings,
      brightness,
      blur,
      glareFraction,
      mode: "heuristic_demo",
      face_visibility: "server_required",
    };
  }
  async inspect(video, context) {
    if (!video?.videoWidth)
      return {
        ready: false,
        warnings: ["Menunggu kamera siap."],
        mode: this.mode,
      };
    const canvas = document.createElement("canvas");
    canvas.width = 384;
    canvas.height = Math.round((384 * video.videoHeight) / video.videoWidth);
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    // Inspect central capture area; a bright window in the background should
    // not veto a well-exposed face/card by itself.
    const region = ctx.getImageData(
      Math.round(canvas.width * 0.2),
      Math.round(canvas.height * 0.15),
      Math.round(canvas.width * 0.6),
      Math.round(canvas.height * 0.7),
    );
    const result = this.pixels(region.data, region.width, region.height);
    if (this.lastFace && context !== "document") {
      const { box, size } = this.lastFace;
      const [x, y, w, h] = box;
      const [iw, ih] = size;
      if (w / iw < 0.08 || x < 0 || y < 0 || x + w > iw || y + h > ih) {
        result.ready = false;
        result.warnings.push("Posisikan wajah utuh di depan kamera.");
      }
    }
    if (this.model) {
      const { ort, inputSize, outputName, threshold } = this.model;
      canvas.width = inputSize;
      canvas.height = inputSize;
      ctx.drawImage(video, 0, 0, inputSize, inputSize);
      const image = ctx.getImageData(0, 0, inputSize, inputSize).data;
      const input = new Float32Array(inputSize * inputSize * 3);
      for (let p = 0; p < inputSize * inputSize; p++)
        for (let c = 0; c < 3; c++)
          input[c * inputSize * inputSize + p] = image[p * 4 + c] / 255;
      const output = await this.session.run({
        [this.session.inputNames[0]]: new ort.Tensor("float32", input, [
          1,
          3,
          inputSize,
          inputSize,
        ]),
      });
      const score = Number(output[outputName]?.data?.[0]);
      if (!Number.isFinite(score) || score < 0 || score > 1)
        throw new Error("Kontrak output model kualitas tidak valid.");
      result.model_quality = score;
      result.mode = this.mode;
      if (score < threshold) {
        result.ready = false;
        result.warnings.push(
          "Kualitas gambar belum memadai menurut model kualitas.",
        );
      }
    }
    return result;
  }
}
if (typeof module !== "undefined") module.exports = { QualityGate };
