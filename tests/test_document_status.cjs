const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { documentStatusView } = require('../app/view/static/document-status.js');
const source = fs.readFileSync('app/view/static/registration.js', 'utf8');
const workflow = fs.readFileSync('app/view/static/workflow-ui.js', 'utf8');
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const deps = { escape: esc, icon: name => `<svg data-icon="${name}"></svg>`, formatTime: value => value + ' WIB' };
function context(overrides = {}) {
  const listeners = {};
  const ctx = vm.createContext({
    document: { addEventListener: (name, callback) => { listeners[name] = callback; }, querySelector: () => null },
    authEpoch: 0, navigationRevision: 0, page: 'status', selectedApplication: null, flow: null,
    esc, icon: deps.icon, documentStatusView,
    approvedStates: ['AUTO_APPROVED', 'MANUAL_APPROVED', 'SLIK_PENDING', 'SLIK_READY'],
    stateLabels: { SLIK_READY: 'PDF tersedia', MANUAL_SCHEDULED: 'Antrean manual' },
    sessionStorage: { getItem: () => null }, stopDeliveryWatch: () => {}, rememberApplication: () => {},
    ...overrides,
  });
  vm.runInContext(source, ctx);
  vm.runInContext(workflow.slice(workflow.indexOf('function routingRequirements('), workflow.indexOf('function routingExplanation(')), ctx);
  return { ctx, listeners };
}
function read(ctx, expression) { return vm.runInContext(expression, ctx); }

test('tracker uses semantic stages, readable statuses and escaped server values', () => {
  const html = documentStatusView({updated:'server-time',revision:2,stages:[
    {key:'received',label:'Dokumen Diterima',status:'done',message:'Diterima',at:'received-time'},
    {key:'review',label:'Dokumen Direview',status:'failed',message:'<script>alert(1)</script>',at:null},
    {key:'complete',label:'Selesai',status:'pending',message:'PDF belum tersedia',at:null},
  ]}, deps);
  assert.match(html, /<ol class="document-timeline">/);
  assert.match(html, /document-stage failed" aria-current="step"/);
  assert.match(html, /&lt;script&gt;/);
  assert.doesNotMatch(html, /<script>/);
  assert.match(html, /bukti versi 2/);
  assert.equal((html.match(/<time /g)||[]).length, 1);
});

test('unknown server status stays pending and missing progress makes no success claim', () => {
  assert.equal(documentStatusView(null, deps), '');
  const html = documentStatusView({stages:[{status:'<script>',label:'Belum dinilai',message:''}]}, deps);
  assert.match(html, /document-stage pending/);
  assert.doesNotMatch(html, /document-stage done/);
});

test('lookup stays on status page and resolves linked registration to live application', async () => {
  const application = {id:'APP-TEST',state:'MANUAL_SCHEDULED',document_progress:{stages:[]}};
  const { ctx } = context({api: async () => ({id:'DEMO-TEST',name:'PEMOHON DEMO',application})});
  assert.equal(await ctx.loadServiceStatus('DEMO-TEST'), true);
  assert.equal(ctx.page, 'status');
  assert.equal(read(ctx, 'serviceStatus.id'), 'DEMO-TEST');
  ctx.selectedApplication = {...application,state:'SLIK_READY'};
  assert.equal(ctx.serviceApplication().state, 'SLIK_READY');
  assert.match(ctx.serviceStatusDetails(), /Unduh ulang PDF SLIK demo/);
});

test('late lookup cannot replace a newer result or a different owner/page', async () => {
  const pending = [];
  const { ctx } = context({api: path => new Promise(resolve => pending.push({path,resolve}))});
  const first = ctx.loadServiceStatus('APP-OLD');
  const second = ctx.loadServiceStatus('APP-NEW');
  pending[1].resolve({id:'APP-NEW',state:'SLIK_PENDING'});
  assert.equal(await second, true);
  pending[0].resolve({id:'APP-OLD',state:'SLIK_READY'});
  assert.equal(await first, false);
  assert.equal(read(ctx, 'serviceStatus.id'), 'APP-NEW');
  const third = ctx.loadServiceStatus('APP-OTHER');
  ctx.authEpoch++;
  pending[2].resolve({id:'APP-OTHER',state:'SLIK_READY'});
  assert.equal(await third, false);
  const fourth = ctx.loadServiceStatus('APP-AWAY');
  ctx.page = 'home';
  pending[3].resolve({id:'APP-AWAY'});
  assert.equal(await fourth, false);
});

test('draft lookup survives poll renders and auth reset clears identity/status', () => {
  const { ctx, listeners } = context();
  listeners.input({target:{id:'registration-number',value:'APP-TYPING'}});
  assert.match(ctx.publicStatus(), /value="APP-TYPING"/);
  ctx.clearRegistrationState();
  assert.equal(read(ctx, 'statusNumberDraft'), '');
  assert.equal(read(ctx, 'serviceStatus'), null);
  assert.equal(read(ctx, 'registrationIdentity'), null);
});

test('registration identity is read from server context and never posted as caller authority', async () => {
  const routes = [];
  const { ctx } = context({api: async path => {routes.push(path); return {name:'SERVER NAME',nik:'1234567890123456',birth:'1990-01-01',address:'SERVER ADDRESS'};}, navigate: async () => {}});
  await ctx.startPostKycRegistration({id:'APP-TEST'});
  const html = ctx.registrationFields(read(ctx, 'registrationDraft'));
  assert.deepEqual(routes, ['/applications/APP-TEST/registration-context']);
  assert.match(html, /value="SERVER NAME"[^>]*readonly/);
  assert.match(html, /id="registration-birth"[^>]*value="1990-01-01"[^>]*readonly/);
  assert.doesNotMatch(html, /name="nik"|name="birth"/);
});

test('status polling follows live server stages and downloads only after ready', async () => {
  const callbacks = [], delivered = [], rendered = [];
  const { ctx } = context({
    principal:{role:'applicant'}, deliveryWatchEpoch:0, deliveryTimer:null,
    setTimeout: fn => {callbacks.push(fn);return callbacks.length;}, clearTimeout:()=>{},
    render:()=>rendered.push(ctx.selectedApplication.state),
    deliverPdf: async app => delivered.push(app.state),
    api: async () => ({id:'APP-TEST',state:'SLIK_READY',document_progress:{stages:[{status:'done'}]}}),
  });
  vm.runInContext(workflow.slice(workflow.indexOf('async function observeDelivery('), workflow.indexOf('document.addEventListener("click"')), ctx);
  vm.runInContext('serviceStatus = {id:"APP-TEST", application:{id:"APP-TEST",state:"MANUAL_SCHEDULED"}}', ctx);
  await ctx.observeDelivery(read(ctx, 'serviceStatus.application'));
  assert.deepEqual(delivered, []);
  await callbacks[0]();
  assert.deepEqual(rendered, ['SLIK_READY']);
  assert.deepEqual(delivered, ['SLIK_READY']);
  assert.equal(ctx.serviceApplication().document_progress.stages[0].status, 'done');
});

test('poll preserves the lookup node/focus and does not redraw unchanged states', async () => {
  const callbacks = [], target = {innerHTML:''}, lookup = {value:'APP-TYPING',focused:true};
  let phase = 0, fullRenders = 0;
  const initial = {id:'APP-TEST',state:'MANUAL_SCHEDULED',updated:'same',capture_revision:1};
  const {ctx} = context({
    document:{addEventListener:()=>{},querySelector: selector => {
      assert.equal(selector, '#service-status-result'); return target;
    }},
    principal:{role:'applicant'},selectedApplication:initial,
    deliveryWatchEpoch:0,deliveryTimer:null,clearTimeout:()=>{},
    setTimeout: fn => {callbacks.push(fn);return callbacks.length;},
    render:()=>{fullRenders++;lookup.focused=false;},deliverPdf:async()=>{},
    api:async()=>phase === 0 ? {...initial} : {...initial,state:'MANUAL_IN_REVIEW',updated:'new'},
  });
  vm.runInContext('serviceStatus = {id:"APP-TEST",application:selectedApplication}',ctx);
  vm.runInContext(workflow.slice(workflow.indexOf('async function observeDelivery('),workflow.indexOf('document.addEventListener("click"')),ctx);
  await ctx.observeDelivery(initial);
  await callbacks[0]();
  assert.equal(target.innerHTML,'');
  phase = 1;
  await callbacks[1]();
  assert.match(target.innerHTML,/Perbarui status/);
  assert.equal(fullRenders,0);
  assert.deepEqual(lookup,{value:'APP-TYPING',focused:true});
});

test('an expired lookup failure cannot replace the next request or navigate back', async () => {
  let fail;
  const {ctx} = context({api:()=>new Promise((_resolve,reject)=>{fail=reject;})});
  const pending=ctx.loadServiceStatus('APP-OLD');
  ctx.navigationRevision++;
  fail(new Error('Old request failed'));
  assert.equal(await pending,false);
  assert.equal(read(ctx,'serviceStatus'),null);
});

test('recheck submits only the current revision, prevents duplicate clicks and observes ready PDF', async () => {
  const requests=[],observed=[];let answer, click;
  const old={id:'APP-TEST',state:'MANUAL_SCHEDULED'};
  const ctx=vm.createContext({document:{addEventListener:(name,handler)=>{if(name==='click')click=handler;}},
    authEpoch:0,navigationRevision:0,selectedApplication:old,serviceStatus:{application:old},flow:{result:{application:old}},
    stopDeliveryWatch:()=>{},render:()=>{},observeDelivery:async app=>observed.push(app.state),
    api:(path,options)=>{requests.push([path,JSON.parse(options.body)]);return new Promise(resolve=>answer=resolve);},errorMessage:assert.fail});
  vm.runInContext(workflow.slice(workflow.indexOf('document.addEventListener("click"'),workflow.indexOf('document.addEventListener("submit"')),ctx);
  const button={disabled:false,isConnected:true,dataset:{demoRecheck:'APP-TEST',revision:'3'},hasAttribute:()=>false};
  const event={target:{closest:()=>button}};
  const pending=click(event);await click(event);
  assert.equal(requests.length,1);
  assert.deepEqual(requests,[['/applications/APP-TEST/demo/recheck',{capture_revision:3}]]);
  answer({id:'APP-TEST',state:'SLIK_READY'});await pending;
  assert.deepEqual(observed,['SLIK_READY']);
  assert.equal(ctx.flow.result.application.state,'SLIK_READY');
  assert.equal(button.disabled,false);
});

test('late recheck cannot redraw another page or start an old PDF download',async()=>{
  let answer,click,rendered=0,observed=0;
  const ctx=vm.createContext({document:{addEventListener:(name,handler)=>{if(name==='click')click=handler;}},
    authEpoch:0,navigationRevision:0,selectedApplication:{id:'APP-TEST'},serviceStatus:null,flow:null,
    stopDeliveryWatch:()=>{},render:()=>{rendered++;},observeDelivery:async()=>{observed++;},
    api:()=>new Promise(resolve=>answer=resolve),errorMessage:assert.fail});
  vm.runInContext(workflow.slice(workflow.indexOf('document.addEventListener("click"'),workflow.indexOf('document.addEventListener("submit"')),ctx);
  const button={disabled:false,isConnected:true,dataset:{demoRecheck:'APP-TEST',revision:'3'},hasAttribute:()=>false};
  const pending=click({target:{closest:()=>button}});
  ctx.navigationRevision++;
  answer({id:'APP-TEST',state:'SLIK_READY'});await pending;
  assert.equal(rendered,0);assert.equal(observed,0);
});
