const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const source = fs.readFileSync('app/view/static/operator.js', 'utf8');
const esc = x => String(x ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function setup(overrides={}) {
  const listeners = {}, classes = {}, nav = {hidden:true,innerHTML:''}, label = {};
  let renders=0, closes=0;
  const ctx = vm.createContext({
    Date, esc, icon: x => `<svg>${x}</svg>`, date: x => 'TIME '+x,
    document: {body:{classList:{toggle:(key,v)=>{classes[key]=v;}}},addEventListener:(key,cb)=>{listeners[key]=cb;}},
    $: key => key==='#operator-nav'?nav:key==='#operator-account-label'?label:{close:()=>{closes++;}},
    principal:{role:'admin',login:'demo-admin'}, page:'queue', authEpoch:0,navigationRevision:0,
    applicationRows:[],selectedApplication:null,capacityCalendar:null,operatorMetrics:{volume:{}},
    workspace:{health:{ready:true}},flow:null,stateLabels:{SLIK_READY:'PDF tersedia'},
    registrationHeader:(n,title,text)=>`<h1>${title}</h1><p>${text}</p>`,padRuntimeLabel:()=> 'CPU',
    applicationPanel:()=> '',capacitySummary:()=> '',
    modal:()=>{},errorMessage:()=>{},render:()=>{renders++;},toast:()=>{},reloadWorkspace:async()=>{},stopCamera:()=>{},releasePreviews:()=>{},
    ...overrides,
  });
  vm.runInContext(source,ctx);
  return {ctx,listeners,classes,nav,label,renders:()=>renders,closes:()=>closes};
}
const app={id:'APP-TEST',name:'<script>name</script>',state:'SLIK_READY',updated:'now',capture_revision:2,routing:{routing_score:76.98388},evidence:[
  {id:'EVD-FULL',kind:'document',revision:2,created:'then',expires:Date.now()/1000+3600},
  {id:'EVD-CROP',kind:'document-crop',revision:2,created:'then',expires:Date.now()/1000+3600},
  {id:'EVD-SELFIE',kind:'selfie',revision:2,created:'then',expires:Date.now()/1000+3600},
]};
test('operator navigation follows applicant shell and respects staff roles',()=>{
  const {ctx,nav,label,classes}=setup();
  ctx.updateOperatorNav();
  assert.equal(classes['operator-mode'],true);assert.equal(nav.hidden,false);
  assert.match(nav.innerHTML,/Ringkasan|Data pemohon|Jejak aktivitas/);
  assert.equal(label.textContent,'demo-admin · admin');
  ctx.principal={role:'helpdesk',login:'desk'};ctx.updateOperatorNav();
  assert.match(nav.innerHTML,/Kasus helpdesk/);assert.doesNotMatch(nav.innerHTML,/Ringkasan|Modul/);
  ctx.page='home';ctx.updateOperatorNav();assert.equal(nav.hidden,true);
});
test('admin can clean passed requests and helpdesk cannot see deletion actions',()=>{
  const {ctx}=setup();
  assert.match(ctx.operatorTable([app]),/data-cleanup="APP-TEST"/);
  assert.match(ctx.operatorTable([app]),/76.98\/100/);
  assert.doesNotMatch(ctx.operatorTable([app]),/<script>/);
  ctx.principal.role='helpdesk';assert.doesNotMatch(ctx.operatorTable([app]),/data-cleanup/);
});
test('gallery keeps original and card crop separately, with safe enlarged photo actions',()=>{
  const {ctx}=setup();const html=ctx.operatorEvidenceView(app);
  assert.match(html,/Foto KTP asli/);assert.match(html,/Crop KTP · hanya area kartu/);
  assert.match(html,/\/api\/evidence\/EVD-FULL/);assert.match(html,/\/api\/evidence\/EVD-CROP/);
  assert.match(html,/data-photo="EVD-CROP"/);assert.doesNotMatch(html,/data-generate-crop/);
});
test('deleted gallery never requests removed images and old evidence can request a local crop',()=>{
  const {ctx}=setup();
  const deleted={...app,evidence:app.evidence.map(e=>({...e,deleted_at:'now'})),photo_cleanup:{at:'now'}};
  const html=ctx.operatorEvidenceView(deleted);
  assert.match(html,/Foto telah dihapus/);assert.doesNotMatch(html,/<img|data-generate-crop/);
  assert.match(ctx.operatorEvidenceView({...app,evidence:[app.evidence[0]]}),/data-generate-crop="APP-TEST"/);
});
test('cleanup confirmation lists only selected request and defaults to photos',()=>{
  const {ctx}=setup();const html=ctx.cleanupDialog({application_id:'APP-TEST',name:'<script>x</script>',capture_revision:2,photos:7,results:2,registrations:1,reports:1});
  assert.match(html,/value="photos" checked required/);assert.match(html,/value="full"/);
  assert.match(html,/satu permohonan yang dipilih/);assert.match(html,/checkbox" name="confirmed" required/);
  assert.doesNotMatch(html,/<script>/);
});
test('cleanup posts server plan version and refreshes remaining identity without auto PDF download',async()=>{
  const calls=[];
  const {ctx,renders,closes}=setup({selectedApplication:app,api:async(path,options)=>{
    calls.push({path,options});return options?{deleted_photos:3,application_deleted:false}:{...app,photo_cleanup:{at:'now'}};
  }});
  await ctx.applyCleanup({application_id:app.id,capture_revision:2,updated_at:'server-version'},'photos');
  assert.deepEqual(JSON.parse(calls[0].options.body),{mode:'photos',capture_revision:2,expected_updated_at:'server-version',confirm_application_id:'APP-TEST'});
  assert.equal(ctx.selectedApplication.photo_cleanup.at,'now');assert.equal(renders(),1);assert.equal(closes(),1);
  assert.doesNotMatch(calls.map(x=>x.path).join(' '),/slik/);
});
test('late destructive response cannot change a new page or actor',async()=>{
  let resolve;const {ctx,renders,closes}=setup({selectedApplication:app,api:()=>new Promise(r=>{resolve=r;})});
  const promise=ctx.applyCleanup({application_id:app.id,capture_revision:2,updated_at:'server-version'},'full');
  ctx.authEpoch++;ctx.navigationRevision++;resolve({application_deleted:true,deleted_photos:3});await promise;
  assert.equal(ctx.selectedApplication.id,'APP-TEST');assert.equal(renders(),0);assert.equal(closes(),0);
});
test('full cleanup preserves a different request already selected on the same page',async()=>{
  const other={id:'APP-OTHER'};const {ctx}=setup({selectedApplication:other,api:async()=>({application_deleted:true,deleted_photos:3})});
  await ctx.applyCleanup({application_id:app.id,capture_revision:2,updated_at:'server-version'},'full');
  assert.equal(ctx.selectedApplication.id,'APP-OTHER');
});
test('old crop response cannot replace newly selected evidence',async()=>{
  let resolve;const {ctx,listeners,renders}=setup({selectedApplication:app,api:()=>new Promise(r=>{resolve=r;})});
  const button={dataset:{generateCrop:'APP-TEST'},disabled:false,isConnected:true};
  const promise=listeners.click({target:{closest:()=>button}});ctx.selectedApplication={id:'APP-NEW'};resolve(app);await promise;
  assert.equal(ctx.selectedApplication.id,'APP-NEW');assert.equal(renders(),0);
});
