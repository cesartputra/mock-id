import vm from 'node:vm';
import fs from 'node:fs';
import assert from 'node:assert/strict';
import { webcrypto } from 'node:crypto';
const nodes=new Map();
const nodeFor=s=>{if(!nodes.has(s))nodes.set(s,{innerHTML:'',textContent:'',classList:{add(){},remove(){},toggle(){}},setAttribute(){},removeAttribute(){},addEventListener(){},open:false,showModal(){this.open=true},close(){this.open=false}});return nodes.get(s)};
const timers=new Map();let n=0;
const context=vm.createContext({document:{querySelector:nodeFor,querySelectorAll(){return []},addEventListener(){}},window:{scrollTo(){},addEventListener(){}},localStorage:{getItem(){return null},setItem(){}},location:{hash:''},crypto:webcrypto,setTimeout(fn){timers.set(++n,fn);return n},clearTimeout(id){timers.delete(id)},Intl,Date,console});
vm.runInContext(fs.readFileSync(new URL('../public/app.js', import.meta.url),'utf8'),context);
const run=source=>vm.runInContext(source,context);
function flush(){while(timers.size){const [id,fn]=timers.entries().next().value;timers.delete(id);fn()}}
for(const expected of ['pass','capture','technical','manual','attack']){
 run(`newSession(); session.document=true; session.consent=true; session.challenge=3; session.kycReady=true; session.step=3; session.scenario='${expected}'; startProcess();`);
 flush();
 assert.equal(run('session.result.status'),expected);
 assert.equal(run('session.step'),4);
 assert.ok(run('session.result.rules.face===85'));
}
run("newSession();session.challenge=3;session.kycReady=false;startProcess();");assert.equal(run('running'),false,'KYC wajib sebelum processing');
run("session.kycReady=true;session.started=Date.now()-16*60*1000;startProcess();");assert.equal(run('running'),false,'Sesi kedaluwarsa ditolak');
run("newSession();session.challenge=3;session.kycReady=true;startProcess();startProcess();");flush();assert.equal(run('db.records.filter(r=>r.session===session.id).length'),1,'Nonce tidak boleh menghasilkan dua hasil');
for(const status of ['manual','scheduled','approved','rejected']){run(`session.result.status='${status}';navigate('verify');`);assert.ok(nodes.get('#app').innerHTML.includes('step-content'));}
run("newSession();session.challenge=3;session.kycReady=true;session.scenario='technical';startProcess();");flush();
const oldNonce=run('session.nonce');run('retry()');assert.equal(run('session.attempt'),2);assert.notEqual(run('session.nonce'),oldNonce);assert.equal(run('session.nonceUsed'),false);
run('session.attempt=db.settings.attempts;');const attempt=run('session.attempt');run('retry()');assert.equal(run('session.attempt'),attempt,'Batas percobaan ditegakkan');
run("newSession();session.challenge=3;session.kycReady=true;startProcess();");flush();run('db.settings.face=99;');assert.equal(run("resultControls(session.result).match(/Pencocokan wajah 1:1[\\s\\S]*?badge (\\w+)/)[1]"),"green");assert.equal(run('session.result.rules.face'),85,'Aturan historis tidak berubah');
assert.equal(run("escapeHTML('<script>')"),'&lt;script&gt;');assert.ok(run("csvCell('=SUM(A1)').startsWith(\"\\\"'\")"));
console.log('PASS: 5 keputusan, KYC wajib, kedaluwarsa, nonce, retry, 4 status manual, ambang historis, escaping HTML/CSV.');
