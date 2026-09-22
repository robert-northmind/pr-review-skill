// Exercise the combined sync contract without launching a browser or contacting GitHub.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(path.join(__dirname,'../../assets/dashboard.js'),'utf8');
const elements=new Map();
const $=id=>{if(!elements.has(id))elements.set(id,{disabled:false,hidden:false,textContent:'',innerHTML:'',classList:{toggle(){}},querySelector(){return this.label||(this.label={textContent:''});}});return elements.get(id);};
const context=vm.createContext({$,state:{prs:[],triage:{config:{enabled:false}},refresh:{status:'completed'},last_github_refresh_at:'2026-09-16T10:00:00Z',queue_refresh:{status:'completed',finished_at:'2026-09-16T10:00:00Z'}},reportingData:{refresh:{status:'completed'},updated_at:'2026-09-16T10:00:00Z'},reportLoadError:'',syncStarting:false,syncRequestErrors:{},esc:s=>String(s??'').replaceAll('<','&lt;'),since:s=>s,post:async()=>{},loadState:async()=>{},loadReporting:async()=>{}});
vm.runInContext(source.slice(source.indexOf('function renderSyncStatus(){'),source.indexOf("$('inbox-tab').addEventListener")),context);
(async()=>{
 context.renderSyncStatus();assert.match($('freshness').textContent,/^Synced /);assert.equal($('warnings').hidden,true);
 context.reportingData.refresh={status:'failed',message:'Report failed <script>'};context.renderSyncStatus();assert.match($('sync-sources').innerHTML,/Report failed &lt;script>/);assert.match($('freshness').textContent,/attention/);assert.equal($('refresh').disabled,false);
 context.reportLoadError='Cached report unavailable';context.reportingData.refresh={status:'completed'};context.renderSyncStatus();assert.match($('sync-sources').innerHTML,/Cached report unavailable/);context.reportLoadError='';
 context.state.queue_refresh={status:'running'};context.renderSyncStatus();assert.equal($('refresh').disabled,true);
 const calls=[];context.post=async endpoint=>calls.push(endpoint);await context.syncGitHub();assert.deepEqual(calls,[]);
 context.state.queue_refresh={status:'failed',finished_at:'2026-09-16T12:00:00Z',message:'Queue failed'};context.renderSyncStatus();assert.match($('sync-sources').innerHTML,/Saved reviews and replies<\/dt><dd>Not synced yet/);
 let release;context.post=endpoint=>{calls.push(endpoint);return endpoint==='/refresh'?new Promise(resolve=>{release=resolve;}):Promise.reject(new Error('Reporting request refused'));};
 const pending=context.syncGitHub();await context.syncGitHub();assert.deepEqual(calls,['/refresh','/refresh-reporting']);assert.equal($('refresh').disabled,true);release({started:true});await pending;
 assert.equal($('refresh').disabled,false);assert.match($('sync-sources').innerHTML,/Reporting request refused/);
 context.state.queue_refresh={status:'completed',finished_at:'2026-09-16T12:00:00Z'};context.post=async endpoint=>calls.push(endpoint);await context.syncGitHub();assert.equal($('warnings').hidden,true);assert.equal(calls.length,4);
 console.log('Workspace sync checks passed: fan-out, duplicate prevention, partial failures, retry, source freshness and escaping.');
})().catch(error=>{console.error(error);process.exitCode=1;});
