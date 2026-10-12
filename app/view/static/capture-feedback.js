/* Shared camera policy: two clean frames, stale results never enable capture. */
class CaptureFeedback {
  constructor() {
    this.clean = 0;
    this.warningStreak = 0;
    this.last = null;
    this.key = "";
    this.result = null;
  }
  update(result, now) {
    const key = (result.warnings || [])
      .map((w) => w.code)
      .sort()
      .join(",");
    this.clean = result.ready ? this.clean + 1 : 0;
    this.warningStreak = result.ready
      ? 0
      : key === this.key
        ? this.warningStreak + 1
        : 1;
    this.key = key;
    this.last = now;
    this.result = result;
    return this.state(now);
  }
  state(now) {
    if (this.last === null || now - this.last > 4000)
      return {
        ready: false,
        warnings: [
          { code: "stale", message: "Menunggu pemeriksaan kamera terbaru…" },
        ],
        warningStreak: 0,
      };
    return {
      ...this.result,
      ready: this.result.ready && this.clean >= 2,
      warningStreak: this.warningStreak,
    };
  }
  mustStopRecording(now) {
    const state = this.state(now);
    return (
      state.warningStreak >= 2 &&
      (state.warnings || []).some((w) =>
        [
          "mask",
          "eyeglasses",
          "sunglasses",
          "hand_on_face",
          "spoof_risk",
        ].includes(w.code),
      )
    );
  }
}
if (typeof module !== "undefined") module.exports = { CaptureFeedback };
