'use strict';
let reportSignature='',reportInterval='daily',reportSelected='',reportLoading=false,reportTimer;
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
function showReporting(show){
 reportingActive=show;$('reporting-view').hidden=!show;$('inbox-content').hidden=show;
 document.querySelector('.workspace-controls').hidden=show;document.querySelector('.sync-controls').hidden=show;
 $('reporting-tab').setAttribute('aria-pressed',show);
 document.querySelectorAll('[data-view]').forEach(button=>button.setAttribute('aria-pressed',!show&&button.dataset.view===filters.view));
 document.querySelector('.skip').textContent=show?'Skip to reporting':'Skip to pull requests';
 document.querySelector('.skip').href=show?'#reporting-view':'#pr-list';
 if(show)loadReporting();else clearTimeout(reportTimer);
}
async function loadReporting(){
 if(reportLoading)return;reportLoading=true;
 try{const response=await fetch('/api/reporting');if(!response.ok)throw new Error('Could not load activity.');
  reportingData=await response.json();renderPicker('reportrepository');renderReporting();
 }catch(error){$('report-error').hidden=false;$('report-error').textContent='Could not load activity. Your previous report remains available. Retry Refresh history.';}
 finally{reportLoading=false;clearTimeout(reportTimer);if(reportingActive)reportTimer=setTimeout(loadReporting,5000);}
}
function reportList(items,empty){return items.length?'<ul class="report-prs">'+items.map(pr=>`<li><a target="_blank" rel="noopener" href="${esc(safeUrl(pr.url))}">${esc(pr.title)}</a><span class="muted">${esc(pr.repository)} #${esc(pr.url.split('/').pop())}</span></li>`).join('')+'</ul>':`<p class="muted">${empty}</p>`;}
function renderReporting(){
 const data=reportingData;if(!data)return;
 const running=data.refresh?.status==='running';$('report-refresh').disabled=running;
 $('report-refresh').textContent=running?'Refreshing…':data.updated_at?'Refresh history':'Load history';
 const error=data.refresh?.status==='failed'?data.refresh.message:'';
 $('report-error').hidden=!error;$('report-error').textContent=error;
 const stale=data.range_end&&data.range_end<data.today;
 $('report-freshness').textContent=running?'Fetching your activity from GitHub…':data.updated_at?`History refreshed ${since(data.updated_at)} · ${data.login}${stale?' · Refresh to include newer days.':''}`:'Load your recent GitHub history to see this report.';
 if(!data.updated_at){$('report-content').innerHTML='<div class="empty"><h3>Your work, day by day</h3><p class="muted">Load history to see four complete weeks and this week so far.</p></div>';return;}
 const signature=JSON.stringify([data,reportInterval,reportSelected,filters.reportRepositoriesOnly,filters.reportRepositoriesExcluded]);
 if(signature===reportSignature)return;reportSignature=signature;
 const oldChart=$('report-content').querySelector('.report-chart'),oldScroll=oldChart?.scrollLeft||0;
 const events=data.events.filter(event=>matchesSelection(filters.reportRepositoriesOnly,filters.reportRepositoriesExcluded,repo=>repo===event.repository));
 const today=data.today,end=data.range_end<today?data.range_end:today,start=data.range_start;
 const monday=weekStart(today),lastStart=dateShift(monday,-7),lastEnd=dateShift(monday,-1),prevStart=dateShift(monday,-14),prevEnd=dateShift(monday,-8);
 const last=reportCounts(events,lastStart,lastEnd),previous=reportCounts(events,prevStart,prevEnd);
 const comparisonAvailable=start<=prevStart&&end>=lastEnd;
 function delta(kind){if(!comparisonAvailable)return 'Refresh history for a full comparison.';const n=last[kind].length-previous[kind].length;return (n===0?'No change':`${n>0?'+':''}${n}`)+' vs the week before';}
 const periods=reportPeriods(start,end,reportInterval);
 if(!reportSelected)reportSelected=dateShift(today,-1);
 let chosen=periods.find(period=>reportSelected>=period.start&&reportSelected<=period.end)||periods.at(-1);
 reportSelected=reportSelected<start||reportSelected>end?chosen.start:reportSelected;
 const bars=periods.map(period=>({...period,...reportCounts(events,period.start,period.end)}));
 const maximum=Math.max(1,...bars.flatMap(bar=>[bar.review.length,bar.merge.length]));
 const selected=reportCounts(events,chosen.start,chosen.end),yesterday=dateShift(today,-1);
 const title=reportInterval==='weekly'?`Week of ${reportDate(chosen.start)}`:chosen.start===yesterday?'Yesterday · '+reportDate(chosen.start):reportDate(chosen.start);
 const inProgress=chosen.end>=today;
 $('report-yesterday').disabled=yesterday<start||yesterday>end;
 $('report-daily').setAttribute('aria-pressed',reportInterval==='daily');$('report-weekly').setAttribute('aria-pressed',reportInterval==='weekly');
 $('report-content').innerHTML=`<div class="report-metrics"><div><p>PRs reviewed · last complete week</p><strong>${comparisonAvailable?last.review.length:'—'}</strong><span>${esc(delta('review'))}</span></div><div><p>Your PRs merged · last complete week</p><strong>${comparisonAvailable?last.merge.length:'—'}</strong><span>${esc(delta('merge'))}</span></div></div>
 <section class="report-chart-section" aria-label="Activity chart"><div class="report-chart-heading"><h3>${reportInterval==='weekly'?'Weekly':'Daily'} activity</h3><span class="muted">${reportDate(start)} – ${reportDate(end)} · <span class="review-key">● Reviewed</span> <span class="merge-key">● Yours merged</span></span></div><p class="muted">Select a ${reportInterval==='weekly'?'week':'day'} to see its PRs. ${reportInterval==='weekly'?'This week is still in progress.':''}</p><div class="report-chart">${bars.map((bar,index)=>{
  const selected=bar.start===chosen.start,reviewHeight=bar.review.length/maximum*84,mergeHeight=bar.merge.length/maximum*84;
  return `<button class="report-bar" data-report-period="${bar.start}" aria-pressed="${selected}" aria-label="${reportInterval==='weekly'?'Week of ':''}${reportDate(bar.start)}: ${bar.review.length} reviewed, ${bar.merge.length} yours merged${bar.end>=today?', in progress':''}"><span class="report-bar-count">${bar.review.length} / ${bar.merge.length}</span><svg viewBox="0 0 40 90" aria-hidden="true"><rect class="review-fill" x="5" y="${90-reviewHeight}" width="13" height="${reviewHeight}" rx="2"/><rect class="merge-fill" x="22" y="${90-mergeHeight}" width="13" height="${mergeHeight}" rx="2"/></svg><span class="report-bar-date">${reportInterval==='weekly'||index%7===0||selected?esc(reportDate(bar.start)):new Date(bar.start+'T12:00:00Z').getUTCDate()}</span></button>`;
 }).join('')}</div></section>
 <section class="report-detail" aria-live="polite"><div class="report-detail-heading"><h3>${esc(title)}</h3>${inProgress?'<span class="chip">In progress</span>':''}</div><div class="report-detail-columns"><div><h4>Reviewed <span class="count">${selected.review.length}</span></h4>${reportList(selected.review,'No PR reviews in this period.')}</div><div><h4>Your PRs merged <span class="count">${selected.merge.length}</span></h4>${reportList(selected.merge,'No authored PRs merged in this period.')}</div></div></section>`;
 reportSignature=JSON.stringify([data,reportInterval,reportSelected,filters.reportRepositoriesOnly,filters.reportRepositoriesExcluded]);
 const chart=$('report-content').querySelector('.report-chart'),selectedBar=chart?.querySelector('[aria-pressed=true]');
 if(chart){chart.scrollLeft=oldScroll;if(selectedBar){const bar=selectedBar.getBoundingClientRect(),area=chart.getBoundingClientRect();if(bar.left<area.left||bar.right>area.right)chart.scrollLeft+=bar.left-area.left-area.width/2+bar.width/2;}}
}
$('reporting-tab').addEventListener('click',()=>showReporting(true));
$('report-refresh').addEventListener('click',async()=>{try{$('report-refresh').disabled=true;await post('/refresh-reporting');await loadReporting();}catch(error){$('report-refresh').disabled=false;$('report-error').hidden=false;$('report-error').textContent=error.message;}});
for(const interval of ['daily','weekly'])$('report-'+interval).addEventListener('click',()=>{reportInterval=interval;renderReporting();});
$('report-yesterday').addEventListener('click',()=>{reportInterval='daily';reportSelected=dateShift(reportingData.today,-1);renderReporting();});
$('report-content').addEventListener('click',event=>{const button=event.target.closest('[data-report-period]');if(button){reportSelected=button.dataset.reportPeriod;renderReporting();$('report-content').querySelector(`[data-report-period="${reportSelected}"]`)?.focus({preventScroll:true});}});
