'use strict';
let queueActive=false, queueSignature='', noteContext=null, queueAutoAt=0, queueQuery='', queueSeen=null;
const queueLabels={reviewing:'In progress',attention:'Back to you',up_next:'Up next',waiting:'Waiting for author',history:'Merged or closed',removed:'Stopped tracking'};
const queueHints={reviewing:'What you are working on',attention:'Waiting PRs with new commits, replies, review requests or a due reminder',up_next:'In your order',waiting:'Comes back to you on new commits or replies, or when a reminder is due',history:'Kept 20 days after closing',removed:'Kept until the PR closes. Track again at any time.'};
const queueEmpty={reviewing:'Nothing in progress. Start the top PR in Up next.',attention:'Nothing came back. Updates on waiting PRs land here.',up_next:'Add a PR here, or use Add to Up next in the Inbox.',waiting:'Nothing is waiting for an author.',history:'Tracked PRs appear here when GitHub confirms they are merged or closed.',removed:'PRs you stop tracking stay here so you can bring them back.'};
const queueMoved={added:'You added it',recovered:'Restored from your GitHub activity',discovered:'Added from GitHub because you commented or reviewed',started:'You started reviewing',resumed:'You continued the review',paused:'You paused it',handed_back:'You handed it back to the author',github_review:'You submitted a review on GitHub',kept_waiting:'You marked the updates as seen',removed:'You stopped tracking it',restored:'You tracked it again'};
const queueReasonIcons={head:'↻',reply:'💬',author:'💬',mention:'@',requested:'⟳',reminder:'⏰'};
const queueBusy=new Set(), queueLocal=new Set();
const queueSectionOpen={reviewing:true,attention:true,up_next:true,waiting:false,history:false,removed:false};
for(const key of Object.keys(queueSectionOpen)){
 try{const saved=localStorage.getItem(`pr-queue-${key}-open`);if(saved!==null)queueSectionOpen[key]=saved==='true';}catch{}
}
function queueRememberSection(key,open){
 queueSectionOpen[key]=open;
 try{localStorage.setItem(`pr-queue-${key}-open`,String(open));}catch{}
}
document.addEventListener('toggle',event=>{
 const key=event.target.dataset?.queueSection;
 if(!Object.hasOwn(queueSectionOpen,key)||!event.target.isConnected)return;
 queueRememberSection(key,event.target.open);
},true);

function queueSectionOf(pr){return pr.workflow.closed?'history':pr.workflow.bucket;}
function queueButton(pr,action,label,primary=false,extra=''){
 return `<button type="button" class="button ${primary?'primary':''}" data-queue-action="${action}" data-url="${esc(pr.url)}" ${extra} ${queueBusy.has(pr.url)?'disabled':''}>${label}</button>`;
}
function queueWhy(pr){
 const w=pr.workflow;
 if(w.closed){const at=pr.pr_state==='merged'?pr.merged_at:pr.closed_at;return (pr.pr_state==='merged'?'Merged':'Closed')+(at?' '+since(at):'');}
 return w.moved&&queueMoved[w.moved.kind]?queueMoved[w.moved.kind]+' '+since(w.moved.at):'';
}
function queueWhyLine(pr){const text=queueWhy(pr);return text?`<p class="queue-why"><span aria-hidden="true">↳ </span>${esc(text)}</p>`:'';}
function queueReasons(reasons,lead=''){
 if(!reasons.length)return '';
 return `<div class="queue-reasons">${lead?`<span class="queue-reasons-lead">${esc(lead)}</span>`:''}${reasons.map(reason=>`<a target="_blank" rel="noopener" href="${esc(safeUrl(reason.url))}"><span aria-hidden="true">${queueReasonIcons[reason.kind]||'•'}</span> ${esc(reason.label)} ↗</a>`).join('')}</div>`;
}
function queueMenu(pr){
 const w=pr.workflow, organize=[];
 if(w.bucket==='up_next')organize.push(queueButton(pr,'wait','Mark as waiting for author'));
 organize.push(queueButton(pr,'note',w.note?'Edit note':'Add note'));
 const tracking=w.bucket==='removed'||w.closed?'':'<p class="detail-heading">Tracking</p>'+queueButton(pr,'remove','Stop tracking');
 return actionDisclosure(pr,'•••','<p class="detail-heading">Organize</p>'+organize.join('')+'<p class="detail-heading">AI tools</p>'+aiReviewActions(pr)+tracking);
}
function queueRemind(pr){
 const w=pr.workflow, set=!!w.remind_at;
 const options=[[1,'1 day'],[3,'3 days'],[7,'1 week']].map(([days,label])=>queueButton(pr,'remind',label,false,`data-days="${days}"`)).join('')+(set?queueButton(pr,'remind','Clear reminder',false,'data-days="0"'):'');
 return `<details class="snooze-picker queue-remind"><summary class="button" aria-label="${set?'Change reminder':'Set a reminder'} for PR ${esc(pr.number)}">${set?'⏰ '+esc(when(w.remind_at)):'Remind me'}</summary><div class="snooze-options"><p class="muted">Back to you in</p>${options}</div></details>`;
}
function queueDetails(pr,withRun){
 const w=pr.workflow, run=pr.run, reviewed=w.review_observation?.head_sha;
 return `<details class="queue-tools"><summary>Details${run?' · AI '+esc(statusLabels[run.status]||run.status):''}</summary>
  ${triageCard(pr)}${withRun?reviewSummary(run):''}
  <p class="muted">${w.checked_at?'GitHub checked '+esc(since(w.checked_at)):'Awaiting first GitHub check'}</p>
  ${reviewed&&w.stage==='reviewing'?`<p class="muted">Review started at commit <code>${esc(reviewed.slice(0,12))}</code>${pr.head_sha&&pr.head_sha!==reviewed?' · newer head available':''}</p>`:''}
  ${run?`<p class="muted">AI activity recorded ${esc(since(run.updated_at))}${run.message?' · '+esc(run.message):''}</p>`:''}
  ${run?.transport!=='in-app'&&(attention(run)||['starting','queued'].includes(run?.status))?`<button class="button" data-action="/regenerate-review" data-url="${esc(pr.url)}" data-retry="true">Retry after closing the previous terminal</button>`:''}
  ${pr.history?.length?renderHistory(pr):''}
 </details>`;
}
function queueTitle(pr){return `<a class="pr-title" target="_blank" rel="noopener" href="${esc(safeUrl(pr.url))}">${esc(pr.title)}</a>`;}
// In progress and Back to you get full cards: they are the PRs that need you now.
function queueCard(pr){
 const w=pr.workflow, back=w.bucket==='attention', reasons=w.reasons||[];
 const actions=back?queueButton(pr,'acknowledge','Keep waiting')+codeWorkspaceLink(pr)+queueButton(pr,'start','Continue review',true)
  :(reasons.length?queueButton(pr,'acknowledge','Mark updates seen'):'')+queueButton(pr,'stop','Pause')+codeWorkspaceLink(pr)+queueButton(pr,'wait','Hand back to author',true);
 return `<article class="pr-card queue-card queue-${back?'back':'now'}" data-queue-pr="${esc(pr.url)}" data-queue-history="false">
  ${back?queueReasons(reasons):''}
  <div class="pr-main"><div>${prIdentity(pr)}${queueTitle(pr)}<div class="pr-byline">${authorBadge(pr)}</div><div class="pr-meta">${prAge(pr)}${pr.is_draft?'<span class="chip">Draft</span>':''}${triageBadge(pr)}${workspaceStatusBadge(pr)}</div></div><div class="pr-actions">${actions}${queueMenu(pr)}</div></div>
  ${back?'':queueReasons(reasons,'New since you started')}
  ${w.note?`<p class="queue-note">${esc(w.note)}</p>`:''}
  ${queueWhyLine(pr)}
  ${w.error?`<p class="queue-sync-error">${esc(w.error)}</p>`:''}
  ${artifactWarning(pr)}${reviewSummary(pr.run)}
  ${queueDetails(pr,false)}
 </article>`;
}
// Up next, waiting and finished PRs are compact rows; details stay one click away.
function queueRow(pr,index,key){
 const w=pr.workflow, historyView=key==='history';
 const rank=key==='up_next'?String(index+1):{waiting:'⏸',history:pr.pr_state==='merged'?'✓':'×',removed:'–'}[key];
 let actions='';
 if(key==='up_next')actions=(index>0?queueButton(pr,'move_up','↑',false,`title="Move up" aria-label="Move PR ${esc(pr.number)} up"`):'')+queueButton(pr,'start','Start review',index===0);
 if(key==='waiting')actions=queueRemind(pr)+queueButton(pr,'start','Review now');
 if(key==='removed')actions=queueButton(pr,'restore','Track again');
 return `<article class="pr-card queue-card queue-row" data-queue-pr="${esc(pr.url)}" data-queue-history="${historyView}">
  <span class="queue-rank${key==='up_next'&&index===0?' queue-rank-first':''}" aria-hidden="true">${rank}</span>
  <div class="queue-row-main">${queueTitle(pr)}
   <p class="queue-row-sub">${esc(pr.owner+'/'+pr.repository)} <a class="pr-number" href="${esc(safeUrl(pr.url))}" target="_blank" rel="noopener">#${esc(pr.number)}</a> · ${esc(pr.author_login?'@'+pr.author_login:'Unknown author')}${pr.is_draft?' · Draft':''}${key==='up_next'?' · '+triageBadge(pr):''}</p>
   ${w.note?`<p class="queue-note queue-row-note">${esc(w.note)}</p>`:''}
   ${key==='up_next'?queueReasons(w.reasons||[]):''}
   ${queueWhyLine(pr)}
   ${w.error?`<p class="queue-sync-error">${esc(w.error)}</p>`:''}
   ${queueDetails(pr,true)}
  </div>
  <div class="pr-actions">${actions}${codeWorkspaceLink(pr)}${queueMenu(pr)}</div>
 </article>`;
}
function queueSection(key,items){
 const body=!items.length?`<p class="muted queue-empty">${queueEmpty[key]}</p>`
  :['reviewing','attention'].includes(key)?items.map(queueCard).join('')
  :`<div class="queue-rows">${items.map((pr,index)=>queueRow(pr,index,key)).join('')}</div>`;
 return `<details id="queue-${key}" data-queue-section="${key}" class="queue-section queue-collapsible queue-lane-${key}" ${queueSectionOpen[key]?'open':''}><summary><span class="queue-section-title">${queueLabels[key]}</span> <span class="count${key==='attention'&&items.length?' queue-count-hot':''}">${items.length}</span> <span class="queue-hint">${queueHints[key]}</span></summary>${body}</details>`;
}
function queueSearchResults(prs){
 const words=queueQuery.toLowerCase().split(/\s+/).filter(Boolean);
 const hits=prs.filter(pr=>{const text=`${pr.title} ${pr.owner}/${pr.repository} #${pr.number} ${pr.author_login||''} ${pr.workflow.note||''}`.toLowerCase();return words.every(word=>text.includes(word));});
 return `<p class="muted queue-search-count">${hits.length} of ${prs.length} tracked PRs match.</p><div class="queue-rows">${hits.map(pr=>`<article class="pr-card queue-card queue-row" data-queue-pr="${esc(pr.url)}" data-queue-history="search">
  <span class="queue-rank" aria-hidden="true"></span><div class="queue-row-main">${queueTitle(pr)}<p class="queue-row-sub">${esc(pr.owner+'/'+pr.repository)} #${esc(pr.number)} · <span class="queue-section-pill">${queueLabels[queueSectionOf(pr)]}</span></p>${queueWhyLine(pr)}</div>
  <div class="pr-actions">${queueButton(pr,'show','Show')}</div></article>`).join('')||'<p class="muted queue-empty">No tracked PR matches.</p>'}</div>`;
}
function queueSorted(prs){
 const compare=(a,b)=>a.workflow.position-b.workflow.position||a.url.localeCompare(b.url);
 const groups={};
 for(const key of Object.keys(queueLabels))groups[key]=prs.filter(pr=>queueSectionOf(pr)===key).sort(compare);
 groups.history.sort((a,b)=>(Date.parse(b.pr_updated_at)||0)-(Date.parse(a.pr_updated_at)||0)||a.url.localeCompare(b.url));
 groups.removed.sort((a,b)=>(Date.parse(b.workflow.moved?.at)||0)-(Date.parse(a.workflow.moved?.at)||0)||a.url.localeCompare(b.url));
 return groups;
}
// Moves made by GitHub sync, reminders or another tab are announced, with a way to find the PR.
function queueAnnounceMoves(prs){
 const current=new Map(prs.map(pr=>[pr.url,queueSectionOf(pr)]));
 const previous=queueSeen;queueSeen=current;
 if(!previous)return;
 const moves=prs.filter(pr=>!queueLocal.has(pr.url)&&previous.get(pr.url)!==current.get(pr.url)&&current.get(pr.url)!=='removed');
 if(!moves.length)return;
 const describe=pr=>{
  const w=pr.workflow, key=current.get(pr.url);
  if(key==='attention')return `#${pr.number} is back to you: ${(w.reasons||[]).map(r=>r.label.toLowerCase()).join(', ')||'new activity'}.`;
  if(!previous.has(pr.url)&&w.moved?.kind==='discovered')return `Added #${pr.number} to Waiting for author because you commented or reviewed on GitHub.`;
  if(key==='waiting'&&w.moved?.kind==='github_review')return `#${pr.number} moved to Waiting for author because you submitted a review on GitHub.`;
  if(key==='history')return `#${pr.number} was ${pr.pr_state==='merged'?'merged':'closed'} and moved to Merged or closed.`;
  return `#${pr.number} moved to ${queueLabels[key]}.`;
 };
 const text=moves.length===1?describe(moves[0]):`${moves.length} PRs moved automatically: ${moves.map(pr=>`#${pr.number} → ${queueLabels[current.get(pr.url)]}`).join(', ')}.`;
 notify(text,null,()=>queueShow(moves[0].url));
}
function renderQueue(force=false){
 if(!state)return;
 const prs=state.prs.filter(pr=>pr.workflow);
 const groups=queueSorted(prs);
 const yours=groups.reviewing.length+groups.attention.length+groups.up_next.length;
 $('my-reviews-tab').querySelector('.count').textContent=yours+groups.waiting.length;
 const refresh=state.queue_refresh||{};
 $('queue-error').hidden=refresh.status!=='failed';$('queue-error').textContent=refresh.message||'';
 queueAnnounceMoves(prs);
 const signature=JSON.stringify([prs,[...queueBusy],queueQuery,Math.floor(Date.now()/60000)]);
 if(!force&&signature===queueSignature)return;queueSignature=signature;
 $('queue-summary').textContent=`${yours} on your turn · ${groups.waiting.length} waiting for authors`;
 const restoreFocus=rememberCardFocus($('queue-view'));
 let focusedSection=null;
 for(const section of $('queue-list').querySelectorAll('[data-queue-section]')){
  queueRememberSection(section.dataset.queueSection,section.open);
  if(section.querySelector('summary')===document.activeElement)focusedSection=section.id;
 }
 const open=new Map([...$('queue-view').querySelectorAll('.queue-card')].map(el=>[el.dataset.queuePr+el.dataset.queueHistory,[...el.querySelectorAll('details[open]')].map(d=>d.className)]));
 const focused=document.activeElement;const focusUrl=focused?.dataset?.url, focusAction=focused?.dataset?.queueAction, focusHistory=focused?.closest('.queue-card')?.dataset.queueHistory;
 $('queue-list').innerHTML=queueQuery.trim()?queueSearchResults(prs):
  [['Your turn',['reviewing','attention','up_next']],['Their turn',['waiting']],['Finished',['history','removed']]].map(([title,keys])=>
   `<section class="queue-turn" aria-label="${title}"><h3 class="queue-turn-title">${title}</h3>${keys.map(key=>queueSection(key,groups[key])).join('')}</section>`).join('');
 for(const el of $('queue-view').querySelectorAll('.queue-card'))for(const d of el.querySelectorAll('details'))if(open.get(el.dataset.queuePr+el.dataset.queueHistory)?.includes(d.className))d.open=true;
 restoreFocus();
 if(focusedSection)$(focusedSection)?.querySelector('summary').focus({preventScroll:true});
 if(focusUrl&&focusAction){const replacement=[...$('queue-view').querySelectorAll('[data-queue-action]')].find(b=>b.dataset.url===focusUrl&&b.dataset.queueAction===focusAction&&b.closest('.queue-card')?.dataset.queueHistory===focusHistory);replacement?.focus({preventScroll:true});}
}
function showQueue(value){
 queueActive=value;$('queue-view').hidden=!value;$('my-reviews-tab').setAttribute('aria-pressed',value);
 if(value){showReporting(false);$('inbox-content').hidden=true;document.querySelectorAll('[data-view]').forEach(b=>b.setAttribute('aria-pressed','false'));$('reporting-tab').setAttribute('aria-pressed','false');document.querySelector('.skip').textContent='Skip to my reviews';document.querySelector('.skip').href='#queue-view';renderQueue();}
 else $('inbox-content').hidden=reportingActive;
 renderWorkspaceNavigation();
 try{localStorage.setItem('pr-personal-view',value?'queue':'inbox');}catch{}
}
function findQueuePr(url){return state?.prs.find(pr=>pr.url===url);}
function queueShow(url){
 const pr=findQueuePr(url);if(!pr?.workflow)return;
 showQueue(true);
 if(queueQuery){queueQuery='';$('queue-search').value='';}
 const key=queueSectionOf(pr);
 // Rendering keeps each section's on-page state, so open the live section too.
 queueRememberSection(key,true);if($('queue-'+key))$('queue-'+key).open=true;
 renderQueue(true);
 const card=[...$('queue-list').querySelectorAll('[data-queue-pr]')].find(el=>el.dataset.queuePr===url);
 if(!card)return;
 card.scrollIntoView({block:'center',behavior:'smooth'});
 card.classList.add('queue-flash');setTimeout(()=>card.classList.remove('queue-flash'),2200);
}
function queueMessage(pr,action,extras){
 const w=pr?.workflow, id='#'+(pr?.number||''), key=pr?.workflow?queueSectionOf(pr):'';
 if(action==='wait')return key==='attention'?`${id} was handed back, but it is back to you: updates arrived during your review.`:`${id} is waiting for the author. New commits or replies bring it back.`;
 if(action==='acknowledge')return key==='waiting'?`${id} stays in Waiting for author. Only newer updates bring it back.`:`Updates on ${id} marked as seen.`;
 if(action==='remind')return extras.days?`${id} comes back to you ${when(w?.remind_at)} if nothing happens first.`:`Reminder for ${id} cleared.`;
 return {enqueue:`${id} saved in Up next.`,start:`${id} is in progress.`,stop:`${id} is paused at the top of Up next. Pending updates are kept.`,
  remove:`Stopped tracking ${id}. It stays under Finished.`,restore:`${id} is back in Up next.`,move_up:'Up next order updated.',note:'Private note saved.'}[action]||'Saved.';
}
async function queueTracked(url,work){
 queueLocal.add(url);
 try{return await work();}finally{queueLocal.delete(url);}
}
async function queueAction(url,action,extras={}){
 const pr=findQueuePr(url), w=pr?.workflow;
 const request={url,action,revision:w?.revision,observed:w?.observed,...extras};
 queueBusy.add(url);renderQueue();
 try {
  return await queueTracked(url,async()=>{
   const result=await post('/queue',request);
   const undo=result.undo_token?()=>queueTracked(url,async()=>{await post('/queue',{url,action:'undo',revision:result.revision,token:result.undo_token});await loadState();notify('Undone.',null,()=>queueShow(url));}):null;
   await loadState();
   const updated=findQueuePr(url);
   notify(result.existing?'This PR is already in My reviews.':queueMessage(updated,action,extras),undo,updated?.workflow&&action!=='note'?()=>queueShow(url):null);
   return result;
  });
 } finally {queueBusy.delete(url);renderQueue(true);}
}
document.addEventListener('click',async event=>{
 const button=event.target.closest('[data-queue-action]');if(!button||button.disabled)return;
 const {url,queueAction:action}=button.dataset;
 if(action==='show'){queueShow(url);return;}
 if(action==='note'){
  const pr=findQueuePr(url);noteContext={url,revision:pr.workflow.revision};$('queue-note-title').textContent=pr.title;$('queue-note').value=pr.workflow.note||'';$('queue-note-error').hidden=true;$('queue-note-dialog').showModal();$('queue-note').focus();return;
 }
 button.closest('details.snooze-picker')?.removeAttribute('open');
 const extras=action==='recover'?{recover:true}:action==='remind'?{days:Number(button.dataset.days)}:{};
 try{await queueAction(url,action==='recover'?'enqueue':action,extras);}catch(error){notify(error.message);}
});
$('queue-search').addEventListener('input',event=>{queueQuery=event.target.value;renderQueue(true);});
$('queue-search').addEventListener('keydown',event=>{if(event.key==='Escape'&&queueQuery){queueQuery='';event.target.value='';renderQueue(true);}});
$('my-reviews-tab').addEventListener('click',()=>showQueue(true));
$('reporting-tab').addEventListener('click',()=>showQueue(false));
$('queue-add').addEventListener('submit',async event=>{
 event.preventDefault();const input=event.target.elements.url;const button=event.target.querySelector('button');button.disabled=true;
 try{await queueAction(input.value.trim(),'enqueue');input.value='';closeDialog($('queue-add-dialog'));}catch(error){notify(error.message);}finally{button.disabled=false;}
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
function queueAutoRefresh(){
 if(document.hidden||!state)return;
 const tracked=state.prs.filter(pr=>pr.workflow&&pr.workflow.stage!=='removed'&&!pr.workflow.closed);
 const unchecked=tracked.some(pr=>!pr.workflow.checked_at&&!pr.workflow.attempted_at);
 if(Date.now()-queueAutoAt>=(unchecked?30000:300000))refreshQueue(unchecked);
}
document.addEventListener('visibilitychange',queueAutoRefresh);
window.addEventListener('focus',queueAutoRefresh);
setInterval(queueAutoRefresh,30000);
setTimeout(queueAutoRefresh,1500);
try{if(localStorage.getItem('pr-personal-view')==='queue')showQueue(true);}catch{}
