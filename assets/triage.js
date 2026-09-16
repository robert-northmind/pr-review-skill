'use strict';
const effortLabels={quick:'Quick',moderate:'Moderate',involved:'Involved',uncertain:'Uncertain'};
function triageEffort(pr){return pr.triage?.status==='completed'?pr.triage.effort:'uncertain';}
function matchesTriage(pr,filter){return filter==='all'||triageEffort(pr)===filter;}
function compareTriage(a,b){
 const rank={quick:0,moderate:1,involved:2,uncertain:3};
 return rank[triageEffort(a)]-rank[triageEffort(b)]||(a.pr_created_at||'9999').localeCompare(b.pr_created_at||'9999')||a.url.localeCompare(b.url);
}
function triageCard(pr){
 const t=pr.triage;if(!t)return '';
 const action=t.can_reestimate?`<button type="button" class="button subtle" data-triage-reestimate data-estimate-id="${esc(t.id||'')}" data-url="${esc(pr.url)}" ${triageRunDisabled({...state.triage,counts:{waiting:1}})?'disabled':''}>${t.status==='completed'?'Re-estimate':'Estimate effort'}</button>`:'';
 if(t.status==='not_estimated')return action?`<section class="triage-summary" aria-label="Estimated review effort">${action}${pr.is_draft?' <span class="muted">Draft — estimated only on request.</span>':''}</section>`:'';
 const done=t.status==='completed',effort=triageEffort(pr);
 const label=done?effortLabels[effort]:({running:'Estimating…',stale:'Estimate outdated',failed:'Estimate unavailable'}[t.status]||'Uncertain');
 const reestimate=action;
 const detail=[...(t.attention||[]),...(t.missing_context||[])];
 return `<section class="triage-summary" aria-label="Estimated review effort"><div class="triage-line"><span class="effort-badge effort-${effort}">${esc(label)}</span>${t.outdated?'<span class="effort-badge effort-uncertain">Outdated</span>':''}${reestimate}<span>${esc(t.reason||'Reading the PR diff to estimate review effort.')}</span></div>${t.outdated?'<p class="muted triage-context">The PR or triage settings changed since this estimate. It is kept until you choose Re-estimate.</p>':''}${t.rerun_status?`<p class="muted triage-context">${t.rerun_status==='running'&&state.triage.status?.state==='running'&&state.triage.status?.current_url===pr.url?'Re-estimating… Previous estimate shown.':'Re-estimate did not finish. Previous estimate kept; choose Re-estimate to retry.'}</p>`:''}${done&&detail.length?`<p class="muted triage-context">${detail.map(esc).join(' · ')}</p>`:''}${done?`<details class="triage-details"><summary>About this estimate</summary><p class="muted">Initial estimate, not an approval. ${esc(t.provider)} · ${esc(t.model)} · ${esc(when(t.finished_at))} · commit ${esc(t.head_sha?.slice(0,12))}</p><p class="muted">After your normal review, did the effort feel about right?</p><div class="triage-feedback" role="group" aria-label="Rate review effort estimate">${[['about_right','About right'],['too_low','Took more effort'],['too_high','Took less effort']].map(([rating,text])=>`<button type="button" class="button subtle" data-triage-rating="${rating}" data-estimate-id="${esc(t.id)}" data-url="${esc(pr.url)}" ${t.outdated||t.rerun_status?'disabled':''} aria-pressed="${t.feedback?.rating===rating}">${text}</button>`).join('')}</div></details>`:''}</section>`;
}
let triageDirty=false,triageConfigSignature='',triageStarting=false;
function renderTriageSettings(){
 const t=state?.triage;if(!t)return;
 renderTriageProgress();
 const c=t.config,signature=JSON.stringify(c);
 document.querySelectorAll('[data-triage-reestimate]').forEach(button=>{button.disabled=triageRunDisabled({...t,counts:{waiting:1}});});
 if(!triageDirty&&signature!==triageConfigSignature){
  $('triage-enabled').value=String(c.enabled);$('triage-provider').value=c.provider;$('triage-model').value=c.model;$('triage-limit').value=c.daily_limit;triageConfigSignature=signature;
 }
 $('triage-status').textContent=`Runs through all eligible unestimated PRs in the inbox and active My reviews. Drafts need a manual estimate; hidden, snoozed, and your own PRs are skipped.`;
 $('triage-run').disabled=triageRunDisabled(t);
 $('triage-run').textContent=triageStarting||['starting','running'].includes(t.status?.state)?'Estimating…':'Estimate all waiting';
}
function triageRunDisabled(t){
 const calls=t.budget?.date===new Date().toISOString().slice(0,10)?t.budget.calls:0;
 return !t.config.enabled||triageDirty||triageStarting||['starting','running'].includes(t.status?.state)||calls>=t.config.daily_limit||(t.counts&&t.counts.waiting===0);
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
 let title='Review effort estimates';
 if(starting)title='Starting effort estimates…';
 else if(running)title=Number.isFinite(s.target)?`Estimating review effort · ${s.processed||0} of ${s.target} processed`:'Estimating review effort…';
 else if(!t.config.enabled)title='Automatic effort estimates are off';
 else if(s.outcome==='failed'||s.outcome==='interrupted')title='Effort estimates stopped';
 else if(limited)title='Daily triage limit reached';
 else if(s.finished_at)title=`Last batch finished · ${s.processed||0} PRs processed`;
 $('triage-progress-title').textContent=title;
 $('triage-activity-title').textContent=busy?title:quotaBlocked?'Daily triage limit reached':'Effort estimates stopped';
 const activityMessage=$('triage-activity-message');
 activityMessage.textContent=quotaBlocked?'Waiting estimates can continue after midnight UTC.':failed?(s.message||'The previous run was interrupted. Open Details for status and retry availability.'):'';
 activityMessage.hidden=!blocked||!activityMessage.textContent;
 $('triage-spinner').hidden=!busy;
 const current=$('triage-progress-current');current.replaceChildren();current.hidden=false;
 const phases={fetching:'Reading GitHub diff',estimating:'Estimating effort',checking:'Checking the PR is still current',preparing:'Preparing the next PR'};
 if(running){
  current.append(document.createTextNode((phases[s.phase]||'Working')+(s.current_url?' · ':'')));
  if(s.current_url){const link=document.createElement('a');link.href=safeUrl(s.current_url);link.target='_blank';link.rel='noopener';try{const p=new URL(s.current_url).pathname.split('/');link.textContent=p[1]+'/'+p[2]+' #'+p[4];}catch{link.textContent='Current PR';}current.append(link);}
 }else if(starting)current.textContent='The background worker is starting. You can keep browsing.';
 else if(s.finished_at)current.textContent='Finished '+when(s.finished_at)+(Number.isFinite(s.uncertain)?` · ${s.uncertain} uncertain in this batch`:'');
 else current.hidden=true;
 const bar=$('triage-progress-bar');bar.hidden=!running||!s.target;if(!bar.hidden){bar.max=s.target;bar.value=Math.min(s.processed||0,s.target);}
 $('triage-progress-counts').textContent=`${c.estimated||0} of ${c.eligible||0} eligible PRs estimated · ${c.waiting||0} waiting${c.outdated?` · ${c.outdated} outdated (manual re-estimate)`:''}${c.active?` · ${c.active} in progress`:''}${c.retrying_later?` · ${c.retrying_later} retrying later`:''} · ${calls||0}/${t.config.daily_limit} model calls today (UTC). Counts cover the inbox and active My reviews, ignoring filters.`;
 const message=$('triage-progress-message');
 message.textContent=s.message||(limited?'More model calls are available after midnight UTC.':c.retrying_later?'Failed or interrupted estimates wait one hour before retrying.':c.uncertain?'Uncertain is a completed assessment: the available context was insufficient for a reliable effort estimate.':'');message.hidden=!message.textContent;
 const button=$('triage-progress-run');button.disabled=triageRunDisabled(t);button.hidden=!blocked||button.disabled;
}
document.addEventListener('DOMContentLoaded',()=>{
 $('triage-form').addEventListener('input',()=>{triageDirty=true;$('triage-save-state').textContent='Unsaved changes';renderTriageSettings();});
 $('triage-form').addEventListener('submit',async event=>{
  event.preventDefault();try{
   await post('/triage-config',{enabled:$('triage-enabled').value==='true',provider:$('triage-provider').value,model:$('triage-model').value.trim(),daily_limit:Number($('triage-limit').value)});
   triageDirty=false;triageConfigSignature='';$('triage-save-state').textContent='Saved';await loadState();notify('Triage settings saved. Refresh GitHub to estimate new PRs. Existing estimates are kept until you choose Re-estimate.');
  }catch(error){notify(error.message);}
 });
 $('triage-details-show').addEventListener('click',()=>{$('settings').open=true;$('triage-settings-heading').focus();$('triage-form').scrollIntoView({block:'nearest'});});
 for(const id of ['triage-run','triage-progress-run'])$(id).addEventListener('click',()=>startTriageBatch());
 document.addEventListener('click',async event=>{
  const rerun=event.target.closest('[data-triage-reestimate]');
  if(rerun){if(!rerun.disabled){rerun.disabled=true;await startTriageBatch(rerun.dataset.url,rerun.dataset.estimateId);}return;}
  const b=event.target.closest('[data-triage-rating]');if(!b||b.disabled)return;b.disabled=true;
  try{await post('/triage-feedback',{url:b.dataset.url,estimate_id:b.dataset.estimateId,rating:b.dataset.triageRating});notify('Thanks — your effort rating was saved locally.');await loadState();}catch(error){notify(error.message);}finally{b.disabled=false;}
 });
});
