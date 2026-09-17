'use strict';
let reportSignature='',reportInterval='daily',reportSelected='',reportLoading=false,reportLoadError='',reportScrollToLatest=false;
let reportPreferences={window:10,timeOff:[]},reportTrendPoints=[],reportChartObserver=null;
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
function renderReporting(){
 const data=reportingData;if(!data)return;
 const running=data.refresh?.status==='running';
 const error=data.refresh?.status==='failed'?data.refresh.message:'';
 $('report-error').hidden=!error;$('report-error').textContent=error;
 const stale=data.range_end&&data.range_end<data.today;
 $('report-freshness').textContent=running?'Fetching your activity from GitHub…':data.updated_at?`History refreshed ${since(data.updated_at)} · ${data.login}${stale?' · Sync to include newer days.':''}`:'Sync GitHub to see this report.';
 if(!data.updated_at){$('report-content').innerHTML='<div class="empty"><h3>Your work, day by day</h3><p class="muted">Sync GitHub to see four complete weeks and this week so far.</p></div>';return;}
 const signature=JSON.stringify([data,reportInterval,reportSelected,filters.reportRepositoriesOnly,filters.reportRepositoriesExcluded,reportPreferences]);
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
 <section class="report-detail" aria-live="polite"><div class="report-detail-heading"><h3>${esc(title)}</h3>${inProgress?'<span class="chip">In progress</span>':''}</div>${daily?`<p class="report-selected-trend muted">${chosen.start>=end?'Trend excludes this incomplete day.':esc(reportTrendDescription(chosenTrend))}${chosenTrend?.off&&!chosenTrend.average?' '+esc(chosenTrend.off)+' excluded.':''}</p>`:''}<div class="report-detail-columns"><div><h4>Reviewed <span class="count">${selected.review.length}</span></h4>${reportList(selected.review,'No PR reviews in this period.')}</div><div><h4>Your PRs merged <span class="count">${selected.merge.length}</span></h4>${reportList(selected.merge,'No authored PRs merged in this period.')}</div></div></section>`;
 reportSignature=JSON.stringify([data,reportInterval,reportSelected,filters.reportRepositoriesOnly,filters.reportRepositoriesExcluded,reportPreferences]);
 $('report-content').querySelector('.report-chart-track').style.minWidth=`${bars.length*45-5}px`;
 reportChartObserver?.disconnect();
 if(daily){reportChartObserver=new ResizeObserver(drawReportTrend);reportChartObserver.observe($('report-content').querySelector('.report-chart-track'));drawReportTrend();}
 const chart=$('report-content').querySelector('.report-chart'),selectedBar=chart?.querySelector('[aria-pressed=true]');
 if(chart){chart.scrollLeft=oldScroll;if(selectedBar){const bar=selectedBar.getBoundingClientRect(),area=chart.getBoundingClientRect();if(bar.left<area.left||bar.right>area.right)chart.scrollLeft+=bar.left-area.left-area.width/2+bar.width/2;}}
 revealLatestReportPeriod();
}
$('reporting-tab').addEventListener('click',()=>showReporting(true));

for(const interval of ['daily','weekly'])$('report-'+interval).addEventListener('click',()=>{reportInterval=interval;renderReporting();});
$('report-yesterday').addEventListener('click',()=>{reportInterval='daily';reportSelected=dateShift(reportingData.today,-1);renderReporting();});
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
