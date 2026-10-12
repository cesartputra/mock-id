"use strict";
// Capture evidence is independent; final verify always recomputes comparisons
// against the current document, selfie proof and held photo.
const CaptureState = {
  reset(flow, stage, release = () => {}, keepInput = false) {
    const clear = (kind) => {
      if (flow[kind + "URL"]) release(flow[kind + "URL"]);
      flow[kind + "Blob"] = null;
      flow[kind + "URL"] = null;
    };
    flow.result = null;
    if (stage === "holding") {
      clear("holding");
      flow.holdingFeedback = null;
    }
    if (stage === "liveness" || !flow.livenessResult?.passed) {
      clear("selfie");
      flow.livenessResult = null;
      flow.frames = [];
      flow.manifest = [];
    }
    if (stage === "document") {
      flow.ocr = null;
      flow.documentCaptureToken = null;
      if (!keepInput) clear("document");
    }
  },
  canVerify(flow) {
    return !!(
      flow.ocr &&
      flow.selfieBlob &&
      flow.livenessResult?.passed &&
      flow.livenessResult.proof_token &&
      flow.holdingBlob &&
      flow.holdingFeedback?.ready
    );
  },
  step(stage) {
    return { document: 0, liveness: 2, holding: 3, verify: 4 }[stage];
  },
};
if (typeof module !== "undefined") module.exports = { CaptureState };
