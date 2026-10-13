const { test } = require("node:test");
const assert = require("node:assert/strict");
const { ReportDelivery } = require("../app/view/static/report-delivery.js");
const ready = {
  id: "APP-TEST",
  capture_revision: 0,
  state: "SLIK_READY",
  slik: { id: "SLIK-TEST" },
};
function fixture(options = {}) {
  const data = new Map();
  let fetched = 0,
    saved = 0;
  const storage = {
    getItem: (k) => data.get(k),
    setItem: (k, v) => data.set(k, v),
  };
  const dependencies = {
    storage,
    fetchPdf: async () => {
      fetched++;
      return "PDF";
    },
    savePdf: async () => {
      saved++;
    },
    ...options,
  };
  return {
    delivery: new ReportDelivery(dependencies),
    counts: () => ({ fetched, saved }),
    dependencies,
  };
}
test("only a ready authorized issuance triggers download, not model pass or manual pending", async () => {
  const f = fixture();
  for (const state of [
    "AUTO_APPROVED",
    "MANUAL_PENDING",
    "MANUAL_IN_REVIEW",
    "SLIK_PENDING",
    "REJECTED",
    "CAPTURE_RETRY",
    "TECHNICAL_PENDING",
  ])
    assert.equal(await f.delivery.deliver({ ...ready, state }), false);
  assert.deepEqual(f.counts(), { fetched: 0, saved: 0 });
  assert.equal(await f.delivery.deliver(ready), true);
  assert.deepEqual(f.counts(), { fetched: 1, saved: 1 });
});
test("poll, reload and concurrent callbacks do not cause duplicate automatic downloads", async () => {
  const f = fixture();
  await Promise.all([f.delivery.deliver(ready), f.delivery.deliver(ready)]);
  await f.delivery.deliver(ready);
  const reload = new ReportDelivery(f.dependencies);
  await reload.deliver(ready);
  assert.deepEqual(f.counts(), { fetched: 1, saved: 1 });
  await reload.deliver(ready, { manual: true });
  assert.deepEqual(f.counts(), { fetched: 2, saved: 2 });
});
test("failed download remains retryable and a new revision/issuance is downloaded", async () => {
  const f = fixture({
    fetchPdf: async () => {
      throw new Error("Server error");
    },
  });
  await assert.rejects(f.delivery.deliver(ready), /Server error/);
  assert.equal(f.delivery.delivered(ready), false);
  f.delivery.fetchPdf = async () => "PDF";
  await f.delivery.deliver(ready);
  await f.delivery.deliver({
    ...ready,
    capture_revision: 1,
    slik: { id: "SLIK-NEW" },
  });
  assert.equal(f.counts().saved, 2);
});
