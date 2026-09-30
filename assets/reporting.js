'use strict';
let reportSignature='',reportInterval='daily',reportSelected='',reportLoading=false,reportLoadError='',reportScrollToLatest=false;
let reportPreferences={window:10,timeOff:[]},reportTrendPoints=[],reportChartObserver=null,costSelected='';
const dateShift=(day,days)=>{const d=new Date(day+'T12:00:00Z');d.setUTCDate(d.getUTCDate()+days);return d.toISOString().slice(0,10);};
const weekStart=day=>{const dow=new Date(day+'T12:00:00Z').getUTCDay();return dateShift(day,-((dow+6)%7));};
const reportDate=day=>new Date(day+'T12:00:00Z').toLocaleDateString(undefined,{month:'short',day:'numeric',timeZone:'UTC'});
function reportCounts(events,start,end){
 const selected=events.filter(event=>event.date>=start&&event.date<=end);
 return {review:[...new Map(selected.filter(event=>event.kind==='review').map(event=>[event.url,event])).values()],merge:[...new Map(selected.filter(event=>event.kind==='merge').map(event=>[event.url,event])).values()]};
}
function reportPeriods(start,end,interval){
 const periods=[];let day=interval==='weekly'?weekStart(start):start;
 while(day<=end){const last=interval==='weekly'?dateShift(day,6):day;periods.push({start:day,end:last});day=dateShift(last,1);}
 return periods;
}
function reportValidDate(day){
 if(typeof day!=='string'||!/^\d{4}-\d{2}-\d{2}$/.test(day))return false;
 const date=new Date(day+'T12:00:00Z');
 return Number.isFinite(date.valueOf())&&date.toISOString().slice(0,10)===day;
}
function reportNormalizePreferences(value){
 const ranges=(Array.isArray(value?.timeOff)?value.timeOff:[])
  .filter(range=>reportValidDate(range?.start)&&reportValidDate(range?.end)&&range.start<=range.end)
  .map(range=>({start:range.start,end:range.end})).sort((a,b)=>a.start.localeCompare(b.start));
 const timeOff=[];
 for(const range of ranges){const last=timeOff.at(-1);if(last&&range.start<=last.end)last.end=last.end>range.end?last.end:range.end;else timeOff.push(range);}
 return {window:value?.window===5?5:10,timeOff};
}
try{reportPreferences=reportNormalizePreferences(JSON.parse(localStorage.getItem('pr-inbox-reporting')||'{}'));}catch{}
function reportDayOff(day,timeOff){
 if(timeOff.some(range=>day>=range.start&&day<=range.end))return 'Time off';
 return [0,6].includes(new Date(day+'T12:00:00Z').getUTCDay())?'Weekend':'';
}
function reportTrends(events,start,end,today,preferences){
 const history=[],points=[];
 // range_end is the sync day, whose activity may still be incomplete even in an old cache.
 const completeBefore=end<today?end:today;
 let average=null;
 for(const period of reportPeriods(start,end,'daily')){
  const day=period.start,off=reportDayOff(day,preferences.timeOff),complete=day<completeBefore;
  if(complete&&!off){
   const counts=reportCounts(events,day,day);
   history.push({review:counts.review.length,merge:counts.merge.length});
   if(history.length>preferences.window)history.shift();
   if(history.length===preferences.window)average={
    review:history.reduce((sum,item)=>sum+item.review,0)/preferences.window,
    merge:history.reduce((sum,item)=>sum+item.merge,0)/preferences.window
   };
  }
  points.push({day,off,average:complete?average:null,workdays:history.length});
 }
 return points;
}
function reportTrendDescription(point){
 if(!point?.average)return `Activity trend needs ${reportPreferences.window} complete workdays of history.`;
 return `${reportPreferences.window}-workday average: ${point.average.review.toFixed(1)} reviewed · ${point.average.merge.toFixed(1)} yours merged per workday${point.off?' · '+point.off+' excluded':''}.`;
}
function drawReportTrend(){
 const track=$('report-content').querySelector('.report-chart-track'),overlay=track?.querySelector('.report-trend-overlay');
 if(!overlay||!track.clientWidth)return;
 const box=track.getBoundingClientRect(),buttons=[...track.querySelectorAll('.report-bar')];
 const maximum=Number(track.dataset.maximum),width=track.clientWidth,height=track.clientHeight;
 overlay.setAttribute('viewBox',`0 0 ${width} ${height}`);
 overlay.setAttribute('width',width);overlay.setAttribute('height',height);
 overlay.innerHTML=['review','merge'].map(kind=>{
  const points=reportTrendPoints.flatMap((point,index)=>{
   if(!point.average)return [];
   const plot=buttons[index]?.querySelector('svg').getBoundingClientRect();
   if(!plot)return [];
   return [{x:plot.left-box.left+plot.width/2,y:plot.bottom-box.top-point.average[kind]/maximum*(84/90)*plot.height}];
  });
  if(!points.length)return '';
  const last=points.at(-1),path=points.map((point,index)=>`${index?'L':'M'}${point.x.toFixed(2)},${point.y.toFixed(2)}`).join(' ');
  return `<path class="report-trend-line ${kind}-trend" d="${path}"/><circle class="${kind}-fill" cx="${last.x}" cy="${last.y}" r="3"/>`;
 }).join('');
}
function renderReportPreferences(){
 $('report-trend-window').value=String(reportPreferences.window);
 $('report-time-off-list').innerHTML=reportPreferences.timeOff.length?reportPreferences.timeOff.map((range,index)=>
  `<li><span>${esc(range.start)}${range.end!==range.start?' – '+esc(range.end):''}</span><button type="button" class="text-button" data-remove-time-off="${index}" aria-label="Remove time off ${esc(range.start)} to ${esc(range.end)}">Remove</button></li>`).join(''):'<li class="muted">No time off marked.</li>';
}
function saveReportPreferences(){
 reportPreferences=reportNormalizePreferences(reportPreferences);
 try{localStorage.setItem('pr-inbox-reporting',JSON.stringify(reportPreferences));$('report-preferences-status').textContent='Saved in this browser.';}
 catch{$('report-preferences-status').textContent='Applied for this session. Browser storage is unavailable; these settings could not be saved.';}
 renderReportPreferences();renderReporting();
}
const costProviders=[{key:'codex',label:'Codex'},{key:'claude',label:'Claude Code'}];
function costMoney(usd){const whole=usd>=1000;return Number(usd||0).toLocaleString('en-US',{style:'currency',currency:'USD',minimumFractionDigits:whole?0:2,maximumFractionDigits:whole?0:2});}
function costModelLabel(id){
 const claude=/^claude-([a-z]+)-(\d+)(?:-(\d{1,2}))?(?:-\d{8})?$/.exec(id||'');
 if(claude)return claude[1][0].toUpperCase()+claude[1].slice(1)+' '+claude[2]+(claude[3]?'.'+claude[3]:'');
 const gpt=/^gpt-([\d.]+)(?:-(.+))?$/.exec(id||'');
 if(gpt)return 'GPT-'+gpt[1]+(gpt[2]?' '+gpt[2][0].toUpperCase()+gpt[2].slice(1):'');
 return id||'Unknown model';
}
function costAxisMaximum(value){
 if(value<=0)return 1;const power=10**Math.floor(Math.log10(value));
 return [1,2,2.5,5,10].map(step=>step*power).find(step=>step>=value);
}
function costAxisLabel(usd){return Number.isInteger(usd)?'$'+usd.toLocaleString('en-US'):costMoney(usd);}
function costSummary(entries,today,days){
 const start=dateShift(today,-(days-1)),previousStart=dateShift(start,-days),previousEnd=dateShift(start,-1);
 const current=entries.filter(entry=>entry.date>=start&&entry.date<=today);
 const previous=entries.filter(entry=>entry.date>=previousStart&&entry.date<=previousEnd);
 const total=list=>list.reduce((sum,entry)=>sum+entry.usd,0);
 const daily=reportPeriods(start,today,'daily').map(({start:day})=>{
  const runs=current.filter(entry=>entry.date===day);
  return {day,runs,total:total(runs),...Object.fromEntries(costProviders.map(({key})=>[key,total(runs.filter(entry=>entry.provider===key))]))};
 });
 const models=new Map();
 for(const entry of current)for(const model of entry.models||[]){
  const key=entry.provider+'|'+model.model+'|'+(model.effort||'');
  const row=models.get(key)||{provider:entry.provider,model:model.model,effort:model.effort||'',usd:0,runs:new Set()};
  row.usd+=model.usd;row.runs.add(entry.run_id);models.set(key,row);
 }
 const updates=current.filter(entry=>entry.mode==='update'),full=current.filter(entry=>entry.mode!=='update');
 const first=entries.map(entry=>entry.date).sort()[0]||'';
 return {start,end:today,days,daily,usd:total(current),count:current.length,
  average:current.length?total(current)/current.length:0,
  fullAverage:full.length?total(full)/full.length:0,updateAverage:updates.length?total(updates)/updates.length:0,updates:updates.length,
  // Compare only when the ledger covers the whole previous window.
  previous:first&&first<=previousStart?total(previous):null,first,
  models:[...models.values()].map(row=>({...row,runs:row.runs.size})).sort((a,b)=>b.usd-a.usd),
  top:[...current].sort((a,b)=>b.usd-a.usd)};
}
function showReporting(show){
 if(show&&!reportingActive)reportScrollToLatest=true;
 reportingActive=show;$('reporting-view').hidden=!show;$('inbox-content').hidden=show;
 $('reporting-tab').setAttribute('aria-pressed',show);
 document.querySelectorAll('[data-view]').forEach(button=>button.setAttribute('aria-pressed',!show&&button.dataset.view===filters.view));
 document.querySelector('.skip').textContent=show?'Skip to reporting':'Skip to pull requests';
 document.querySelector('.skip').href=show?'#reporting-view':'#pr-list';
 renderWorkspaceNavigation();if(show){renderReporting();loadReporting();}
}
async function loadReporting(){
 if(reportLoading)return;reportLoading=true;
 try{const response=await fetch('/api/reporting');if(!response.ok)throw new Error('Could not load activity.');
  reportingData=await response.json();reportLoadError='';renderPicker('reportrepository');renderReporting();
 }catch(error){reportLoadError='Could not read cached reporting data; retrying automatically.';$('report-error').hidden=false;$('report-error').textContent='Could not load activity. Your previous report remains available. Use Sync GitHub to retry.';}
 finally{reportLoading=false;renderSyncStatus();}
}
function reportList(items,empty){return items.length?'<ul class="report-prs">'+items.map(pr=>`<li><a target="_blank" rel="noopener" href="${esc(safeUrl(pr.url))}">${esc(pr.title)}</a><span class="muted">${esc(pr.repository)} #${esc(pr.url.split('/').pop())}</span></li>`).join('')+'</ul>':`<p class="muted">${empty}</p>`;}
function revealLatestReportPeriod(){
 if(!reportingActive||!reportScrollToLatest)return;
 const chart=$('report-content').querySelector('.report-chart');
 if(!chart||!chart.clientWidth)return;
 chart.scrollLeft=chart.scrollWidth;
 reportScrollToLatest=false;
}
function costRunList(entries,empty){
 return entries.length?'<ul class="cost-runs">'+entries.map(entry=>{
  const pr=`${entry.repository} #${entry.number}`,title=(reportingData?.events||[]).find(event=>event.url===entry.pr_url)?.title||state?.prs?.find(pr=>pr.url===entry.pr_url)?.title;
  // Runs on the default model record no model name; the costliest model is the lead.
  const details=[...(title?[pr]:[]),costModelLabel(entry.model||entry.models?.[0]?.model),...(entry.mode==='update'?['Update']:[]),reportDate(entry.date)];
  return `<li><div><a target="_blank" rel="noopener" href="${esc(safeUrl(entry.pr_url))}">${esc(title||pr)}</a><span class="muted">${esc(details.join(' · '))}</span></div><strong>${esc(costMoney(entry.usd))}</strong></li>`;
 }).join('')+'</ul>':`<p class="muted">${empty}</p>`;
}
function costDayLabel(day){
 const parts=costProviders.filter(({key})=>day[key]>0).map(({key,label})=>`${label} ${costMoney(day[key])}`);
 return `${reportDate(day.day)}: ${costMoney(day.total)}, ${day.runs.length} review${day.runs.length===1?'':'s'}${parts.length?' · '+parts.join(' · '):''}`;
}
function renderCostSection(data){
 const days=data.ai_cost_days||30;
 const entries=(data.ai_costs||[]).filter(entry=>matchesSelection(filters.reportRepositoriesOnly,filters.reportRepositoriesExcluded,repo=>repo===entry.repository));
 const summary=costSummary(entries,data.today,days);
 if(!summary.count&&!entries.length)return `<section class="cost-section" aria-labelledby="cost-heading"><h3 id="cost-heading">AI review cost</h3><p class="muted">No priced AI reviews in the last ${days} days. Costs appear here when an in-app review finishes.</p></section>`;
 if(costSelected&&!summary.daily.some(day=>day.day===costSelected))costSelected='';
 const maximum=costAxisMaximum(Math.max(...summary.daily.map(day=>day.total))),selected=summary.daily.find(day=>day.day===costSelected);
 const change=summary.previous===null?`Tracked since ${reportDate(summary.first)}`:`${summary.usd>=summary.previous?'+':'−'}${costMoney(Math.abs(summary.usd-summary.previous))} vs the ${days} days before`;
 const split=summary.updates?`Full ${costMoney(summary.fullAverage)} · update ${costMoney(summary.updateAverage)}`:'All full reviews';
 const bars=summary.daily.map((day,index)=>{
  const height=day.total?Math.max(1.5,day.total/maximum*100):0,segments=costProviders.filter(({key})=>day[key]>0);
  return `<button class="cost-day" data-cost-day="${day.day}" aria-pressed="${day.day===costSelected}" aria-label="${esc(costDayLabel(day))}"><span class="cost-bar"><span class="cost-stack" data-cost-height="${height.toFixed(2)}%">${segments.map(({key})=>`<i class="cost-${key}" data-cost-grow="${day[key].toFixed(4)}"></i>`).join('')}</span></span>${index%7===0&&index<summary.daily.length-3||index===summary.daily.length-1?`<span class="cost-date cost-date-major">${esc(reportDate(day.day))}</span>`:`<span class="cost-date">${new Date(day.day+'T12:00:00Z').getUTCDate()}</span>`}</button>`;
 }).join('');
 const modelRows=summary.models.map(row=>`<li><span class="cost-model"><i class="cost-swatch cost-${esc(row.provider)}" aria-hidden="true"></i>${esc(costModelLabel(row.model))}${row.effort?` <span class="muted">${esc(row.effort)}</span>`:''}</span><span class="cost-share" aria-hidden="true"><i class="cost-${esc(row.provider)}" data-cost-width="${(summary.usd?row.usd/summary.usd*100:0).toFixed(1)}%"></i></span><span class="muted">${row.runs} review${row.runs===1?'':'s'}</span><strong>${esc(costMoney(row.usd))}</strong></li>`).join('');
 return `<section class="cost-section" aria-labelledby="cost-heading">
 <div class="report-chart-heading"><h3 id="cost-heading">AI review cost</h3><span class="muted">${reportDate(summary.start)} – ${reportDate(summary.end)} · ${costProviders.map(({key,label})=>`<span class="cost-key"><i class="cost-swatch cost-${key}" aria-hidden="true"></i>${label}</span>`).join(' ')}</span></div>
 <p class="muted cost-basis">API-price estimates reported by Claude Code and Codex, including sub-agents. What you actually pay depends on your plan.</p>
 <div class="report-metrics"><div><p>Last ${days} days</p><strong>${esc(costMoney(summary.usd))}</strong><span>${esc(change)}</span></div><div><p>AI reviews</p><strong>${summary.count}</strong><span>${summary.updates?`${summary.updates} were updates`:'No update reviews'}</span></div><div><p>Average per review</p><strong>${esc(costMoney(summary.average))}</strong><span>${esc(split)}</span></div></div>
 <div class="cost-chart"><div class="cost-axis" aria-hidden="true"><span>${esc(costAxisLabel(maximum))}</span><span>${esc(costAxisLabel(maximum/2))}</span><span>$0</span></div><div class="cost-plot" role="group" aria-label="Daily AI review cost. Select a day to see its reviews.">${bars}</div><div class="cost-tooltip" role="presentation" hidden></div></div>
 <div class="report-detail-columns cost-detail"><div><h4>By model</h4><ul class="cost-models">${modelRows||'<li class="muted">No model usage recorded.</li>'}</ul></div>
 <div aria-live="polite"><div class="cost-detail-heading"><h4>${selected?`${esc(reportDate(selected.day))} <span class="count">${esc(costMoney(selected.total))}</span>`:'Most expensive reviews'}</h4>${selected?'<button type="button" class="text-button" data-cost-day="">Show most expensive</button>':''}</div>
 ${selected?costRunList([...selected.runs].sort((a,b)=>b.usd-a.usd),'No AI reviews finished on this day.'):costRunList(summary.top.slice(0,5),'No AI reviews in this period.')}</div></div>
 </section>`;
}
// The dashboard CSP forbids style attributes; CSSOM writes are allowed.
function applyCostGeometry(root){
 for(const element of root.querySelectorAll('[data-cost-height]'))element.style.height=element.dataset.costHeight;
 for(const element of root.querySelectorAll('[data-cost-grow]'))element.style.flexGrow=element.dataset.costGrow;
 for(const element of root.querySelectorAll('[data-cost-width]'))element.style.width=element.dataset.costWidth;
}
function showCostTooltip(button){
 const chart=button.closest('.cost-chart'),tip=chart?.querySelector('.cost-tooltip');
 const day=tip&&costSummary(reportingData.ai_costs.filter(entry=>matchesSelection(filters.reportRepositoriesOnly,filters.reportRepositoriesExcluded,repo=>repo===entry.repository)),reportingData.today,reportingData.ai_cost_days||30).daily.find(item=>item.day===button.dataset.costDay);
 if(!day)return;
 tip.innerHTML=`<strong>${esc(reportDate(day.day))} · ${esc(costMoney(day.total))}</strong>${costProviders.filter(({key})=>day[key]>0).map(({key,label})=>`<span><i class="cost-swatch cost-${key}" aria-hidden="true"></i>${label} ${esc(costMoney(day[key]))}</span>`).join('')}<span class="muted">${day.runs.length} review${day.runs.length===1?'':'s'}</span>`;
 tip.hidden=false;
 const area=chart.getBoundingClientRect(),bar=button.getBoundingClientRect();
 const top=button.querySelector('.cost-stack').getBoundingClientRect().top-area.top-tip.offsetHeight-8;
 // Tall bars leave no room above; sit beside the bar instead of covering it.
 const beside=bar.right-area.left+8+tip.offsetWidth<=area.width?bar.right-area.left+8:bar.left-area.left-8-tip.offsetWidth;
 tip.style.left=(top>=0?Math.min(Math.max(bar.left-area.left+bar.width/2-tip.offsetWidth/2,0),area.width-tip.offsetWidth):beside)+'px';
 tip.style.top=Math.max(0,top)+'px';
}
function hideCostTooltip(){$('report-content').querySelector('.cost-tooltip')?.setAttribute('hidden','');}
function renderReporting(){
 const data=reportingData;if(!data)return;
 const running=data.refresh?.status==='running';
 const error=data.refresh?.status==='failed'?data.refresh.message:'';
 $('report-error').hidden=!error;$('report-error').textContent=error;
 const stale=data.range_end&&data.range_end<data.today;
 $('report-freshness').textContent=running?'Fetching your activity from GitHub…':data.updated_at?`History refreshed ${since(data.updated_at)} · ${data.login}${stale?' · Sync to include newer days.':''}`:'Sync GitHub to see this report.';
 if(!data.updated_at){$('report-content').innerHTML='<div class="empty"><h3>Your work, day by day</h3><p class="muted">Sync GitHub to see four complete weeks and this week so far.</p></div>'+renderCostSection(data);applyCostGeometry($('report-content'));return;}
 const signature=JSON.stringify([data,reportInterval,reportSelected,costSelected,filters.reportRepositoriesOnly,filters.reportRepositoriesExcluded,reportPreferences]);
 if(signature===reportSignature){revealLatestReportPeriod();drawReportTrend();return;}reportSignature=signature;
 const oldChart=$('report-content').querySelector('.report-chart'),oldScroll=oldChart?.scrollLeft||0;
 const events=data.events.filter(event=>matchesSelection(filters.reportRepositoriesOnly,filters.reportRepositoriesExcluded,repo=>repo===event.repository));
 const today=data.today,end=data.range_end<today?data.range_end:today,start=data.range_start;
 const monday=weekStart(today),lastStart=dateShift(monday,-7),lastEnd=dateShift(monday,-1),prevStart=dateShift(monday,-14),prevEnd=dateShift(monday,-8);
 const last=reportCounts(events,lastStart,lastEnd),previous=reportCounts(events,prevStart,prevEnd);
 const comparisonAvailable=start<=prevStart&&end>=lastEnd;
 function delta(kind){if(!comparisonAvailable)return 'Sync GitHub for a full comparison.';const n=last[kind].length-previous[kind].length;return (n===0?'No change':`${n>0?'+':''}${n}`)+' vs the week before';}
 const periods=reportPeriods(start,end,reportInterval);
 if(!reportSelected)reportSelected=dateShift(today,-1);
 let chosen=periods.find(period=>reportSelected>=period.start&&reportSelected<=period.end)||periods.at(-1);
 reportSelected=reportSelected<start||reportSelected>end?chosen.start:reportSelected;
 const bars=periods.map(period=>({...period,...reportCounts(events,period.start,period.end)}));
 reportTrendPoints=reportTrends(events,start,end,today,reportPreferences);
 const daily=reportInterval==='daily',latestTrend=reportTrendPoints.filter(point=>point.average).at(-1);
 const chosenTrend=reportTrendPoints.find(point=>point.day===chosen.start);
 const maximum=Math.max(1,...bars.flatMap(bar=>[bar.review.length,bar.merge.length]));
 const selected=reportCounts(events,chosen.start,chosen.end),yesterday=dateShift(today,-1);
 const title=reportInterval==='weekly'?`Week of ${reportDate(chosen.start)}`:chosen.start===yesterday?'Yesterday · '+reportDate(chosen.start):reportDate(chosen.start);
 const inProgress=chosen.end>=today;
 $('report-yesterday').disabled=yesterday<start||yesterday>end;
 $('report-daily').setAttribute('aria-pressed',reportInterval==='daily');$('report-weekly').setAttribute('aria-pressed',reportInterval==='weekly');
 $('report-content').innerHTML=`<div class="report-metrics"><div><p>PRs reviewed · last complete week</p><strong>${comparisonAvailable?last.review.length:'—'}</strong><span>${esc(delta('review'))}</span></div><div><p>Your PRs merged · last complete week</p><strong>${comparisonAvailable?last.merge.length:'—'}</strong><span>${esc(delta('merge'))}</span></div></div>
 <section class="report-chart-section${daily?' report-with-trend':''}" aria-label="Activity chart"><div class="report-chart-heading"><h3>${daily?'Daily':'Weekly'} activity</h3><span class="muted">${reportDate(start)} – ${reportDate(end)} · <span class="review-key">● Reviewed</span> <span class="merge-key">● Yours merged</span></span></div><p class="muted">Select a ${daily?'day':'week'} to see its PRs. ${daily?'Shaded days are weekends or time off.':'This week is still in progress.'}</p>
 ${daily?`<div class="report-trend-legend"><span><i class="review-trend"></i>Reviewed trend</span><span><i class="merge-trend"></i>Merged trend</span><span class="muted">${reportPreferences.window} workdays</span></div><p class="report-trend-summary">${esc(reportTrendDescription(latestTrend))}${latestTrend?' Through '+esc(reportDate(latestTrend.day))+'.':''}</p>`:''}
 <div class="report-chart"><div class="report-chart-track" data-maximum="${maximum}">${bars.map((bar,index)=>{
  const selected=bar.start===chosen.start,reviewHeight=bar.review.length/maximum*84,mergeHeight=bar.merge.length/maximum*84;
  const point=daily?reportTrendPoints[index]:null,off=point?.off;
  const trendLabel=point?.average?' · '+reportTrendDescription(point):'';
  return `<button class="report-bar${off?' report-day-off':''}" data-report-period="${bar.start}" aria-pressed="${selected}" aria-label="${daily?'':'Week of '}${reportDate(bar.start)}: ${bar.review.length} reviewed, ${bar.merge.length} yours merged${bar.end>=today?', in progress':''}${off?' · '+off:''}${esc(trendLabel)}"><span class="report-bar-count"><span class="review-key">${bar.review.length}</span><span class="merge-key">${bar.merge.length}</span></span><svg viewBox="0 0 40 90" preserveAspectRatio="none" aria-hidden="true"><rect class="review-fill" x="5" y="${90-reviewHeight}" width="13" height="${reviewHeight}" rx="2"/><rect class="merge-fill" x="22" y="${90-mergeHeight}" width="13" height="${mergeHeight}" rx="2"/></svg><span class="report-bar-date">${!daily||index%7===0||selected?esc(reportDate(bar.start)):new Date(bar.start+'T12:00:00Z').getUTCDate()}</span></button>`;
 }).join('')}${daily?'<svg class="report-trend-overlay" aria-hidden="true"></svg>':''}</div></div></section>
 <section class="report-detail" aria-live="polite"><div class="report-detail-heading"><h3>${esc(title)}</h3>${inProgress?'<span class="chip">In progress</span>':''}</div>${daily?`<p class="report-selected-trend muted">${chosen.start>=end?'Trend excludes this incomplete day.':esc(reportTrendDescription(chosenTrend))}${chosenTrend?.off&&!chosenTrend.average?' '+esc(chosenTrend.off)+' excluded.':''}</p>`:''}<div class="report-detail-columns"><div><h4>Reviewed <span class="count">${selected.review.length}</span></h4>${reportList(selected.review,'No PR reviews in this period.')}</div><div><h4>Your PRs merged <span class="count">${selected.merge.length}</span></h4>${reportList(selected.merge,'No authored PRs merged in this period.')}</div></div></section>${renderCostSection(data)}`;
 reportSignature=JSON.stringify([data,reportInterval,reportSelected,costSelected,filters.reportRepositoriesOnly,filters.reportRepositoriesExcluded,reportPreferences]);
 $('report-content').querySelector('.report-chart-track').style.minWidth=`${bars.length*45-5}px`;
 applyCostGeometry($('report-content'));
 reportChartObserver?.disconnect();
 if(daily){reportChartObserver=new ResizeObserver(drawReportTrend);reportChartObserver.observe($('report-content').querySelector('.report-chart-track'));drawReportTrend();}
 const chart=$('report-content').querySelector('.report-chart'),selectedBar=chart?.querySelector('[aria-pressed=true]');
 if(chart){chart.scrollLeft=oldScroll;if(selectedBar){const bar=selectedBar.getBoundingClientRect(),area=chart.getBoundingClientRect();if(bar.left<area.left||bar.right>area.right)chart.scrollLeft+=bar.left-area.left-area.width/2+bar.width/2;}}
 revealLatestReportPeriod();
}
$('reporting-tab').addEventListener('click',()=>showReporting(true));

for(const interval of ['daily','weekly'])$('report-'+interval).addEventListener('click',()=>{reportInterval=interval;renderReporting();});
$('report-yesterday').addEventListener('click',()=>{reportInterval='daily';reportSelected=dateShift(reportingData.today,-1);renderReporting();});
$('report-content').addEventListener('click',event=>{
 const day=event.target.closest('[data-cost-day]');
 if(day){const key=day.dataset.costDay;costSelected=key===costSelected?'':key;renderReporting();if(key)$('report-content').querySelector(`.cost-day[data-cost-day="${key}"]`)?.focus({preventScroll:true});return;}
});
for(const kind of ['mouseover','focusin'])$('report-content').addEventListener(kind,event=>{const button=event.target.closest('.cost-day');if(button)showCostTooltip(button);});
for(const kind of ['mouseout','focusout'])$('report-content').addEventListener(kind,event=>{if(event.target.closest('.cost-day')&&!event.relatedTarget?.closest?.('.cost-day'))hideCostTooltip();});
$('report-content').addEventListener('click',event=>{const button=event.target.closest('[data-report-period]');if(button){reportSelected=button.dataset.reportPeriod;renderReporting();$('report-content').querySelector(`[data-report-period="${reportSelected}"]`)?.focus({preventScroll:true});}});
$('report-trend-window').addEventListener('change',event=>{reportPreferences.window=Number(event.target.value);saveReportPreferences();});
$('report-time-off-start').addEventListener('change',()=>{
 const start=$('report-time-off-start').value,end=$('report-time-off-end');
 if(!end.value||end.value<start)end.value=start;
 end.setCustomValidity('');
});
$('report-time-off-end').addEventListener('input',event=>event.target.setCustomValidity(''));
$('report-time-off-form').addEventListener('submit',event=>{
 event.preventDefault();
 const start=$('report-time-off-start').value,end=$('report-time-off-end').value;
 if(!reportValidDate(start)||!reportValidDate(end)||end<start){$('report-time-off-end').setCustomValidity('Choose an end date on or after the start date.');$('report-time-off-end').reportValidity();return;}
 reportPreferences.timeOff.push({start,end});saveReportPreferences();event.target.reset();
});
$('report-time-off-list').addEventListener('click',event=>{
 const button=event.target.closest('[data-remove-time-off]');if(!button)return;
 const index=Number(button.dataset.removeTimeOff);
 reportPreferences.timeOff.splice(index,1);saveReportPreferences();
 const remaining=$('report-time-off-list').querySelectorAll('button');
 (remaining[Math.min(index,remaining.length-1)]||$('report-time-off-start')).focus();
});
renderReportPreferences();
