const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const { VerificationEntryGate } = require("../app/view/static/verification-entry.js");
const source = fs.readFileSync("app/view/static/app.js", "utf8");
const puzzle = { challenge_id: "fixture-puzzle", width: 320, height: 180,
  piece_size: 52, piece_y: 30, max_offset: 268, background: "data:image/png;base64,fixture", piece: "data:image/png;base64,fixture" };
const tick = () => new Promise((resolve) => setImmediate(resolve));

function gate(api) {
  const nodes = new Map(), listeners = new Map();
  const dialog = {
    open: false,
    querySelector(id) {
      if (!nodes.has(id)) nodes.set(id, { checked: false, disabled: true, value: "0", style: {}, textContent: "", innerHTML: "" });
      return nodes.get(id);
    },
    addEventListener(event, fn) { listeners.set(event, fn); },
    removeEventListener(event) { listeners.delete(event); },
    close() { this.open = false; listeners.get("close")?.(); },
  };
  let content;
  const instance = new VerificationEntryGate({ api, escape: String, getDialog: () => dialog,
    showDialog(_title, html) { content = html; dialog.open = true; } });
  return { instance, dialog, node: (id) => dialog.querySelector(id), content: () => content };
}

test("checked consent and a valid server receipt advance automatically without a continue button", async () => {
  const calls = [];
  const ui = gate(async (path, options) => {
    calls.push(path);
    if (path.endsWith("challenge")) return puzzle;
    assert.equal(JSON.parse(options.body).offset, 135);
    return { captcha_token: "server-receipt", expires_in: 120 };
  });
  const done = ui.instance.open();
  assert.match(ui.content(), /Saya setuju memproses capture pada server lokal ini/);
  ui.node("#verification-consent").checked = true; ui.instance.acknowledge(); await tick();
  assert.doesNotMatch(ui.content(), /entry-continue|Lanjut ke verifikasi/);
  assert.match(ui.content(), /verifikasi dimulai otomatis/);
  ui.node("#entry-puzzle-slider").value = "135"; ui.instance.movePiece();
  assert.equal(ui.node("#entry-puzzle-piece").style.left, "42.1875%");
  await ui.instance.solve();
  assert.deepEqual(await done, { consent: true, captcha_token: "server-receipt" });
  assert.deepEqual(calls, ["/verification-entry/challenge", "/verification-entry/solve"]);
  assert.equal(ui.dialog.open, false);
});

test("wrong position resets slider and piece, replaces puzzle, and retains consent", async () => {
  let wrong = true, generation = 0;
  const ui = gate(async (path) => {
    if (path.endsWith("challenge")) return {...puzzle, challenge_id: `puzzle-${++generation}`, background: `new-image-${generation}`};
    if (wrong) { const error = new Error("Wrong piece"); error.status = 422; throw error; }
    return { captcha_token: "server-receipt", expires_in: 120 };
  });
  const done = ui.instance.open();
  ui.node("#verification-consent").checked = true; ui.instance.acknowledge(); await tick();
  ui.node("#entry-puzzle-slider").value = "135";
  ui.instance.movePiece();
  await ui.instance.solve();
  assert.equal(ui.instance.pending.challenge.challenge_id, "puzzle-2");
  assert.match(ui.node("#entry-puzzle").innerHTML, /new-image-2/);
  assert.equal(ui.node("#entry-puzzle-slider").value, "0");
  assert.equal(ui.node("#entry-puzzle-piece").style.left, "0%");
  assert.equal(ui.node("#entry-puzzle-slider").disabled, false);
  assert.equal(ui.instance.pending.receipt, null);
  assert.equal(ui.instance.pending.consent, true);
  assert.match(ui.node("#entry-error").textContent, /Slider direset/);
  wrong = false; await ui.instance.solve();
  assert.deepEqual(await done, { consent: true, captcha_token: "server-receipt" });
});

test("cancel and escape discard pending CAPTCHA responses", async () => {
  let reply;
  const ui = gate(() => new Promise((resolve) => { reply = resolve; }));
  const done = ui.instance.open();
  ui.node("#verification-consent").checked = true; ui.instance.acknowledge();
  ui.dialog.close(); assert.equal(await done, null);
  reply(puzzle); await tick();
  assert.equal(ui.instance.pending, null);
  assert.equal(ui.dialog.open, false);
});

test("an invalid or expired receipt cannot advance into capture", async () => {
  const ui = gate(async (path) => path.endsWith("challenge") ? puzzle : { captcha_token: "short-lived", expires_in: 0 });
  const done = ui.instance.open();
  ui.node("#verification-consent").checked = true; ui.instance.acknowledge(); await tick();
  await ui.instance.solve();
  assert.equal(ui.instance.pending.receipt, null);
  assert.equal(ui.instance.pending.consent, true);
  assert.match(ui.node("#entry-error").textContent, /Respons CAPTCHA belum sah/);
  ui.instance.cancel(); await done;
});

test("new capture creates no session or destructive reset until preflight completes", async () => {
  for (const accepted of [false, true]) {
    let resolve, reset = 0, registrationReset = 0;
    const calls = [];
    const original = { documentURL: "existing-preview" };
    const context = vm.createContext({ busy: false, captureResetting: false, principal: { role: "applicant" },
      authEpoch: 0, navigationRevision: 0, flow: original, selectedApplication: { id: "old" }, stopCamera() {},
      $: () => ({ close() {} }), releasePreviews() { reset++; }, stopDeliveryWatch() {}, rememberApplication() {},
      clearRegistrationState() { registrationReset++; },
      verificationEntry: { pending: null, open: () => new Promise((reply) => { resolve = reply; }) },
      api: async (path, options) => { calls.push([path, JSON.parse(options.body)]); return { id: "new", application_id: "new-app" }; },
    });
    vm.runInContext(source.slice(source.indexOf("async function newFlow("), source.indexOf("function table(")), context);
    const done = context.newFlow(false);
    assert.equal(calls.length, 0); assert.equal(reset, 0); assert.equal(registrationReset, 0);
    resolve(accepted ? { consent: true, captcha_token: "fixture-receipt" } : null);
    assert.equal(await done, accepted);
    if (accepted) {
      assert.equal(calls[0][0], "/sessions"); assert.equal(calls[0][1].captcha_token, "fixture-receipt");
      assert.equal(context.flow.consent, true); assert.equal(reset, 1); assert.equal(registrationReset, 1);
    } else { assert.equal(context.flow, original); assert.equal(calls.length, 0); assert.equal(registrationReset, 0); }
  }
});

test("document step no longer renders an inline consent checkbox", () => {
  const context = vm.createContext({ flow: { consent: true }, icon: () => "", esc: String });
  vm.runInContext(source.slice(source.indexOf("function documentView("), source.indexOf("function identityView(")), context);
  assert.doesNotMatch(context.documentView(), /id="consent"|type="checkbox"/);
  assert.match(context.documentView(), /CAPTCHA sudah diselesaikan/);
});


test("consent is read and acknowledged before the puzzle is requested", async () => {
  let calls = 0;
  const ui = gate(async () => { calls++; return puzzle; });
  const done = ui.instance.open();
  assert.match(ui.content(), /Saya menyatakan telah membaca, memahami, dan menyetujui seluruh pernyataan ini/);
  assert.match(ui.content(), /Saya Mengerti/);
  assert.equal(ui.node("#entry-consent-next").disabled, true);
  ui.instance.acknowledge(); await tick();
  assert.equal(calls, 0); assert.equal(ui.instance.pending.step, "consent");
  ui.node("#verification-consent").checked = true; ui.instance.update();
  assert.equal(ui.node("#entry-consent-next").disabled, false);
  ui.instance.acknowledge(); await tick();
  assert.equal(calls, 1); assert.equal(ui.instance.pending.step, "captcha");
  assert.doesNotMatch(ui.content(), /Periksa puzzle/);
  ui.instance.back();
  assert.equal(ui.instance.pending.receipt, null);
  assert.equal(ui.instance.pending.step, "consent");
  ui.instance.cancel(); await done;
});

test("pointer drag waits until release and checks the final offset only once", async () => {
  const answers = [];
  const ui = gate(async (path, options) => {
    if (path.endsWith("challenge")) return puzzle;
    answers.push(JSON.parse(options.body).offset);
    return { captcha_token: "auto-receipt", expires_in: 120 };
  });
  const done = ui.instance.open();
  ui.node("#verification-consent").checked = true; ui.instance.acknowledge(); await tick();
  const slider = ui.node("#entry-puzzle-slider"); slider.id = "entry-puzzle-slider";
  ui.instance.onPointerDown({ target: slider });
  slider.value = "80"; ui.instance.onInput({ target: slider });
  await new Promise((resolve) => setTimeout(resolve, 550));
  assert.deepEqual(answers, []);
  slider.value = "135"; ui.instance.onInput({ target: slider });
  ui.instance.onPointerUp();
  await new Promise((resolve) => setTimeout(resolve, 300));
  assert.deepEqual(answers, [135]);
  ui.instance.onInput({ target: slider }); await tick();
  assert.deepEqual(answers, [135]);
  assert.equal((await done).captcha_token, "auto-receipt");
});

test("keyboard idle is debounced and cancellation removes queued checks", async () => {
  const answers = [];
  const ui = gate(async (path, options) => {
    if (path.endsWith("challenge")) return puzzle;
    answers.push(JSON.parse(options.body).offset);
    const error = new Error("Wrong offset"); error.status = 422; throw error;
  });
  const done = ui.instance.open();
  ui.node("#verification-consent").checked = true; ui.instance.acknowledge(); await tick();
  const slider = ui.node("#entry-puzzle-slider"); slider.id = "entry-puzzle-slider";
  for (const value of [100, 101, 102]) { slider.value = String(value); ui.instance.onInput({ target: slider }); }
  await new Promise((resolve) => setTimeout(resolve, 550));
  assert.deepEqual(answers, [102]);
  assert.equal(slider.value, "0");
  assert.equal(ui.instance.pending.lastCheckedOffset, null);
  assert.deepEqual(answers, [102]);
  slider.value = "103"; ui.instance.onInput({ target: slider });
  ui.instance.cancel(); await done;
  await new Promise((resolve) => setTimeout(resolve, 550));
  assert.deepEqual(answers, [102]);
});

test("expired puzzle automatically loads a new challenge without losing consent", async () => {
  let generation=0;
  const ui=gate(async path => {
    if(path.endsWith('challenge')) return {...puzzle,challenge_id:'fresh-'+(++generation)};
    const error=new Error('Expired');error.status=409;throw error;
  });
  const done=ui.instance.open();ui.node('#verification-consent').checked=true;ui.instance.acknowledge();await tick();
  await ui.instance.solve();
  assert.equal(ui.instance.pending.challenge.challenge_id,'fresh-2');
  assert.equal(ui.instance.pending.consent,true);assert.match(ui.node('#entry-error').textContent,/tidak berlaku/);
  ui.instance.cancel();assert.equal(await done,null);
});

test("cancel while solving ignores a late successful receipt", async () => {
  let reply;
  const ui=gate(path=>path.endsWith('challenge')?Promise.resolve(puzzle):new Promise(resolve=>{reply=resolve;}));
  const done=ui.instance.open();ui.node('#verification-consent').checked=true;ui.instance.acknowledge();await tick();
  const solving=ui.instance.solve();ui.instance.cancel();assert.equal(await done,null);
  reply({captcha_token:'late-token',expires_in:120});await solving;
  assert.equal(ui.instance.pending,null);assert.equal(ui.dialog.open,false);
});

test("server failure stays actionable without renewing puzzles in a loop", async () => {
  const calls=[];
  const ui=gate(async path=>{calls.push(path);if(path.endsWith('challenge'))return puzzle;const error=new Error('Server unavailable');error.status=503;throw error;});
  const done=ui.instance.open();ui.node('#verification-consent').checked=true;ui.instance.acknowledge();await tick();
  await ui.instance.solve();
  assert.equal(calls.length,2);assert.equal(ui.instance.pending.challenge.challenge_id,puzzle.challenge_id);
  assert.equal(ui.instance.pending.receipt,null);assert.equal(ui.instance.pending.solving,false);
  assert.match(ui.node('#entry-error').textContent,/Server unavailable/);
  ui.instance.cancel();await done;
});

test("automatic receipt completion creates exactly one server session through newFlow", async () => {
  const ui=gate(async path=>path.endsWith('challenge')?puzzle:{captcha_token:'auto-receipt',expires_in:120});
  const calls=[];
  const context=vm.createContext({busy:false,captureResetting:false,principal:{role:'applicant'},authEpoch:0,navigationRevision:0,
    flow:null,selectedApplication:null,stopCamera(){},$:()=>({close(){}}),releasePreviews(){},stopDeliveryWatch(){},rememberApplication(){},clearRegistrationState(){},
    verificationEntry:ui.instance,api:async(path,options)=>{calls.push([path,JSON.parse(options.body)]);return{id:'SESSION-AUTO',application_id:'APP-AUTO'};},
  });
  vm.runInContext(source.slice(source.indexOf('async function newFlow('),source.indexOf('function table(')),context);
  const start=context.newFlow(false);ui.node('#verification-consent').checked=true;ui.instance.acknowledge();await tick();
  await Promise.all([ui.instance.solve(),ui.instance.solve()]);assert.equal(await start,true);
  ui.instance.continue();assert.equal(calls.length,1);assert.equal(calls[0][1].captcha_token,'auto-receipt');
  assert.equal(context.flow.session.id,'SESSION-AUTO');assert.equal(ui.dialog.open,false);
});

test("session creation ignores navigation changes and holds admission until its response", async () => {
  for (const phase of ["preflight","session","duplicate","failure"]) {
    let entryReply, sessionReply, sessionFail, opens=0, calls=0, resets=0;
    const original={session:{id:"existing"}}, remembered=[];
    const context=vm.createContext({busy:false,captureResetting:false,principal:{role:"applicant"},authEpoch:0,navigationRevision:0,
      flow:original,selectedApplication:null,stopCamera(){},$:()=>({close(){}}),
      releasePreviews(){resets++;},stopDeliveryWatch(){},rememberApplication:id=>remembered.push(id),
      verificationEntry:{pending:null,open:()=>{opens++;return phase==="preflight" ? new Promise(r=>entryReply=r) : Promise.resolve({consent:true,captcha_token:"fixture-receipt"});}},
      api:()=>{calls++;return new Promise((resolve,reject)=>{sessionReply=resolve;sessionFail=reject;});},
    });
    vm.runInContext(source.slice(source.indexOf("async function newFlow("),source.indexOf("function table(")),context);
    const started=context.newFlow(false);await tick();
    if(phase==="preflight") {
      context.navigationRevision++;entryReply({consent:true,captcha_token:"fixture-receipt"});
      assert.equal(await started,false);assert.equal(calls,0);
    } else if(phase==="failure") {
      const rejected=assert.rejects(started,/Unavailable/);sessionFail(new Error("Unavailable"));await rejected;
    } else {
      if(phase==="session") context.navigationRevision++;
      else {
        const duplicate=context.newFlow(false);await tick();
        assert.equal(opens,1);assert.equal(calls,1);assert.equal(await duplicate,false);
      }
      sessionReply({id:"new",application_id:"APP-NEW"});
      assert.equal(await started,phase==="duplicate");
    }
    assert.equal(context.captureResetting,false);
    if(phase!=="duplicate") {assert.equal(context.flow,original);assert.equal(resets,0);assert.deepEqual(remembered,[]);}
  }
});
