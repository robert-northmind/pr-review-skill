'use strict';
// Review load is the triage effort, shown as Low/Medium/High with four parts (see triage_provider).
const effortLabels={quick:'Low',moderate:'Medium',involved:'High',uncertain:'Unsure'};
const loadLevels={quick:'low',moderate:'medium',involved:'high',uncertain:'unknown'};
const loadWords={low:'Low',medium:'Medium',high:'High',unknown:'Unsure'};
const loadParts=[['change_scope','Change scope','How much handwritten behavior changes, and how widely'],['required_context','Required context','Unchanged code, domain or contracts you need to load'],['conceptual_complexity','Conceptual complexity','State, lifecycle, concurrency or tricky logic'],['review_risk','Review risk','What a missed defect would cost']];
function triageEffort(pr){return pr.triage?.status==='completed'?pr.triage.effort:'uncertain';}
function matchesTriage(pr,filter){return filter==='all'||triageEffort(pr)===filter;}
function compareTriage(a,b){
 const rank={quick:0,moderate:1,involved:2,uncertain:3};
 return rank[triageEffort(a)]-rank[triageEffort(b)]||(a.pr_created_at||'9999').localeCompare(b.pr_created_at||'9999')||a.url.localeCompare(b.url);
}
function loadBars(parts){return parts?`<span class="load-bars" aria-hidden="true">${loadParts.map(([key])=>`<i data-level="${esc(parts[key].level)}"></i>`).join('')}</span>`:'';}
// compact: the list cell — the word and bars only; the side panel has the details.
function triageBadge(pr,compact=false){
 const t=pr.triage;
 if(t?.status!=='completed'){
  const label={running:'Estimating…',failed:'Unavailable',stale:'Outdated'}[t?.status]||'Not estimated';
  if(compact)return `<span class="load-none" title="Review load: ${esc(label)}">${t?.status==='running'?'Estimating…':'–'}</span>`;
  return `<span class="effort-badge"><span class="effort-label">Review load</span> ${esc(label)}</span>`;
 }
 const level=loadLevels[t.effort]||'unknown',parts=t.components;
 const levels=parts?`<dl>${loadParts.map(([key,label])=>`<dt>${label}</dt><dd><span class="load-level load-${esc(parts[key].level)}">${loadWords[parts[key].level]}</span></dd>`).join('')}</dl>`:'<p>No breakdown yet. Re-estimate to get the four parts.</p>';
 const tip=`<span class="load-tip" role="tooltip"><strong>Review load: ${loadWords[level]}</strong><span class="load-tip-what">How much reviewing this PR is likely to take, estimated from the diff before any AI review: how much changes, how much context you need, how tricky it is, and what a missed bug would cost.</span>${t.reason?`<span class="load-tip-reason">${esc(t.reason)}</span>`:''}${levels}${t.outdated?'<span class="load-tip-reason load-tip-outdated">This estimate is for an older commit or different settings. Re-estimate to update it.</span>':''}<span class="load-tip-more">Click for the reasons behind each part.</span></span>`;
 return `<button type="button" class="load-badge load-${level}${t.outdated?' is-outdated':''}" data-load-open aria-label="Review load ${loadWords[level]}${t.outdated?', outdated':''}. Show details.">${compact?'':'<span class="load-prefix">Review load</span> '}${loadWords[level]}${loadBars(parts)}${compact?'':tip}</button>`;
}
function loadBreakdown(parts){
 if(!parts)return '';
 return `<ul class="load-parts">${loadParts.map(([key,label,hint])=>`<li><div class="load-part-head"><div><strong>${label}</strong><span class="muted">${hint}</span></div><span class="load-level load-${esc(parts[key].level)}">${loadWords[parts[key].level]}</span></div><p>${esc(parts[key].reason)}</p></li>`).join('')}</ul>`;
}
function triageCard(pr){
 const t=pr.triage;if(!t)return '';
 const done=t.status==='completed';
 const action=t.can_reestimate?`<button type="button" class="button subtle" data-triage-reestimate data-estimate-id="${esc(t.id||'')}" data-url="${esc(pr.url)}" ${triageRunDisabled({...state.triage,counts:{waiting:1}})?'disabled':''}>${done?'Re-estimate':'Estimate review load'}</button>`:'';
 const context=[...(t.attention||[]),...(t.missing_context||[])];
 const rerun=t.rerun_status?(t.rerun_status==='running'&&state.triage.status?.state==='running'&&state.triage.status?.current_url===pr.url?'Re-estimating… Previous estimate shown.':'Re-estimate did not finish. Previous estimate kept; retry from Estimate details.'):'';
 return `<section class="triage-summary" aria-label="Estimated review load">
 ${t.reason?`<p class="triage-reason muted">${esc(t.reason)}</p>`:''}
 ${rerun?`<p class="triage-rerun muted">${esc(rerun)}</p>`:''}
 <details class="triage-details"><summary>Review load details</summary>
 ${t.reason?`<p>${esc(t.reason)}</p>`:''}
 ${done?loadBreakdown(t.components):''}
 ${pr.is_draft?'<p class="muted">Draft — estimated only on request.</p>':''}
 ${t.outdated?'<p class="muted">This estimate covers an older PR revision or different settings. Re-estimate to update it.</p>':''}
 ${context.length?`<ul class="triage-context">${context.map(item=>`<li>${esc(item)}</li>`).join('')}</ul>`:''}
 ${done?`<p class="muted">Initial estimate, not an approval. ${esc(t.provider)} · ${esc(t.model)} · ${esc(when(t.finished_at))} · commit ${esc(t.head_sha?.slice(0,12))}</p>`:''}
 <div class="action-bar">${action}</div>
 ${done?`<p class="muted">After your review, did the review load feel about right?</p><div class="triage-feedback" role="group" aria-label="Rate the review load estimate">${[['about_right','About right'],['too_low','Took more effort'],['too_high','Took less effort']].map(([rating,text])=>`<button type="button" class="button subtle" data-triage-rating="${rating}" data-estimate-id="${esc(t.id)}" data-url="${esc(pr.url)}" ${t.outdated||t.rerun_status?'disabled':''} aria-pressed="${t.feedback?.rating===rating}">${text}</button>`).join('')}</div>`:''}
 </details></section>`;
}
let triageDirty=false,triageStarting=false;
function renderTriageSettings(){
 const t=state?.triage;if(!t)return;
 renderTriageProgress();
 document.querySelectorAll('[data-triage-reestimate]').forEach(button=>{button.disabled=triageRunDisabled({...t,counts:{waiting:1}});});
 $('triage-status').textContent=`Runs through all eligible unestimated PRs in the inbox and active My reviews. Drafts need a manual estimate; hidden, snoozed, and your own PRs are skipped.`;
 $('triage-run').disabled=triageRunDisabled(t);
 $('triage-run').textContent=triageStarting||['starting','running'].includes(t.status?.state)?'Estimating…':'Estimate all waiting';
}
function triageRunDisabled(t){
 const calls=t.budget?.date===new Date().toISOString().slice(0,10)?t.budget.calls:0;
 return !t.config.enabled||triageDirty||triageStarting||['starting','running'].includes(t.status?.state)||calls>=t.config.daily_limit||(t.counts&&t.counts.waiting===0&&!t.counts.updates_waiting);
}
async function startTriageBatch(url=null,estimateId=null){
 triageStarting=true;renderTriageSettings();
 try{const result=await post(url?'/triage-reestimate':'/triage-run',url?{url,estimate_id:estimateId}:{});if(!result.started)notify(state?.triage?.config.enabled?'A batch is already starting or running.':'Enable automatic estimates first.');await loadState();}
 catch(error){notify(error.message);}
 finally{triageStarting=false;renderTriageSettings();}
}
function renderTriageProgress(){
 const t=state?.triage;if(!t)return;
 const s=t.status||{},c=t.counts||{},running=s.state==='running',starting=triageStarting||s.state==='starting',busy=running||starting;
 const calls=t.budget?.date===new Date().toISOString().slice(0,10)?t.budget.calls:0;
 const limited=calls>=t.config.daily_limit;
 const failed=['failed','interrupted'].includes(s.outcome);
 const quotaBlocked=limited&&((c.waiting||0)+(c.retrying_later||0)>0);
 const blocked=!busy&&t.config.enabled&&(failed||quotaBlocked);
 const activity=$('triage-activity');activity.hidden=!busy&&!blocked;
 activity.classList.toggle('is-blocked',blocked);
 let title='Review load estimates';
 if(starting)title='Starting review load estimates…';
 else if(running)title=Number.isFinite(s.target)?`Estimating review load · ${s.processed||0} of ${s.target} processed`:'Estimating review load…';
 else if(!t.config.enabled)title='Automatic review load estimates are off';
 else if(s.outcome==='failed'||s.outcome==='interrupted')title='Review load estimates stopped';
 else if(limited)title='Daily triage limit reached';
 else if(s.finished_at)title=`Last batch finished · ${s.processed||0} PRs processed`;
 $('triage-progress-title').textContent=title;
 $('triage-activity-title').textContent=busy?title:quotaBlocked?'Daily triage limit reached':'Review load estimates stopped';
 const activityMessage=$('triage-activity-message');
 activityMessage.textContent=quotaBlocked?'Waiting estimates can continue after midnight UTC.':failed?(s.message||'The previous run was interrupted. Open Details for status and retry availability.'):'';
 activityMessage.hidden=!blocked||!activityMessage.textContent;
 $('triage-spinner').hidden=!busy;
 const current=$('triage-progress-current');current.replaceChildren();current.hidden=false;
 const phases={comparing:'Comparing new commits with the last AI review','estimating-update':'Choosing an update or a full review',fetching:'Reading GitHub diff',estimating:'Estimating review load',checking:'Checking the PR is still current',preparing:'Preparing the next PR'};
 if(running){
  current.append(document.createTextNode((phases[s.phase]||'Working')+(s.current_url?' · ':'')));
  if(s.current_url){const link=document.createElement('a');link.href=safeUrl(s.current_url);link.target='_blank';link.rel='noopener';try{const p=new URL(s.current_url).pathname.split('/');link.textContent=p[1]+'/'+p[2]+' #'+p[4];}catch{link.textContent='Current PR';}current.append(link);}
 }else if(starting)current.textContent='The background worker is starting. You can keep browsing.';
 else if(s.finished_at)current.textContent='Finished '+when(s.finished_at)+(Number.isFinite(s.uncertain)?` · ${s.uncertain} uncertain in this batch`:'');
 else current.hidden=true;
 const bar=$('triage-progress-bar');bar.hidden=!running||!s.target;if(!bar.hidden){bar.max=s.target;bar.value=Math.min(s.processed||0,s.target);}
 $('triage-progress-counts').textContent=`${c.estimated||0} of ${c.eligible||0} eligible PRs estimated · ${c.waiting||0} waiting${c.updates_waiting?` · ${c.updates_waiting} review update check${c.updates_waiting===1?'':'s'} waiting`:''}${c.outdated?` · ${c.outdated} outdated (manual re-estimate)`:''}${c.active?` · ${c.active} in progress`:''}${c.retrying_later?` · ${c.retrying_later} retrying later`:''} · ${calls||0}/${t.config.daily_limit} model calls today (UTC). Counts cover the inbox and active My reviews, ignoring filters.`;
 const message=$('triage-progress-message');
 message.textContent=s.message||(limited?'More model calls are available after midnight UTC.':c.retrying_later?'Failed or interrupted estimates wait one hour before retrying.':c.uncertain?'Uncertain is a completed assessment: the available context was insufficient for a reliable review load estimate.':'');message.hidden=!message.textContent;
 const button=$('triage-progress-run');button.disabled=triageRunDisabled(t);button.hidden=!blocked||button.disabled;
}
// A load badge opens the breakdown: in its card, or in the side panel from a list row.
document.addEventListener('click',event=>{
 const badge=event.target.closest('[data-load-open]');if(!badge)return;
 const row=badge.closest('[data-row-open]');
 if(row){openDrawer(row.dataset.pr||row.dataset.queuePr,row.dataset.rowOpen,'details.triage-details');return;}
 const details=badge.closest('.pr-card')?.querySelector('details.triage-details');if(!details)return;
 for(let d=details;d;d=d.parentElement?.closest('details'))d.open=true;details.scrollIntoView({block:'nearest',behavior:'smooth'});details.querySelector('summary').focus({preventScroll:true});
});
document.addEventListener('DOMContentLoaded',()=>{
 $('triage-details-show').addEventListener('click',()=>{showDialog('activity-dialog');$('triage-progress-title').focus();});
 for(const id of ['triage-run','triage-progress-run'])$(id).addEventListener('click',()=>startTriageBatch());
 document.addEventListener('click',async event=>{
  const rerun=event.target.closest('[data-triage-reestimate]');
  if(rerun){if(!rerun.disabled){rerun.disabled=true;await startTriageBatch(rerun.dataset.url,rerun.dataset.estimateId);}return;}
  const b=event.target.closest('[data-triage-rating]');if(!b||b.disabled)return;b.disabled=true;
  try{await post('/triage-feedback',{url:b.dataset.url,estimate_id:b.dataset.estimateId,rating:b.dataset.triageRating});notify('Thanks — your review load rating was saved locally.');await loadState();}catch(error){notify(error.message);}finally{b.disabled=false;}
 });
});
