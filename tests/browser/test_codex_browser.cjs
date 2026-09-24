'use strict';
const {spawn}=require('node:child_process'),{once}=require('node:events'),path=require('node:path'),fs=require('node:fs'),assert=require('node:assert/strict');
const {chromium}=require(process.env.PR_REVIEW_PLAYWRIGHT_MODULE||'playwright');
(async()=>{
 const fixture=spawn(process.env.PYTHON||'python3',[path.join(__dirname,'../fixtures/codex_browser_fixture.py')],{stdio:['ignore','pipe','inherit']});let browser;
 try{
  const [chunk]=await once(fixture.stdout,'data'),url=chunk.toString().trim();
  browser=await chromium.launch({headless:true,channel:'chrome'});
  const page=await browser.newPage({viewport:{width:1440,height:1050}}),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.goto(url);await page.locator('[data-review-open]').first().click();
  await page.waitForSelector('#review-dialog[open] .review-event');
  assert.match(await page.locator('#review-updates').textContent(),/simulated review/);
  const initial=await page.locator('.review-stage[data-state=running]').first().textContent();
  await page.waitForFunction(v=>document.querySelector('.review-stage[data-state=running]').textContent!==v,initial,{timeout:12000});
  await page.reload();await page.waitForSelector('#review-dialog[open] .review-event');
  assert.match(await page.locator('#review-updates').textContent(),/6 of 100/);
  await page.context().setOffline(true);
  await page.waitForFunction(()=>document.getElementById('review-stream-status').textContent.includes('Reconnecting'));
  await page.context().setOffline(false);
  await page.waitForFunction(()=>document.getElementById('review-stream-status').textContent.startsWith('Live'),{timeout:15000});
  await page.evaluate(()=>{const event={id:999,at:new Date().toISOString(),kind:'update',text:'<img src=x onerror=alert(1)>'};const fake={run_id:reviewPanel.runId,status:'running',message:'Checking',progress:{percent:45,finished:2,total:9,skipped:0,stages:[]},events:[event]};reviewPanel.render(fake);});
  assert.equal(await page.locator('#review-updates img').count(),0);
  await page.waitForSelector('.review-stage');
  const output=process.env.PR_REVIEW_SCREENSHOTS||require('node:os').tmpdir()+'/pr-review-codex-screenshots';fs.mkdirSync(output,{recursive:true});
  for(const theme of ['light','dark'])for(const width of [1440,390]){
   await page.evaluate(t=>document.documentElement.dataset.theme=t,theme);await page.setViewportSize({width,height:1050});
   assert.ok(await page.evaluate(()=>document.querySelector('#review-dialog').scrollWidth<=document.querySelector('#review-dialog').clientWidth),`dialog overflow ${theme}/${width}`);
   await page.screenshot({path:path.join(output,`${theme}-${width}.png`)});
  }
  // Questions and steering go to the running reviewer; replies land in the feed.
  assert.equal(await page.locator('#review-compose').isVisible(),true);
  await page.locator('#review-compose-text').fill('What is going on?');
  await page.locator('#review-compose-text').press('Enter');
  await page.waitForSelector('.review-event.you');
  assert.equal(await page.locator('#review-compose-text').inputValue(),'');
  assert.match(await page.locator('.review-event.you').first().textContent(),/What is going on\?/);
  await page.waitForFunction(()=>document.getElementById('review-updates').textContent.includes('Sample reply'),null,{timeout:8000});
  assert.equal(await page.locator('.review-event.you').count(),1);
  await page.locator('#review-compose-text').fill('Skip the example app');
  page.once('dialog',dialog=>dialog.dismiss());
  await page.locator('#review-wrap-up').click();
  assert.equal(await page.locator('#review-wrap-up').isDisabled(),false,'Dismissing the confirmation must not wrap up');
  page.once('dialog',dialog=>dialog.accept());
  await page.locator('#review-wrap-up').click();
  assert.equal(await page.locator('#review-wrap-up').textContent(),'Wrapping up…');
  await page.waitForFunction(()=>[...document.querySelectorAll('.review-event.you')].some(e=>e.textContent.includes('Wrap up now. Skip the example app')),null,{timeout:8000});
  await page.reload();await page.waitForSelector('#review-dialog[open] .review-event.you');
  assert.equal(await page.locator('#review-wrap-up').isDisabled(),true);
  assert.equal(await page.locator('#review-wrap-up').textContent(),'Wrapping up…');
  await page.locator('#review-stop').click();
  await page.waitForFunction(()=>document.getElementById('review-status').textContent.startsWith('Cancelled'));
  await page.reload();await page.waitForFunction(()=>document.getElementById('review-status').textContent.startsWith('Cancelled'));
  assert.equal(await page.locator('#review-stop').isVisible(),false);
  assert.equal(await page.locator('#review-compose').isVisible(),false);
  assert.equal(await page.locator('#review-wrap-up').isVisible(),false);
  // A finished deep link must await the shared state request before rendering its report link.
  const saved=await page.evaluate(()=>state),savedRun=saved.prs[0].history[0];
  savedRun.artifacts['review-html']={name:'review-html',run_id:savedRun.run_id,path:'/fixture/report.html',version:'fixture',freshness:'current',status:'completed'};
  const deep=await browser.newPage();
  const terminal=await page.evaluate(async()=>await (await fetch('/api/review?run_id='+encodeURIComponent(reviewPanel.runId))).json());
  terminal.status='completed-with-gaps';terminal.message='Report ready; local Dart startup blocked.';
  terminal.progress.percent=85;terminal.progress.finished=8;
  terminal.progress.stages.forEach(s=>{s.status=s.name==='runtime-verification'?'blocked':'completed';});
  Object.assign(savedRun,{status:terminal.status,progress:terminal.progress});
  await deep.route('**/api/state',async route=>{await new Promise(resolve=>setTimeout(resolve,800));await route.fulfill({json:saved});});
  await deep.route('**/api/review?*',route=>route.fulfill({json:terminal}));
  await deep.goto(url+'/?review='+encodeURIComponent(savedRun.run_id));
  await deep.waitForSelector('#review-result a');
  assert.match(await deep.locator('#review-result a').textContent(),/Open review notes/);
  assert.equal(await deep.locator('#review-status').textContent(),'Finished · 1 stage blocked');
  assert.equal(await deep.locator('#review-progress').isVisible(),false);
  assert.equal(await deep.locator('#review-percent').isVisible(),false);
  assert.equal(await deep.locator('#review-estimate').isVisible(),false);
  assert.equal(await deep.locator('.review-stage[data-state=blocked]').count(),1);
  assert.equal(await deep.locator('.review-summary progress').count(),0);
  assert.doesNotMatch(await deep.locator('.review-summary').first().textContent(),/85%/);
  await deep.reload();await deep.waitForSelector('#review-result a');
  assert.equal(await deep.locator('#review-status').textContent(),'Finished · 1 stage blocked');
  for(const status of ['completed','failed','cancelled','blocked']){
   await deep.evaluate(({data,status})=>reviewPanel.render({...data,status}),{data:terminal,status});
   assert.equal(await deep.locator('#review-progress').isVisible(),false);
   assert.equal(await deep.locator('#review-percent').isVisible(),false);
  }
  await deep.evaluate(data=>reviewPanel.render({...data,status:'running'}),terminal);
  assert.equal(await deep.locator('#review-progress').isVisible(),true);
  assert.equal(await deep.locator('#review-percent').isVisible(),true);
  assert.equal(await deep.locator('#review-estimate').isVisible(),true);
  assert.equal(await deep.locator('#review-stop').isVisible(),true);
  await deep.locator('#review-close').click();
  await deep.reload();
  assert.equal(await deep.locator('#review-dialog').isVisible(),false);
  assert.equal(new URL(deep.url()).searchParams.has('review'),false);
  await deep.locator('[data-review-open]').first().click();
  await deep.waitForSelector('#review-result a');
  // Reopening the same run must ignore a slower response from the old view.
  await deep.unroute('**/api/review?*');
  let requests=0;
  await deep.route('**/api/review?*',async route=>{
   const old=++requests===1;
   if(old)await new Promise(resolve=>setTimeout(resolve,300));
   await route.fulfill({json:old?{...terminal,status:'failed',message:'Stale response'}:terminal});
  });
  await deep.evaluate(async runId=>{
   const first=openReview(runId),second=openReview(runId);
   await Promise.all([first,second]);
  },savedRun.run_id);
  assert.equal(await deep.locator('#review-status').textContent(),'Finished · 1 stage blocked');
  await deep.close();
  assert.deepEqual(errors,[]);
  console.log('Browser checks passed: live progress, reload, offline reconnect, escaped content, questions, wrap-up, cancellation, terminal outcomes, saved report link, light/dark desktop/mobile.');
 }finally{if(browser)await browser.close();fixture.kill('SIGTERM');}
})().catch(e=>{console.error(e);process.exitCode=1;});
