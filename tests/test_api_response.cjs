const { test } = require("node:test");
const assert = require("node:assert/strict");
const { readApiResponse } = require("../app/view/static/api-response.js");
test("successful JSON and empty 204 responses", async () => {
  assert.deepEqual(
    await readApiResponse(Response.json({ status: "capture" })),
    { status: "capture" },
  );
  assert.equal(
    await readApiResponse(new Response(null, { status: 204 })),
    null,
  );
});
for (const [label, text, status] of [
  ["plaintext 500", "Internal Server Error", 500],
  ["HTML gateway error", "<html>private diagnostic</html>", 502],
  ["empty unavailable response", "", 503],
  ["plaintext bad request", "Invalid host header", 400],
  ["truncated JSON success", '{"status":', 200],
])
  test(
    label + " preserves status without exposing response contents",
    async () => {
      await assert.rejects(
        readApiResponse(new Response(text, { status })),
        (error) => {
          assert.equal(error.status, status);
          assert.doesNotMatch(
            error.message,
            /SyntaxError|Unexpected token|private diagnostic|Invalid host header|Internal Server Error/,
          );
          assert.match(
            error.message,
            status >= 400
              ? new RegExp(`HTTP ${status}`)
              : /Respons server tidak valid/,
          );
          return true;
        },
      );
    },
  );
test("structured server retry and request ID reach the caller", async () => {
  await assert.rejects(
    readApiResponse(
      Response.json(
        {
          detail: "Coba kembali",
          code: "verification_unavailable",
          request_id: "abc123",
          retry: { stage: "verify" },
        },
        { status: 503 },
      ),
    ),
    (error) => {
      assert.equal(error.status, 503);
      assert.equal(error.retry.stage, "verify");
      assert.equal(error.requestId, "abc123");
      assert.match(error.message, /Coba kembali.*abc123/);
      return true;
    },
  );
});
test("validation details remain actionable", async () => {
  await assert.rejects(
    readApiResponse(
      Response.json(
        { detail: [{ loc: ["body", "selfie"], msg: "Field required" }] },
        { status: 422 },
      ),
    ),
    /selfie: Field required/,
  );
});
test("verification retry rotates nonce and resubmits the same captured blobs", async () => {
  const vm = require("node:vm"),
    fs = require("node:fs");
  const source = fs.readFileSync("app/view/static/app.js", "utf8");
  const flow = {
    session: { id: "test-session", nonce: "original" },
    livenessResult: { passed: true, proof_token: "validated-proof" },
    holdingFeedback: { ready: true },
    selfieBlob: new Blob(["public fixture selfie"]),
    holdingBlob: new Blob(["synthetic held photo"]),
    step: 3,
  };
  const requests = [],
    errors = [];
  const context = vm.createContext({
    flow,
    selectedApplication: null,
    observeDelivery: async () => {},
    FormData,
    Error,
    withBusy: async (action) => {
      try {
        await action();
      } catch (error) {
        errors.push(error);
      }
    },
    reloadWorkspace: async () => {},
    api: async (path, options) => {
      requests.push({ path, options });
      if (requests.length === 1) {
        const error = new Error("Storage unavailable");
        error.retry = { stage: "verify" };
        throw error;
      }
      if (path.endsWith("/retry"))
        return { id: "test-session", nonce: "rotated", revision: 1 };
      return { status: "capture" };
    },
  });
  vm.runInContext(
    source.slice(
      source.indexOf("async function runVerification()"),
      source.indexOf("let captureResetting"),
    ),
    context,
  );
  await context.runVerification();
  assert.equal(requests.length, 1); // No automatic loop on a failing server.
  assert.equal(flow.pendingVerificationRetry, true);
  await context.runVerification();
  assert.equal(requests[1].path, "/sessions/test-session/retry");
  assert.equal(requests[2].options.body.get("nonce"), "rotated");
  assert.equal(requests[2].options.body.get("proof_token"), "validated-proof");
  assert.equal(
    await requests[0].options.body.get("selfie").text(),
    await requests[2].options.body.get("selfie").text(),
  );
  assert.equal(
    await requests[0].options.body.get("holding").text(),
    await requests[2].options.body.get("holding").text(),
  );
  assert.equal(flow.pendingVerificationRetry, false);
  assert.equal(flow.step, 4);
  assert.equal(errors.length, 1);
});
