const path=require('node:path'),fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const s=fs.readFileSync(path.join(__dirname,'../../assets/reporting.js'),'utf8');const c=vm.createContext({});vm.runInContext(s.slice(0,s.indexOf('function showReporting(')),c);
const e=[{date:'2026-09-07',kind:'review',url:'a'},{date:'2026-09-07',kind:'review',url:'a'},{date:'2026-09-08',kind:'review',url:'a'},{date:'2026-09-09',kind:'merge',url:'b'}];
assert.equal(c.reportCounts(e,'2026-09-07','2026-09-07').review.length,1);
assert.equal(c.reportCounts(e,'2026-09-07','2026-09-13').review.length,1);
assert.equal(c.reportCounts(e,'2026-09-07','2026-09-13').merge.length,1);
assert.equal(c.reportCounts(e,'2026-09-10','2026-09-10').review.length,0);
assert.equal(c.reportPeriods('2026-08-10','2026-09-10','weekly').length,5);
assert.equal(c.reportPeriods('2026-08-10','2026-09-10','daily').length,32);
assert.equal(vm.runInContext("weekStart('2026-09-06')",c),'2026-08-31');
const activity=[];
const dates=['2026-09-07','2026-09-08','2026-09-09','2026-09-10','2026-09-11','2026-09-14','2026-09-15','2026-09-16','2026-09-17','2026-09-18'];
[1,0,3,4,2,8,1,0,6,5].forEach((n,i)=>{
 for(let j=0;j<n;j++)activity.push({date:dates[i],kind:'review',url:'review-'+j});
 activity.push({date:dates[i],kind:'merge',url:'merge-'+i});
});
activity.push({...activity[0]}); // duplicate submissions are still one PR that day
for(const date of ['2026-09-12','2026-09-13','2026-09-21'])for(let i=0;i<100;i++)activity.push({date,kind:'review',url:'extra-'+i});
const preferences={window:5,timeOff:[]};
const trend=c.reportTrends(activity,'2026-09-07','2026-09-21','2026-09-21',preferences);
const at=(points,date)=>points.find(point=>point.day===date);
assert.equal(at(trend,'2026-09-10').average,null,'wait for the whole window');
assert.equal(at(trend,'2026-09-11').average.review,2,'include zero weekdays and deduplicate per day');
assert.equal(at(trend,'2026-09-11').average.merge,1,'merge rate is independent');
assert.equal(at(trend,'2026-09-13').average.review,2,'weekend events do not affect the trend');
assert.equal(at(trend,'2026-09-14').average.review,3.4,'roll out the oldest workday');
assert.equal(at(trend,'2026-09-18').average.review,4);
assert.equal(at(trend,'2026-09-21').average,null,'exclude today even when it has activity');
const ten=c.reportTrends(activity,'2026-09-07','2026-09-21','2026-09-21',{window:10,timeOff:[]});
assert.equal(at(ten,'2026-09-17').average,null);
assert.equal(at(ten,'2026-09-18').average.review,3,'10-day setting averages ten daily counts, not distinct PRs across the window');
const leave=c.reportTrends(activity,'2026-09-07','2026-09-21','2026-09-21',{window:5,timeOff:[{start:'2026-09-15',end:'2026-09-15'}]});
assert.equal(at(leave,'2026-09-15').average.review,3.4,'time off holds the previous rate');
assert.equal(at(leave,'2026-09-18').average.review,4.2,'reach further back to collect five workdays');
const vacation=c.reportTrends(activity,'2026-09-07','2026-09-21','2026-09-21',{window:5,timeOff:[{start:'2026-09-07',end:'2026-09-18'}]});
assert.ok(vacation.every(point=>point.average===null),'never invent a rate with insufficient workdays');
const stale=c.reportTrends(activity,'2026-09-07','2026-09-18','2026-09-21',preferences);
assert.equal(at(stale,'2026-09-18').average,null,'last cached day may be incomplete after midnight');
assert.equal(at(stale,'2026-09-17').average.review,3.4);
const empty=c.reportTrends([],'2026-09-07','2026-09-21','2026-09-21',preferences);
assert.equal(at(empty,'2026-09-18').average.review,0,'no activity is a real zero once history is complete');
assert.equal(c.reportDayOff('2026-10-25',[]),'Weekend','DST Sunday is still a weekend');
assert.equal(c.reportDayOff('2026-10-26',[]),'');
assert.equal(c.reportValidDate('2026-02-30'),false);
assert.equal(c.reportValidDate('2028-02-29'),true);
const normalized=c.reportNormalizePreferences({window:7,timeOff:[null,{start:'bad',end:'bad'},{start:'2026-09-20',end:'2026-09-10'},{start:'2026-09-14',end:'2026-09-18'},{start:'2026-09-10',end:'2026-09-15'}]});
assert.equal(normalized.window,10);
assert.equal(JSON.stringify(normalized.timeOff),JSON.stringify([{start:'2026-09-10',end:'2026-09-18'}]));

// AI review cost: a 30-day window, provider split, model totals and a fair comparison.
const costs=[
 {run_id:'a',date:'2026-09-29',provider:'claude',mode:'full',usd:8,models:[{model:'claude-opus-5-5',usd:7.5},{model:'claude-sonnet-5-5',usd:.5}]},
 {run_id:'b',date:'2026-09-29',provider:'codex',mode:'update',usd:4,models:[{model:'gpt-6-astra',effort:'high',usd:4}]},
 {run_id:'c',date:'2026-09-01',provider:'claude',mode:'full',usd:2,models:[{model:'claude-opus-5-5',usd:2}]},
 {run_id:'old',date:'2026-08-02',provider:'claude',mode:'full',usd:100,models:[{model:'claude-opus-5-5',usd:100}]}];
const cost=c.costSummary(costs,'2026-09-30',30);
assert.equal(cost.start,'2026-09-01');assert.equal(cost.daily.length,30);
assert.equal(cost.usd,14);assert.equal(cost.count,3);assert.equal(cost.updates,1);assert.equal(cost.previous,100,'full previous window is covered');
const day=cost.daily.find(item=>item.day==='2026-09-29');assert.equal(day.claude,8);assert.equal(day.codex,4);assert.equal(day.runs.length,2);
assert.equal(JSON.stringify(cost.models.map(row=>[row.model,row.usd,row.runs])),JSON.stringify([['claude-opus-5-5',9.5,2],['gpt-6-astra',4,1],['claude-sonnet-5-5',.5,1]]));
assert.equal(cost.top.map(entry=>entry.run_id).join(),'a,b,c');
assert.equal(c.costSummary(costs.slice(0,3),'2026-09-30',30).previous,null,'no comparison before tracking covers the previous window');
assert.equal(c.costModelLabel('claude-haiku-4-5-20251001'),'Haiku 4.5');assert.equal(c.costModelLabel('gpt-5.6-sol'),'GPT-5.6 Sol');
assert.equal(c.costAxisMaximum(142.68),200);assert.equal(c.costMoney(1234.5),'$1,235');assert.equal(c.costMoney(3.456),'$3.46');
console.log('Reporting aggregation and trend checks passed: windows, zero days, weekends, time off, incomplete history, duplicate reviews, date validation, DST and AI review cost.');
