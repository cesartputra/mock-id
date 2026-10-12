const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync("app/view/static/app.js", "utf8");

test("public shell has no staff entry, account form or login submission", () => {
  const html = fs.readFileSync("app/view/static/index.html", "utf8");
  const workflow = fs.readFileSync("app/view/static/workflow-ui.js", "utf8");
  assert.doesNotMatch(
    html,
    /Akses petugas|data-page="account"|Workspace operator|data-page="dashboard"/,
  );
  assert.doesNotMatch(
    workflow,
    /account-form|account-password|auth\/login|function accountView/,
  );
  assert.match(html, /data-page="home"/);
  assert.match(html, /data-page="status"/);
});

test("old staff deep links redirect to public home and do not expose an anonymous operator", async () => {
  const hashes = [],
    renders = [];
  const context = vm.createContext({
    page: "home",
    principal: { role: "applicant", guest: true },
    selectedApplication: null,
    flow: null,
    reloadWorkspace: async () => {},
    history: { replaceState: (_state, _title, hash) => hashes.push(hash) },
    window: { scrollTo: () => {} },
    render: () => renders.push(context.page),
    stopDeliveryWatch: () => {},
    names: {},
  });
  vm.runInContext(
    source.slice(
      source.indexOf("const names ="),
      source.indexOf("const statuses ="),
    ),
    context,
  );
  vm.runInContext(
    source.slice(
      source.indexOf("async function navigate("),
      source.indexOf("async function newFlow("),
    ),
    context,
  );
  for (const target of ["account", "dashboard", "queue", "audit", "modules"])
    await context.navigate(target);
  assert.deepEqual(hashes, Array(5).fill("#home"));
  assert.deepEqual(renders, Array(5).fill("home"));
});

test("public bootstrap uses a browser guest session even when an operator session exists", async () => {
  const calls = [];
  const context = vm.createContext({
    accessMode: null,
    principal: null,
    page: "home",
    authEpoch: 0,
    workspace: {},
    applicationRows: [],
    selectedApplication: null,
    operatorMetrics: null,
    capacityCalendar: null,
    api: async (path) => {
      calls.push(path);
      if (path === "/auth/me") {
        const error = new Error("No browser guest");
        error.status = 401;
        throw error;
      }
      if (path === "/auth/guest")
        return { principal: { role: "applicant", guest: true } };
      if (path === "/health") return { ready: true };
      throw new Error("Unexpected staff request: " + path);
    },
  });
  vm.runInContext(
    source.slice(
      source.indexOf("async function reloadWorkspace("),
      source.indexOf("function badge("),
    ),
    context,
  );
  await context.reloadWorkspace();
  assert.deepEqual(calls, ["/auth/me", "/auth/guest", "/health"]);
  assert.equal(context.accessMode, "public");
  assert.equal(context.principal.role, "applicant");
});
