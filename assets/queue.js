'use strict';
let queueActive=false, queueSignature='', noteContext=null, queueAutoAt=0;
const queueLabels={up_next:'Up next',reviewing:'Reviewing',waiting:'Waiting',done:'Done for now',removed:'Removed'};
const queueBusy=new Set();

function queueButton(pr,action,label,primary=false){
 return `<button type="button" class="button ${primary?'primary':''}" data-queue-action="${action}" data-url="${esc(pr.url)}" ${queueBusy.has(pr.url)?'disabled':''}>${label}</button>`;
}
function queueCard(pr){
 const w=pr.workflow, reasons=w.reasons||[], history=w.bucket==='history',run=pr.run;
 let primary='',secondary='';
 if(history){if(!w.closed)primary=queueButton(pr,'restore','Restore to Up next',true);}
 else {
  primary=w.stage==='up_next'?queueButton(pr,'start','Start reviewing',true):w.stage==='reviewing'?queueButton(pr,'wait','Waiting for author',true):queueButton(pr,'start','Resume reviewing',true);
  if(w.stage==='up_next')secondary+=queueButton(pr,'move_up','Move up');
  if(reasons.length)secondary+=queueButton(pr,'acknowledge','Mark updates checked');
  secondary+=queueButton(pr,'done','Done for now');
 }
 secondary+=queueButton(pr,'note',w.note?'Edit note':'Add note');
 const menu='<p class="detail-heading">Organize review</p>'+secondary+'<p class="detail-heading">AI tools</p>'+aiReviewActions(pr)+(!history?'<p class="detail-heading">Tracking</p>'+queueButton(pr,'remove','Remove from My reviews'):'');
 const reviewed=w.review_observation?.head_sha;
 const stateLabel=w.closed?(pr.pr_state==='merged'?'Merged':'Closed'):queueLabels[w.stage];
 return `<article class="pr-card queue-card" data-queue-pr="${esc(pr.url)}">
  <div class="pr-main"><div>${prIdentity(pr)}<a class="pr-title" target="_blank" rel="noopener" href="${esc(safeUrl(pr.url))}">${esc(pr.title)}</a><div class="pr-byline">${authorBadge(pr)}</div><div class="pr-meta">${prAge(pr)}<span>${esc(stateLabel)}</span>${pr.is_draft?'<span class="chip">Draft</span>':''}${triageBadge(pr)}</div></div><div class="pr-actions">${primary}${artifactLink(notesArtifact(pr.artifacts),'Open AI notes',pr)}${actionDisclosure(pr,'•••',menu)}</div></div>
  ${reasons.length?`<div class="queue-reasons">${reasons.map(reason=>`<a target="_blank" rel="noopener" class="chip warn" href="${esc(safeUrl(reason.url))}">${esc(reason.label)} ↗</a>`).join('')}</div>`:''}
  ${w.error?`<p class="queue-sync-error">${esc(w.error)}</p>`:''}
  ${artifactWarning(pr)}${triageCard(pr)}
  ${w.note?`<p class="queue-note">${esc(w.note)}</p>`:''}
  <details class="queue-tools"><summary>Review details${run?' · AI '+esc(statusLabels[run.status]||run.status):''}</summary>
   <p class="muted">${w.checked_at?'GitHub checked '+esc(since(w.checked_at)):'Awaiting first GitHub check'}</p>
   ${reviewed&&w.stage==='reviewing'?`<p class="muted">Review started at commit <code>${esc(reviewed.slice(0,12))}</code>${pr.head_sha&&pr.head_sha!==reviewed?' · newer head available':''}</p>`:''}
   ${run?`<p class="muted">AI activity recorded ${esc(since(run.updated_at))}${run.message?' · '+esc(run.message):''}</p>`:''}
   ${attention(run)||['starting','queued'].includes(run?.status)?`<button class="button" data-action="/regenerate-review" data-url="${esc(pr.url)}" data-retry="true">Retry after closing the previous terminal</button>`:''}
   ${pr.history?.length?renderHistory(pr):''}
  </details>
 </article>`;
}
function renderQueue(force=false){
 if(!state)return;
 const prs=state.prs.filter(pr=>pr.workflow);
 const count=prs.filter(pr=>pr.workflow.bucket!=='history').length;
 $('my-reviews-tab').querySelector('.count').textContent=count;
 const refresh=state.queue_refresh||{};
 $('queue-recover').disabled=refresh.status==='running';
 $('queue-error').hidden=refresh.status!=='failed';$('queue-error').textContent=refresh.message||'';
 const signature=JSON.stringify([prs,state.queue_candidates,[...queueBusy],Math.floor(Date.now()/60000)]);
 if(!force&&signature===queueSignature)return;queueSignature=signature;
 const restoreFocus=rememberCardFocus($('queue-view'));
 const open=new Map([...$('queue-view').querySelectorAll('.queue-card')].map(el=>[el.dataset.queuePr,[...el.querySelectorAll('details[open]')].map(d=>d.className)]));
 const focused=document.activeElement;const focusUrl=focused?.dataset?.url, focusAction=focused?.dataset?.queueAction;
 const compare=(a,b)=>a.workflow.position-b.workflow.position||a.url.localeCompare(b.url);
 const sections=[['attention','Needs another look','Updates and replies since your last check.'],['up_next','Up next','PRs you chose to review next.'],['reviewing','Reviewing','Reviews you have started.'],['waiting','Waiting','Kept here until something needs another look.']];
 $('queue-list').innerHTML=sections.map(([key,title,description])=>{
  const group=prs.filter(pr=>pr.workflow.bucket===key).sort(compare);
  if(!group.length)return `<details class="queue-section queue-empty-group"><summary>${title} <span class="count">0</span></summary><p class="muted">Nothing here right now.</p></details>`;
  return `<section class="queue-section" aria-label="${title}"><div class="list-heading"><div><h3>${title} <span class="count">${group.length}</span></h3></div></div>${group.map(queueCard).join('')||'<p class="queue-empty muted">Nothing here right now.</p>'}</section>`;
 }).join('');
 const history=prs.filter(pr=>pr.workflow.bucket==='history').sort(compare);
 $('queue-history-count').textContent='('+history.length+')';$('queue-history-list').innerHTML=history.map(queueCard).join('')||'<p class="muted">Completed and removed reviews will appear here.</p>';
 $('queue-candidates').innerHTML=(state.queue_candidates||[]).map(pr=>`<div class="queue-candidate"><div><a target="_blank" rel="noopener" href="${esc(safeUrl(pr.url))}">${esc(pr.title)}</a><p class="muted">${esc(pr.owner+'/'+pr.repository)} #${esc(pr.number)}</p></div>${queueButton(pr,'recover','Follow this review')}</div>`).join('')||'<p class="muted">No unsaved reviews found in the local history. Search GitHub for earlier participation.</p>';
 for(const el of $('queue-view').querySelectorAll('.queue-card'))for(const d of el.querySelectorAll('details'))if(open.get(el.dataset.queuePr)?.includes(d.className))d.open=true;
 restoreFocus();
 if(focusUrl&&focusAction){const replacement=[...$('queue-view').querySelectorAll('[data-queue-action]')].find(b=>b.dataset.url===focusUrl&&b.dataset.queueAction===focusAction);replacement?.focus({preventScroll:true});}
}
function showQueue(value){
 queueActive=value;$('queue-view').hidden=!value;$('my-reviews-tab').setAttribute('aria-pressed',value);
 if(value){showReporting(false);$('inbox-content').hidden=true;document.querySelectorAll('[data-view]').forEach(b=>b.setAttribute('aria-pressed','false'));$('reporting-tab').setAttribute('aria-pressed','false');document.querySelector('.skip').textContent='Skip to my reviews';document.querySelector('.skip').href='#queue-view';renderQueue();}
 else $('inbox-content').hidden=reportingActive;
 renderWorkspaceNavigation();
 try{localStorage.setItem('pr-personal-view',value?'queue':'inbox');}catch{}
}
function findQueuePr(url){return state?.prs.find(pr=>pr.url===url);}
async function queueAction(url,action,extras={}){
 const pr=findQueuePr(url), w=pr?.workflow;
 const request={url,action,revision:w?.revision,observed:w?.observed,...extras};
 queueBusy.add(url);renderQueue();
 try {
  const result=await post('/queue',request);
  const undo=result.undo_token&&['done','remove'].includes(action)?async()=>{await post('/queue',{url,action:'undo',revision:result.revision,token:result.undo_token});await loadState();}:null;
  const messages={enqueue:'Saved in My reviews.',start:'Review started. Opening the PR does not clear pending updates.',wait:'Waiting for the author. Any newer updates remain visible.',acknowledge:'The displayed updates were marked checked.',done:'Review marked done for now.',remove:'Removed from My reviews. The PR and its review artifacts are unchanged.',restore:'Restored to Up next.',move_up:'Queue order updated.',note:'Private note saved.'};
  notify(result.existing?'This PR is already in My reviews.':messages[action]||'Saved.',undo);
  await loadState();return result;
 } finally {queueBusy.delete(url);renderQueue(true);}
}
document.addEventListener('click',async event=>{
 const button=event.target.closest('[data-queue-action]');if(!button||button.disabled)return;
 const {url,queueAction:action}=button.dataset;
 if(action==='show'){showQueue(true);const w=findQueuePr(url)?.workflow;if(w?.bucket==='history')$('queue-history').open=true;[...$('queue-view').querySelectorAll('[data-queue-pr]')].find(el=>el.dataset.queuePr===url)?.scrollIntoView({block:'center',behavior:'smooth'});return;}
 if(action==='note'){
  const pr=findQueuePr(url);noteContext={url,revision:pr.workflow.revision};$('queue-note-title').textContent=pr.title;$('queue-note').value=pr.workflow.note||'';$('queue-note-error').hidden=true;$('queue-note-dialog').showModal();$('queue-note').focus();return;
 }
 try{await queueAction(url,action==='recover'?'enqueue':action,action==='recover'?{recover:true}:{});}catch(error){notify(error.message);}
});
$('my-reviews-tab').addEventListener('click',()=>showQueue(true));
$('reporting-tab').addEventListener('click',()=>showQueue(false));
$('queue-add').addEventListener('submit',async event=>{
 event.preventDefault();const input=event.target.elements.url;const button=event.target.querySelector('button');button.disabled=true;
 try{await queueAction(input.value.trim(),'enqueue');input.value='';$('queue-add-dialog').close();}catch(error){notify(error.message);}finally{button.disabled=false;}
});
$('queue-note-cancel').addEventListener('click',()=>$('queue-note-dialog').close());
$('queue-note-form').addEventListener('submit',async event=>{
 event.preventDefault();const button=event.target.querySelector('button[type=submit]');button.disabled=true;
 try{await queueAction(noteContext.url,'note',{revision:noteContext.revision,note:$('queue-note').value});$('queue-note-dialog').close();}
 catch(error){$('queue-note-error').hidden=false;$('queue-note-error').textContent=error.message;}
 finally{button.disabled=false;}
});
async function refreshQueue(force=false,recovery=false){
 try{await post(recovery?'/recover-reviews':'/refresh-queue',{force});queueAutoAt=Date.now();await loadState();}catch(error){notify(error.message);}
}
$('queue-recover').addEventListener('click',()=>refreshQueue(true,true));
function queueAutoRefresh(){
 if(document.hidden||!state)return;
 const tracked=state.prs.filter(pr=>pr.workflow&&pr.workflow.stage!=='removed'&&!pr.workflow.closed);
 const unchecked=tracked.some(pr=>!pr.workflow.checked_at&&!pr.workflow.attempted_at);
 if(tracked.length&&Date.now()-queueAutoAt>=(unchecked?30000:300000))refreshQueue(unchecked);
}
document.addEventListener('visibilitychange',queueAutoRefresh);
window.addEventListener('focus',queueAutoRefresh);
setInterval(queueAutoRefresh,30000);
setTimeout(queueAutoRefresh,1500);
try{if(localStorage.getItem('pr-personal-view')==='queue')showQueue(true);}catch{}
