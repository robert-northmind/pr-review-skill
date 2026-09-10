'use strict';
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const artifactUrl = path => '/artifact?path='+encodeURIComponent(path);
const safeUrl = value => {try {const u=new URL(value);return u.protocol==='https:'?u.href:'#';} catch{return '#';}};
const labels={requested:'Requested from you',watching:'Watching',mine:'Your PRs',hidden:'Hidden'};
const descriptions={requested:'PRs assigned to you or requesting your review.',watching:'Open PRs from repositories you follow.',mine:'Open pull requests you created.',hidden:'Set aside for now. Restore a PR to bring it back to its view.'};
const statusLabels={starting:'Starting',queued:'Starting',running:'Reviewing',completed:'Completed',blocked:'Needs input',failed:'Run failed',cancelled:'Tracking stopped','no-activity':'No recent activity'};
const active = run => run && ['starting','queued','running','no-activity'].includes(run.status);
const attention = run => run && ['blocked','failed','no-activity'].includes(run.status);
const defaults={view:'requested',search:'',reportRepositoriesOnly:[],reportRepositoriesExcluded:[],repositoriesOnly:[],repositoriesExcluded:[],authorsOnly:[],authorsExcluded:[],statusesOnly:[],statusesExcluded:[],starred:false,drafts:'all',sort:'updated'};
let filters={...defaults};
try {filters={...defaults,...JSON.parse(localStorage.getItem('pr-inbox-filters')||'{}')};}catch{}
// Preserve selections saved by the earlier single-author filter.
const authorLogins = values => [...new Set((Array.isArray(values)?values:[]).filter(value=>typeof value==='string'&&value).map(value=>value.startsWith('app/')?value.slice(4)+'[bot]':value))];
filters.authorsOnly=authorLogins(Array.isArray(filters.authorsOnly)&&filters.authorsOnly.length?filters.authorsOnly:filters.author?[filters.author]:[]);
filters.authorsExcluded=authorLogins([...(Array.isArray(filters.authorsExcluded)?filters.authorsExcluded:[]),...(filters.hideRenovate?['renovate[bot]','renovate-sh-app[bot]']:[])]);
delete filters.author;delete filters.hideRenovate;
const selectedValues = values => [...new Set((Array.isArray(values)?values:[]).filter(value=>typeof value==='string'&&value))];
for(const key of ['reportRepositoriesOnly','reportRepositoriesExcluded'])filters[key]=selectedValues(filters[key]);
for(const [prefix,legacy] of [['repositories','repository'],['statuses','status']]){
 filters[prefix+'Only']=selectedValues(Array.isArray(filters[prefix+'Only'])&&filters[prefix+'Only'].length?filters[prefix+'Only']:filters[legacy]?[filters[legacy]]:[]);
 filters[prefix+'Excluded']=selectedValues(filters[prefix+'Excluded']);delete filters[legacy];
}
if(!labels[filters.view])filters.view='requested';
let reportingData=null, reportingActive=false, state=null, listSignature='', profiles={}, editingAgent='', settingsDirty=false, configSignature='', loading=false, toastTimer, undoAction=null;
const busy = new Set();
function saveFilters(){try{localStorage.setItem('pr-inbox-filters',JSON.stringify(filters));}catch{}}
function when(stamp){if(!stamp)return 'Not yet checked';const date=new Date(stamp);return Number.isNaN(date.valueOf())?'Unknown date':date.toLocaleString(undefined,{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'});}
function since(stamp){if(!stamp)return 'Unknown';const minutes=Math.max(0,Math.floor((Date.now()-new Date(stamp))/60000));if(!Number.isFinite(minutes))return 'Unknown';if(minutes<1)return 'just now';if(minutes<60)return minutes+'m ago';if(minutes<1440)return Math.floor(minutes/60)+'h ago';return Math.floor(minutes/1440)+'d ago';}
function notify(text,undo){clearTimeout(toastTimer);undoAction=undo||null;$('toast').replaceChildren(document.createTextNode(text));if(undo){const button=document.createElement('button');button.textContent='Undo';button.id='undo';$('toast').append(button);}$('toast').hidden=false;toastTimer=setTimeout(()=>$('toast').hidden=true,undo?10000:6000);}
async function post(action,data={}){const response=await fetch(action,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':document.querySelector('meta[name="csrf-token"]').content},body:JSON.stringify(data)});const result=await response.json();if(!response.ok)throw new Error(result.error||'The action failed.');return result;}
function artifactLink(a,label){return a?`<a class="button ${label==='Open notes'?'primary':''}" href="${esc(artifactUrl(a.path))}" target="_blank" rel="noopener" title="${esc(when(a.created_at)+' · '+a.tool+' · '+(a.head_sha?.slice(0,8)||'commit not recorded'))}">${esc(label)}</a>`:'';}
function renderHistory(pr){return pr.history.map(run=>`<div class="history-entry"><div><p>${esc(when(run.created_at))} · ${esc(run.tool)} · ${esc(statusLabels[run.status]||run.status)}</p><p class="muted">${esc(run.kind==='explainer'?'Explanation':'Review')} · Commit <code>${esc(run.head_sha?.slice(0,12)||'not recorded')}</code></p></div><div class="history-links">${Object.entries(run.artifacts).map(([name,a])=>`<a target="_blank" rel="noopener" href="${esc(artifactUrl(a.path))}">${name==='review-markdown'?'Notes':'Explainer'}</a>`).join('')}</div></div>`).join('');}
function authorBadge(pr){
 const login=pr.author_login||'';
 if(!login)return '<span class="pr-author unknown-author">Unknown author</span>';
 const encoded=encodeURIComponent(login), name=pr.author_name||login;
 const profileUrl=login.endsWith('[bot]')?'https://github.com/apps/'+encodeURIComponent(login.slice(0,-5)):'https://github.com/'+encoded;
 let avatar=`https://github.com/${encoded}.png?size=64`;
 try {const u=new URL(pr.author_avatar_url);if(u.protocol==='https:'&&u.hostname==='avatars.githubusercontent.com')avatar=u.href;}catch{}
 return `<a class="pr-author" href="${esc(profileUrl)}" target="_blank" rel="noopener" aria-label="Author: ${esc(name===login?login:name+' ('+login+')')}"><span class="avatar-wrap"><span class="avatar-fallback" aria-hidden="true">${esc(login.slice(0,1).toUpperCase())}</span><img class="author-avatar" src="${esc(avatar)}" alt="" width="28" height="28" loading="lazy" referrerpolicy="no-referrer"></span><span>${esc(name)}${name!==login?` <span class="author-login">@${esc(login)}</span>`:''}</span>${login.endsWith('[bot]')?'<span class="chip">Bot</span>':''}</a>`;
}
function card(pr){
 const run=pr.run, isActive=active(run), arts=pr.artifacts, hasNotes=!!arts['review-markdown'], hidden=!!pr.hidden;
 const buttons=hidden?`<button class="button" data-action="/unhide" data-url="${esc(pr.url)}">Restore PR</button>`:
  artifactLink(arts['review-markdown'],'Open notes')+artifactLink(arts['explanation-html'],'Explainer')+
  (!hasNotes?`<button class="button primary" data-action="/regenerate-review" data-url="${esc(pr.url)}" ${isActive?'disabled':''}>${isActive?'Run in progress':'Run review'}</button>`:'')+`<button class="button hide-pr" data-action="/hide" data-url="${esc(pr.url)}" aria-label="Hide PR ${esc(pr.number)}" title="Hide this PR — you can undo or restore it later">Hide</button>`;
 let status=run?`<span class="chip ${isActive?'run-live':attention(run)?'warn':''}">${esc(statusLabels[run.status]||run.status)}</span>`:'';
 if(hasNotes)status+=`<span class="chip good">AI notes available</span>`;
 if(pr.artifact_freshness==='older')status+='<span class="chip warn">Older commit · rerun to update</span>';
 if(Object.keys(arts).length && pr.artifact_freshness==='unknown')status+='<span class="chip">Commit freshness unverified</span>';
 if(pr.mixed_artifacts)status+='<span class="chip warn">Results from different runs</span>';
 const newestArtifact=Object.values(arts).sort((a,b)=>b.created_at.localeCompare(a.created_at))[0];
 const history=pr.history.length?`<div><p class="detail-heading">Run history (${pr.history_total})</p>${renderHistory(pr)}</div>`:'';
 return `<article class="pr-card" data-pr="${esc(pr.url)}"><div class="pr-main"><button class="star" aria-label="${pr.starred?'Unstar':'Star'} PR ${esc(pr.number)}" aria-pressed="${!!pr.starred}" data-action="/${pr.starred?'unstar':'star'}" data-url="${esc(pr.url)}">${pr.starred?'★':'☆'}</button><div><a class="pr-title" href="${esc(safeUrl(pr.url))}" target="_blank" rel="noopener">${esc(pr.title)}</a><div class="pr-byline">${authorBadge(pr)}</div><div class="pr-meta"><span>${esc(pr.owner+'/'+pr.repository)} #${esc(pr.number)}</span><span title="${esc(when(pr.pr_updated_at||pr.first_seen_at))}">${pr.pr_updated_at?'Updated':'First seen'} ${esc(since(pr.pr_updated_at||pr.first_seen_at))}</span>${pr.is_draft?'<span class="chip">Draft</span>':''}</div></div><div class="pr-actions">${buttons}</div></div>
 <div class="pr-foot"><span title="Your participation on GitHub">GitHub: ${esc(pr.participation)}</span>${status}${newestArtifact?`<span title="${esc(when(newestArtifact.created_at))}">Results ${esc(since(newestArtifact.created_at))}</span>`:''}</div>
 <details class="run-details"><summary>Review actions${run?' & history':''}</summary><div class="detail-content">
 ${!hidden?`<div class="action-bar"><button class="button" data-action="/regenerate-review" data-url="${esc(pr.url)}" ${isActive?'disabled':''}>${hasNotes?'Regenerate review':'Run full review'}</button><button class="button" data-action="/regenerate-explainer" data-url="${esc(pr.url)}" ${isActive?'disabled':''}>${arts['explanation-html']?'Regenerate explainer':'Generate explainer'}</button></div>`:''}
 ${run?`<section><p class="detail-heading">${esc(statusLabels[run.status]||run.status)} · ${esc(run.tool)}</p><p class="muted">Last recorded activity ${esc(since(run.updated_at))}. ${isActive?'Status comes from the review tracker; it does not prove the terminal is still running.':''}</p>${run.message?`<p class="muted">${esc(run.message)}</p>`:''}<ul class="task-list">${run.tasks.filter(t=>t.status!=='skipped').map(t=>`<li title="${esc(t.message)}">${esc(t.name.replaceAll('-',' '))}: ${esc(t.status)}</li>`).join('')}</ul>${run.session_reference?`<div class="action-bar"><button class="button" data-copy="${esc(run.session_reference)}">Copy session reference</button>${safeUrl(run.session_reference)!=='#'?`<a class="button" href="${esc(safeUrl(run.session_reference))}" target="_blank" rel="noopener">Open session</a>`:''}</div>`:'<p class="muted">No session reference recorded.</p>'}
 ${attention(run)||['starting','queued'].includes(run.status)?`<button class="button" data-action="/regenerate-review" data-url="${esc(pr.url)}" data-retry="true">Retry after closing the previous terminal</button>`:''}</section>`:''}
 ${Object.keys(arts).length?`<section><p class="detail-heading">Results currently shown</p>${Object.entries(arts).map(([name,a])=>`<p class="muted">${name==='review-markdown'?'Notes':'Explainer'}: ${esc(when(a.created_at))} · ${esc(a.tool)} · commit ${esc(a.head_sha?.slice(0,12)||'not recorded')}${a.status!=='completed'?' · partial result':''}</p>`).join('')}</section>`:''}${history}</div></details></article>`;
}
const statusOptions={unreviewed:'Not reviewed on GitHub',reviewed:'Reviewed on GitHub',ready:'AI notes available',running:'AI run active',attention:'AI run needs attention',older:'Older AI results'};
const pickerConfig={reportrepository:{prefix:'reportRepositories',title:'Repositories',empty:'All report repositories'},author:{prefix:'authors',title:'Authors',empty:'All authors'},repository:{prefix:'repositories',title:'Repositories',empty:'All repositories'},status:{prefix:'statuses',title:'Statuses',empty:'Any review status'}};
const pickerSignatures={};
function filterOptions(id){
 if(id==='reportrepository')return new Map((reportingData?.events||[]).map(event=>[event.repository,event.repository]));
 if(id==='status')return new Map(Object.entries(statusOptions));
 return new Map((state?.prs||[]).filter(pr=>id!=='author'||pr.author_login).map(pr=>id==='author'?[pr.author_login,pr.author_name||pr.author_login]:[pr.owner+'/'+pr.repository,pr.owner+'/'+pr.repository]));
}
function renderPicker(id){
 const {prefix,title,empty}=pickerConfig[id],only=filters[prefix+'Only'],excluded=filters[prefix+'Excluded'];
 const summary=[only.length?`${only.length} only`:'',excluded.length?`${excluded.length} excluded`:''].filter(Boolean).join(' · ');
 $(id+'-summary').textContent=summary?title+' · '+summary:empty;
 $(id+'-selection').textContent=summary||'No '+title.toLowerCase()+' filtered out';
 const options=filterOptions(id);
 for(const value of [...only,...excluded])if(!options.has(value))options.set(value,value);
 const query=$(id+'-search').value.trim().toLowerCase();
 const choices=[...options].filter(([value,name])=>`${name} ${value}`.toLowerCase().includes(query));
 if(id!=='status')choices.sort((a,b)=>a[1].localeCompare(b[1]));
 const signature=JSON.stringify([choices,only,excluded]);if(signature===pickerSignatures[id])return;pickerSignatures[id]=signature;
 const focused=document.activeElement,value=focused?.dataset?.filterValue,mode=focused?.dataset?.filterMode;
 const container=$(id+'-options'),scrollTop=container.scrollTop;
 container.innerHTML=choices.map(([value,name])=>{
  const label=id==='author'&&name!==value?name+' ('+value+')':name;
  return `<div class="filter-option"><div class="filter-option-name"><strong>${esc(name)}</strong>${id==='author'&&name!==value?`<span class="muted">@${esc(value)}</span>`:''}</div><button type="button" class="filter-choice" data-filter-value="${esc(value)}" data-filter-mode="only" aria-label="Show only ${esc(label)}" aria-pressed="${only.includes(value)}">Show only</button><button type="button" class="filter-choice exclude" data-filter-value="${esc(value)}" data-filter-mode="excluded" aria-label="Exclude ${esc(label)}" aria-pressed="${excluded.includes(value)}">Exclude</button></div>`;
 }).join('')||'<p class="muted">No '+title.toLowerCase()+' match your search.</p>';
 container.scrollTop=scrollTop;
 if(value&&mode)[...container.querySelectorAll('button')].find(button=>button.dataset.filterValue===value&&button.dataset.filterMode===mode)?.focus({preventScroll:true});
}
function renderPickers(){for(const id of Object.keys(pickerConfig))renderPicker(id);}
function updatePicker(id){saveFilters();renderPicker(id);if(id==='reportrepository')renderReporting();else renderList();}
function closePicker(id,focus=false){if($(id+'-picker').open){$(id+'-picker').open=false;if(focus)$(id+'-summary').focus();}}
for(const [id,{prefix}] of Object.entries(pickerConfig)){
 $(id+'-options').addEventListener('click',event=>{
  const button=event.target.closest('[data-filter-value]');if(!button)return;
  const value=button.dataset.filterValue,key=prefix+(button.dataset.filterMode==='only'?'Only':'Excluded');
  const other=prefix+(button.dataset.filterMode==='only'?'Excluded':'Only');
  filters[key]=filters[key].includes(value)?filters[key].filter(item=>item!==value):[...filters[key],value];
  filters[other]=filters[other].filter(item=>item!==value);updatePicker(id);
 });
 $(id+'-search').addEventListener('input',()=>renderPicker(id));
 $(id+'-clear').addEventListener('click',()=>{filters[prefix+'Only']=[];filters[prefix+'Excluded']=[];$(id+'-search').value='';updatePicker(id);});
 $(id+'-done').addEventListener('click',()=>closePicker(id,true));
}
$('exclude-renovate').addEventListener('click',()=>{
 const bots=authorLogins(['renovate[bot]','renovate-sh-app[bot]',...(state?.prs||[]).map(pr=>pr.author_login).filter(login=>/^renovate(?:[-\[]|$)/i.test(login||''))]);
 filters.authorsExcluded=authorLogins([...filters.authorsExcluded,...bots]);filters.authorsOnly=filters.authorsOnly.filter(login=>!bots.includes(login));updatePicker('author');
});
document.addEventListener('keydown',event=>{if(event.key==='Escape')for(const id of Object.keys(pickerConfig))if($(id+'-picker').open){event.preventDefault();closePicker(id,true);}});
document.addEventListener('click',event=>{for(const id of Object.keys(pickerConfig))if(!event.composedPath().includes($(id+'-picker')))closePicker(id);});
function matchesStatus(pr,status){
 switch(status){
  case 'unreviewed':return !pr.my_review_at;
  case 'reviewed':return !!pr.my_review_at;
  case 'ready':return !!pr.artifacts['review-markdown'];
  case 'running':return !!active(pr.run);
  case 'attention':return !!attention(pr.run);
  case 'older':return pr.artifact_freshness==='older';
  default:return false;
 }
}
function matchesSelection(only,excluded,matches){return (!only.length||only.some(matches))&&!excluded.some(matches);}
function visiblePrs(){
 const text=filters.search.toLowerCase().trim().replace(/^#/,'');
 return state.prs.filter(pr=>filters.view==='hidden'?pr.hidden:!pr.hidden&&pr.group===filters.view).filter(pr=>{
  if(text&&!`${pr.title} ${pr.owner}/${pr.repository} ${pr.number} ${pr.author_login} ${pr.author_name||''}`.toLowerCase().includes(text))return false;
  if(!matchesSelection(filters.repositoriesOnly,filters.repositoriesExcluded,value=>value===pr.owner+'/'+pr.repository))return false;
  if(!matchesSelection(filters.authorsOnly,filters.authorsExcluded,value=>value===pr.author_login))return false;
  if(filters.starred&&!pr.starred)return false;
  if(filters.drafts==='ready'&&pr.is_draft || filters.drafts==='only'&&!pr.is_draft)return false;
  if(!matchesSelection(filters.statusesOnly,filters.statusesExcluded,value=>matchesStatus(pr,value)))return false;
  return true;
 }).sort((a,b)=>{
  if(filters.sort==='starred'&&a.starred!==b.starred)return Number(!!b.starred)-Number(!!a.starred);
  const field=filters.sort==='oldest'?'first_seen_at':'pr_updated_at';
  const left=a[field]||a.first_seen_at||'',right=b[field]||b.first_seen_at||'';
  return (filters.sort==='oldest'?left.localeCompare(right):right.localeCompare(left)) || a.url.localeCompare(b.url);
 });
}
function renderList(force=false){if(!state)return;const prs=visiblePrs();const signature=JSON.stringify([prs,filters]);
 $('result-count').textContent=`${prs.length} ${prs.length===1?'PR':'PRs'}`;
 $('view-heading').textContent=labels[filters.view];$('view-description').textContent=descriptions[filters.view];
 document.querySelectorAll('[data-view]').forEach(button=>{const view=button.dataset.view;button.setAttribute('aria-pressed',!reportingActive&&view===filters.view);button.querySelector('.count').textContent=state.prs.filter(pr=>view==='hidden'?pr.hidden:!pr.hidden&&pr.group===view).length;});
 if(!force&&signature===listSignature)return;listSignature=signature;
 const expanded=new Set([...document.querySelectorAll('.pr-card:has(details[open])')].map(el=>el.dataset.pr));
 const focused=document.activeElement,focusUrl=focused?.dataset?.url,focusAction=focused?.dataset?.action;
 $('pr-list').innerHTML=prs.map(card).join('')||`<div class="empty"><h3>${filters.search||filters.repositoriesOnly.length||filters.repositoriesExcluded.length||filters.authorsOnly.length||filters.authorsExcluded.length||filters.statusesOnly.length||filters.statusesExcluded.length||filters.starred||filters.drafts!=='all'?'No PRs match these filters':'Nothing here right now'}</h3><p class="muted">${filters.view==='hidden'?'Hidden PRs can be restored here.':'Try another view, clear your filters, or refresh GitHub.'}</p><button class="text-button" data-clear>Clear filters</button></div>`;
 document.querySelectorAll('.pr-card').forEach(el=>{if(expanded.has(el.dataset.pr))el.querySelector('details').open=true;});
 if(focusUrl&&focusAction){const replacement=[...document.querySelectorAll('[data-action]')].find(el=>el.dataset.url===focusUrl&&el.dataset.action===focusAction);replacement?.focus({preventScroll:true});}
 for(const button of document.querySelectorAll('[data-action]'))if(busy.has(button.dataset.url))button.disabled=true;
}
function showConfig(config){configSignature=JSON.stringify(config);profiles=structuredClone(config.agent_profiles);editingAgent=config.agent;$('agent').value=editingAgent;fillAgent();settingsDirty=false;markDirty();}
function fillAgent(){const profile=profiles[editingAgent]||{model:'',effort:''};$('model').value=profile.model;$('effort').value=profile.effort;$('model-options').innerHTML=state.models[editingAgent].map(value=>`<option value="${esc(value)}"></option>`).join('');$('effort-options').innerHTML=state.efforts[editingAgent].map(value=>`<option value="${esc(value)}"></option>`).join('');}
function markDirty(){if(!state)return;const config=state.config;settingsDirty=editingAgent!==config.agent||$('model').value!==config.model||$('effort').value!==config.effort;$('save-state').textContent=settingsDirty?'Unsaved changes — save before starting a review.':'Saved. Blank fields use the CLI defaults.';$('discard').hidden=!settingsDirty;}
function renderState(){
 const config=state.config;$('effective-agent').textContent=`${config.agent==='codex'?'Codex · Approve for me':'Claude Code'} · ${config.model||'default model'}${config.effort?' · '+config.effort+' effort':''}`;
 const count=state.prs.filter(pr=>active(pr.run)).length;$('active-runs').textContent=count?`${count} active ${count===1?'run':'runs'}`:'';
 const refresh=state.refresh||{}, isRefreshing=refresh.status==='running';$('refresh').disabled=isRefreshing;$('refresh').querySelector('span').textContent=isRefreshing?'Refreshing…':'Refresh GitHub';
 const stamp=state.last_github_refresh_at||state.last_refresh_attempt_at;
 $('freshness').textContent=isRefreshing?'Checking GitHub in the background…':stamp?`${state.last_github_refresh_at?'GitHub refreshed':'Last refresh attempt'} ${since(stamp)}`:'GitHub has not been refreshed yet';$('freshness').title=when(stamp);
 const warnings=[...state.warnings];if(refresh.status==='failed')warnings.unshift(refresh.message||'The refresh failed. Please retry.');
 $('warnings').hidden=!warnings.length;$('warnings').innerHTML=warnings.length?`<details><summary>${warnings.length} refresh ${warnings.length===1?'issue':'issues'} · previous data kept where a source was incomplete</summary><ul>${warnings.map(w=>`<li>${esc(w)}</li>`).join('')}</ul></details>`:'';
 if(!settingsDirty&&JSON.stringify(config)!==configSignature)showConfig(config);
 renderPickers();
 $('watched-repos').innerHTML=config.watched_repos.map(repo=>`<li><span>${esc(repo)}</span><button class="text-button" data-remove-repo="${esc(repo)}" aria-label="Stop watching ${esc(repo)}">Remove</button></li>`).join('')||'<li class="muted">No watched repositories yet.</li>';
 renderList();
}
async function loadState(){if(loading)return;loading=true;try{const response=await fetch('/api/state');if(!response.ok)throw new Error('Could not read the inbox.');state=await response.json();$('connection').hidden=true;renderState();}catch(error){$('connection').hidden=false;$('connection').textContent='Connection interrupted. Showing the last loaded inbox; retrying automatically. '+error.message;}finally{loading=false;}}
function syncFilterControls(){ $('search').value=filters.search;$('starred').checked=filters.starred;renderPickers();$('drafts').value=filters.drafts;$('sort').value=filters.sort;}
function clearFilters(){for(const id of Object.keys(pickerConfig))$(id+'-search').value='';filters={...defaults,view:filters.view,reportRepositoriesOnly:filters.reportRepositoriesOnly,reportRepositoriesExcluded:filters.reportRepositoriesExcluded};syncFilterControls();saveFilters();renderList();}
document.addEventListener('click',async event=>{
 const view=event.target.closest('[data-view]');if(view){showReporting(false);filters.view=view.dataset.view;saveFilters();renderList();return;}
 if(event.target.closest('[data-clear]')||event.target.closest('#clear-filters')){clearFilters();return;}
 if(event.target.closest('#undo')){const action=undoAction;undoAction=null;$('toast').hidden=true;try{await action?.();}catch(error){notify(error.message);}return;}
 const copy=event.target.closest('[data-copy]');if(copy){try{await navigator.clipboard.writeText(copy.dataset.copy);notify('Session reference copied.');}catch{notify('Could not access the clipboard. Session: '+copy.dataset.copy);}return;}
 const remove=event.target.closest('[data-remove-repo]');if(remove){try{await post('/remove-repo',{repo:remove.dataset.removeRepo});notify('Repository removed. Refresh GitHub to update the inbox.');await loadState();}catch(error){notify(error.message);}return;}
 const button=event.target.closest('[data-action]');if(!button||button.disabled)return;
 const {action,url,retry}=button.dataset;const launching=action.startsWith('/regenerate-');
 if(launching&&settingsDirty){notify('Save or discard your agent settings before starting a review.');$('settings').open=true;return;}
 if(retry==='true'&&!confirm('Close the previous Terminal session first. Retry stops tracking that run; it does not stop its process. Start a new review?'))return;
 busy.add(url);button.disabled=true;
 try{const result=await post(action,{url,retry:retry==='true'});
  if(launching)notify(result.existing?'This PR already has an active run. Open its review history for details.':'Terminal opened. Progress will appear here and survives reloading the page.');
  else if(action==='/hide')notify('PR hidden.',async()=>{await post('/unhide',{url});await loadState();});
  else if(action==='/unhide')notify('PR restored.');
  await loadState();
 }catch(error){notify(error.message);}finally{busy.delete(url);renderList(true);}
});
for(const [id,key] of [['search','search'],['drafts','drafts'],['sort','sort']])$(id).addEventListener(id==='search'?'input':'change',()=>{filters[key]=$(id).value;saveFilters();renderList();});

// Keep a legible avatar fallback if a profile image is missing or unavailable.
document.addEventListener('error',event=>{if(event.target.matches?.('.author-avatar'))event.target.hidden=true;},true);
$('starred').addEventListener('change',()=>{filters.starred=$('starred').checked;saveFilters();renderList();});
$('agent').addEventListener('change',()=>{profiles[editingAgent]={model:$('model').value,effort:$('effort').value};editingAgent=$('agent').value;fillAgent();markDirty();});
$('model').addEventListener('input',markDirty);$('effort').addEventListener('input',markDirty);
$('discard').addEventListener('click',()=>showConfig(state.config));
$('agent-form').addEventListener('submit',async event=>{event.preventDefault();try{await post('/set-config',{agent:editingAgent,model:$('model').value,effort:$('effort').value});settingsDirty=false;configSignature='';await loadState();notify('Review settings saved.');}catch(error){notify(error.message);}});
$('repo-form').addEventListener('submit',async event=>{event.preventDefault();try{await post('/add-repo',{repo:$('add-repo').value});$('add-repo').value='';notify('Repository added. Refresh GitHub to load its PRs.');await loadState();}catch(error){notify(error.message);}});
$('refresh').addEventListener('click',async()=>{try{$('refresh').disabled=true;await post('/refresh');await loadState();}catch(error){$('refresh').disabled=false;notify(error.message);}});
syncFilterControls();
(async function poll(){await loadState();setTimeout(poll,5000);})();
