const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync("app/view/static/app.js", "utf8");

test("operator entry is restored while applicant registration remains available", () => {
  const html = fs.readFileSync("app/view/static/index.html", "utf8");
  const workflow = fs.readFileSync("app/view/static/workflow-ui.js", "utf8");
  assert.match(
    html,
    /Akses petugas|data-page="account"|Workspace operator|data-page="dashboard"/,
  );
  assert.match(
    workflow,
    /account-form|account-password|auth\/login|function accountView/,
  );
  assert.match(html, /data-page="home"/);
  assert.match(html, /data-page="status"/);
});

test("operator deep links require staff and do not expose a guest workspace", async () => {
  const hashes = [],
    renders = [];
  const context = vm.createContext({
    page: "home",
    principal: { role: "applicant", guest: true },
    selectedApplication: null,
    flow: null,
    navigationRevision: 0,
    verificationEntry: { cancel: () => {} },
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
  assert.deepEqual(hashes, Array(5).fill("#account"));
  assert.deepEqual(renders, Array(5).fill("account"));
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

test("staff navigation honors admin/helpdesk roles and redirects anonymous access to login", async () => {
  for (const [role, expected] of [
    ["admin", "dashboard"],
    ["helpdesk", "queue"],
    [null, "account"],
  ]) {
    const context = vm.createContext({
      page: "home",
      principal: role ? { role } : null,
      selectedApplication: null,
      flow: null,
      navigationRevision: 0,
      verificationEntry: { cancel: () => {} },
      reloadWorkspace: async () => {},
      history: { replaceState: () => {} },
      window: { scrollTo: () => {} },
      render: () => {},
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
    await context.navigate("dashboard");
    assert.equal(context.page, expected);
  }
});

test("API requests select operator cookies only on staff pages", async () => {
  const headers = [];
  const context = vm.createContext({
    page: "home",
    flow: null,
    authEpoch: 0,
    FormData,
    fetch: async (_url, options) => {
      headers.push(options.headers);
      return {};
    },
    readApiResponse: async () => ({}),
  });
  vm.runInContext(
    source.slice(
      source.indexOf("async function api("),
      source.indexOf("async function reloadWorkspace("),
    ),
    context,
  );
  for (const page of ["home", "account", "dashboard", "queue", "result"]) {
    context.page = page;
    await context.api("/auth/me");
  }
  assert.deepEqual(
    headers.map((h) => h["X-Workspace-Mode"]),
    ["public", "operator", "operator", "operator", "public"],
  );
});

test("document and holding intake expose only camera capture, with no gallery picker", () => {
  const context = vm.createContext({flow:{consent:true},icon:()=>"",esc:v=>v});
  for (const [name,end] of [["documentView","identityView"],["holdingView","checkRows"]]) {
    vm.runInContext(source.slice(source.indexOf(`function ${name}(`),
      source.indexOf(`function ${end}(`)),context);
    const html = context[name]();
    assert.match(html,/data-camera=/);
    assert.doesNotMatch(html,/type="file"|data-upload|Pilih gambar|Pilih foto|gambar unggahan/);
  }
});

function cameraIntake() {
  const events = {preview:0,render:0,revoked:[]};
  const context = vm.createContext({
    Blob,Error,flow:{session:{id:"fixture-only"}},
    Image:class {width=1920;height=1080;decode=async()=>{}},
    preview:()=>{events.preview++;return "blob:fixture";},
    URL:{revokeObjectURL:u=>events.revoked.push(u)},
    render:()=>{events.render++;},
  });
  vm.runInContext(source.slice(source.indexOf("async function setImage("),
    source.indexOf("function stopCamera()")),context);
  return {context,events};
}

test("gallery or incomplete camera input cannot replace capture data or reset the session", async () => {
  const {context,events} = cameraIntake();
  const blob = new Blob(["protocol only"],{type:"image/jpeg"});
  const document = {context:"document",ready:true,complete:true,document_capture_token:"bound-server-token"};
  const holding = {context:"holding",ready:true,complete:true,nik_matches:true,hand_detected:true};
  for (const [kind,checked,prepared] of [
    ["document",null,false], ["holding",null,false],
    ["document",document,false], ["document",{...document,complete:false},true],
    ["document",{...document,document_capture_token:null},true],
    ["holding",{...holding,hand_detected:false},true],
    ["holding",{...holding,nik_matches:false},true],
    ["holding",document,true],
  ]) await assert.rejects(context.setImage(blob,kind,checked,prepared),/pengambilan otomatis/);
  assert.equal(events.preview,0);
  assert.equal(events.render,0);
  assert.equal(context.flow.documentBlob,undefined);
  assert.equal(context.flow.holdingBlob,undefined);
});

test("only checked automatic camera photos retain the exact blob and document receipt", async () => {
  const {context,events} = cameraIntake();
  const blob = new Blob(["protocol only"],{type:"image/jpeg"});
  const document = {context:"document",ready:true,complete:true,document_capture_token:"bound-server-token"};
  await context.setImage(blob,"document",document,true);
  assert.equal(context.flow.documentBlob,blob);
  assert.equal(context.flow.documentCaptureToken,document.document_capture_token);
  const holding = {context:"holding",ready:true,complete:true,nik_matches:true,hand_detected:true};
  await context.setImage(blob,"holding",holding,true);
  assert.equal(context.flow.holdingBlob,blob);
  assert.equal(context.flow.holdingFeedback,holding);
  assert.equal(events.render,2);
});
