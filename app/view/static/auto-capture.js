"use strict";
// Two independent, complete model checks for the same document. A passing
// visibility preview cannot substitute for readable NIK/card/hand evidence.
class AutoCaptureGate {
  constructor(context) {
    this.context = context;
    this.reset();
  }
  reset() {
    this.subject = null;
    this.count = 0;
    this.last = null;
    this.completed = false;
  }
  observe(result, now) {
    if (this.completed || (this.last !== null && now <= this.last))
      return false;
    const valid =
      result.context === this.context &&
      result.ready &&
      result.complete &&
      result.nik_readable &&
      typeof result.subject_key === "string" &&
      (this.context !== "document" ||
        (result.identity_ready &&
          result.verified_frames >= 3 &&
          typeof result.document_capture_token === "string")) &&
      (this.context !== "holding" ||
        (result.nik_matches && result.hand_detected));
    if (!valid) {
      this.reset();
      return false;
    }
    if (this.context === "document") {
      // Three-frame consensus and the selected photo token are server-owned.
      this.completed = true;
      return true;
    }
    this.count =
      this.subject === result.subject_key &&
      this.last !== null &&
      now - this.last <= 8000
        ? this.count + 1
        : 1;
    this.subject = result.subject_key;
    this.last = now;
    if (this.count < 2) return false;
    this.completed = true;
    return true;
  }
}
if (typeof module !== "undefined") module.exports = { AutoCaptureGate };
