"use strict";
// Only SLIK_READY from the authorized server can trigger a PDF download.
class ReportDelivery {
  constructor({ fetchPdf, savePdf, storage }) {
    this.fetchPdf = fetchPdf;
    this.savePdf = savePdf;
    this.storage = storage;
    this.sent = new Set();
    this.inflight = new Map();
  }
  key(app) {
    return app?.state === "SLIK_READY" && app.slik?.id
      ? `mock-id-pdf-v3:${app.id}:${app.capture_revision}:${app.slik.id}`
      : null;
  }
  delivered(app) {
    const key = this.key(app);
    if (!key) return false;
    try {
      return this.sent.has(key) || this.storage?.getItem(key) === "sent";
    } catch {
      return this.sent.has(key);
    }
  }
  async deliver(app, { manual = false } = {}) {
    const key = this.key(app);
    if (!key || (!manual && this.delivered(app))) return false;
    if (this.inflight.has(key)) return this.inflight.get(key);
    const task = (async () => {
      const blob = await this.fetchPdf(app);
      await this.savePdf(blob, `slik-demo-${app.id}.pdf`);
      this.sent.add(key);
      try {
        this.storage?.setItem(key, "sent");
      } catch {
        /* Private browser storage can be unavailable. */
      }
      return true;
    })();
    this.inflight.set(key, task);
    try {
      return await task;
    } finally {
      this.inflight.delete(key);
    }
  }
}
if (typeof module !== "undefined") module.exports = { ReportDelivery };
