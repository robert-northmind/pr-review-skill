'use strict';
const {spawn}=require('node:child_process'),{once}=require('node:events'),path=require('node:path'),fs=require('node:fs'),assert=require('node:assert/strict');
const {chromium}=require(process.env.PR_REVIEW_PLAYWRIGHT_MODULE||'playwright');
(async()=>{
 const fixture=spawn(process.env.PYTHON||'python3',[path.join(__dirname,'../fixtures/workspace_browser_fixture.py')],{stdio:['ignore','pipe','inherit']});
 let browser;
 try{
  const [chunk]=await Promise.race([once(fixture.stdout,'data'),once(fixture,'exit').then(([code])=>{throw new Error(`Fixture exited before serving (status ${code}).`);})]),url=chunk.toString().trim();
  browser=await chromium.launch({headless:true,channel:process.env.PR_REVIEW_BROWSER_CHANNEL||'chrome'});
  const page=await browser.newPage({viewport:{width:1440,height:1100}}),errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  page.on('console',message=>{if(message.type()==='error')errors.push(message.text());});
  const data={login:'example-reviewer',range_start:'2026-08-24',range_end:'2026-09-21',today:'2026-09-21',timezone:'Europe/Berlin',updated_at:'2026-09-21T09:00:00Z',refresh:{status:'idle'},events:[]};
  for(let i=0;i<29;i++){
   const date=new Date(Date.UTC(2026,7,24+i)).toISOString().slice(0,10),week=Math.floor(i/7);
   for(const [kind,n] of [['review',i%7<5?(i%5===1?0:3+week+i%3):0],['merge',i%7<5?1+week%2:0]]){
    for(let j=0;j<n;j++)data.events.push({date,kind,url:`https://github.com/example/repo/pull/${i*20+j}`,repository:'example/repo',title:`Example ${kind} ${i*20+j}`});
   }
  }
  await page.route('**/api/reporting',route=>route.fulfill({json:data}));
  await page.goto(url);await page.click('#reporting-tab');
  await page.waitForSelector('.report-trend-overlay path');
  assert.equal(await page.inputValue('#report-trend-window'),'10');
  assert.equal(await page.locator('.report-trend-overlay path').count(),2);
  assert.match(await page.locator('.report-trend-summary').textContent(),/10-workday average/);
  const original=await page.locator('.report-trend-overlay path').first().getAttribute('d');
  const totals=await page.locator('.report-metrics').textContent();
  const bars=await page.locator('.report-bar-count').allTextContents();
  await page.selectOption('#report-trend-window','5');
  assert.notEqual(await page.locator('.report-trend-overlay path').first().getAttribute('d'),original);
  const five=await page.locator('.report-trend-summary').textContent();
  await page.click('.report-time-off summary');
  await page.fill('#report-time-off-start','2026-09-17');
  await page.fill('#report-time-off-end','2026-09-18');
  await page.click('#report-time-off-form button');
  assert.notEqual(await page.locator('.report-trend-summary').textContent(),five);
  assert.match(await page.locator('#report-preferences-status').textContent(),/Saved/);
  assert.equal(await page.locator('.report-metrics').textContent(),totals);
  assert.deepEqual(await page.locator('.report-bar-count').allTextContents(),bars);
  await page.locator('[data-report-period="2026-09-18"]').click();
  assert.match(await page.locator('.report-selected-trend').textContent(),/Time off excluded/);
  assert.ok(await page.locator('.report-prs a').count()>0,'excluded activity remains available in drill-down');
  await page.reload();await page.click('#reporting-tab');await page.waitForSelector('.report-trend-overlay path');
  assert.equal(await page.inputValue('#report-trend-window'),'5');
  await page.click('.report-time-off summary');
  assert.match(await page.locator('#report-time-off-list').textContent(),/2026-09-17.*2026-09-18/);
  await page.locator('[data-remove-time-off]').click();
  assert.equal(await page.locator('.report-trend-summary').textContent(),five);
  // Invalid ranges cannot be saved; a corrected range and overlapping ranges can.
  await page.fill('#report-time-off-start','2026-09-17');await page.fill('#report-time-off-end','2026-09-15');await page.click('#report-time-off-form button');
  assert.equal(await page.locator('#report-time-off-end').evaluate(el=>el.validity.valid),false);
  assert.equal(await page.locator('[data-remove-time-off]').count(),0);
  await page.fill('#report-time-off-end','2026-09-18');await page.click('#report-time-off-form button');
  await page.fill('#report-time-off-start','2026-09-16');await page.fill('#report-time-off-end','2026-09-17');await page.click('#report-time-off-form button');
  assert.equal(await page.locator('[data-remove-time-off]').count(),1);
  assert.match(await page.locator('#report-time-off-list').textContent(),/2026-09-16.*2026-09-18/);
  await page.locator('[data-remove-time-off]').click();
  await page.click('.report-time-off summary');
  await page.click('#report-weekly');assert.equal(await page.locator('.report-trend-overlay').count(),0);
  assert.equal(await page.locator('.report-metrics').textContent(),totals);
  await page.click('#report-daily');await page.waitForSelector('.report-trend-overlay path');
  // Report filtering also changes the trend, without leaking excluded repository events.
  await page.evaluate(()=>{filters.reportRepositoriesExcluded=['example/repo'];renderReporting();});
  assert.match(await page.locator('.report-trend-summary').textContent(),/0\.0 reviewed · 0\.0 yours merged/);
  await page.evaluate(()=>{filters.reportRepositoriesExcluded=[];renderReporting();});
  const output=process.env.REPORTING_BROWSER_OUTPUT||'/tmp/pr-reporting-browser';fs.mkdirSync(output,{recursive:true});
  for(const theme of ['light','dark'])for(const width of [1440,390,320]){
   await page.evaluate(theme=>{document.documentElement.dataset.theme=theme;},theme);
   await page.setViewportSize({width,height:1100});
   await page.waitForFunction(()=>document.querySelector('.report-trend-overlay')?.viewBox.baseVal.width===document.querySelector('.report-chart-track')?.clientWidth);
   assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`Page overflow ${theme}/${width}`);
   assert.ok(await page.evaluate(()=>{
    const track=document.querySelector('.report-chart-track'),overlay=track.querySelector('.report-trend-overlay');
    return [...overlay.querySelectorAll('path')].every(el=>{const b=el.getBBox();return b.x>=0&&b.y>=0&&b.x+b.width<=track.clientWidth&&b.y+b.height<=track.clientHeight;});
   }),`Trend outside chart ${theme}/${width}`);
   // Verify the final marker shares the bar's actual value scale after resizing/scrolling.
   assert.ok(await page.evaluate(()=>{
    const point=reportTrendPoints.filter(p=>p.average).at(-1),track=document.querySelector('.report-chart-track');
    const bar=track.querySelector(`[data-report-period="${point.day}"] svg`).getBoundingClientRect();
    const overlay=track.querySelector('.report-trend-overlay'),marker=overlay.querySelector('circle');
    const expected=bar.bottom-track.getBoundingClientRect().top-point.average.review/Number(track.dataset.maximum)*(84/90)*bar.height;
    return Math.abs(Number(marker.getAttribute('cy'))-expected)<.1;
   }),`Trend/bar alignment ${theme}/${width}`);
   await page.locator('#reporting-view').screenshot({path:path.join(output,`${theme}-${width}.png`)});
   await page.click('.report-time-off summary');
   assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`Time-off overflow ${theme}/${width}`);
   await page.click('.report-time-off summary');
  }
  // A stale cache must not present its final partial day as a completed observation.
  data.range_end='2026-09-18';await page.evaluate(()=>loadReporting());
  await page.locator('[data-report-period="2026-09-18"]').click();
  assert.match(await page.locator('.report-selected-trend').textContent(),/incomplete day/);
  data.range_end='2026-09-21';data.range_start='2026-09-18';await page.evaluate(()=>loadReporting());
  assert.equal(await page.locator('.report-trend-overlay path').count(),0);
  assert.match(await page.locator('.report-trend-summary').textContent(),/needs 5 complete workdays/);
  assert.deepEqual(errors,[]);
  console.log('Reporting browser checks passed: trend windows, time off, persistence, filtering, drill-down, weekly totals, incomplete history, chart alignment, and light/dark 320/390/1440px layouts.');
 }finally{if(browser)await browser.close();fixture.kill('SIGTERM');}
})().catch(error=>{console.error(error);process.exitCode=1;});
