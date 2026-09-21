// Exercise Inbox launch controls with synthetic state and intercepted launch requests.
'use strict';
const {spawn}=require('node:child_process');
const {once}=require('node:events');
const path=require('node:path');
const assert=require('node:assert/strict');
const {chromium}=require(process.env.PR_REVIEW_PLAYWRIGHT_MODULE||'playwright');
(async()=>{
 const fixture=spawn(process.env.PYTHON||'python3',[path.join(__dirname,'workspace_browser_fixture.py')],{stdio:['ignore','pipe','inherit']});
 let browser;
 try{
  const [output]=await once(fixture.stdout,'data'),origin=output.toString().trim();
  browser=await chromium.launch({headless:true,channel:process.env.PR_REVIEW_BROWSER_CHANNEL||'chrome'});
  const context=await browser.newContext({viewport:{width:1440,height:1000}});
  await context.route('**/*',route=>new URL(route.request().url()).origin===origin?route.continue():route.abort());
  const page=await context.newPage(),errors=[],launches=[];
  page.on('pageerror',error=>errors.push(error.message));
  const snapshot=await (await context.request.get(origin+'/api/state')).json();
  const pr=snapshot.prs.find(item=>item.number===1);
  assert.ok(pr);
  pr.artifacts={};pr.run=null;pr.history=[];pr.history_total=0;
  await page.route('**/api/state',route=>route.fulfill({json:snapshot}));
  let failNext=false;
  await page.route('**/regenerate-review',async route=>{
   assert.equal(route.request().method(),'POST');
   const body=route.request().postDataJSON();
   assert.equal(body.url,pr.url);assert.equal(body.retry,false);
   assert.ok(route.request().headers()['x-csrf-token']);
   launches.push(body);
   if(failNext){failNext=false;await route.fulfill({status:400,json:{error:'Synthetic launch failure'}});return;}
   pr.run={run_id:'synthetic-run',status:'running',tool:'claude',transport:'terminal',tasks:[],updated_at:new Date().toISOString()};
   await route.fulfill({json:{run_id:pr.run.run_id,transport:'terminal',existing:false}});
  });
  await page.goto(origin);
  const card=page.locator(`[data-pr="${pr.url}"]`);
  await card.waitFor();
  assert.equal(await card.locator('[data-action="/regenerate-review"]').count(),1,'Inbox must offer a first AI review before notes exist');
  await card.locator('.pr-overflow > summary').click();
  await card.getByRole('button',{name:'Run AI review',exact:true}).click();
  await card.getByRole('button',{name:'AI review in progress',exact:true}).waitFor({state:'attached'});
  assert.equal(await card.getByRole('button',{name:'AI review in progress',exact:true}).isDisabled(),true);
  assert.equal(launches.length,1);

  // Existing notes still allow reruns; a rejected launch must restore the action.
  pr.run.status='completed';
  pr.artifacts={'review-html':{path:'/synthetic/review.html',freshness:'current',head_sha:'b'.repeat(40)}};
  failNext=true;
  await page.reload();await card.waitFor();
  await card.locator('.pr-overflow > summary').click();
  await card.getByRole('button',{name:'Run AI review again',exact:true}).click();
  await page.waitForFunction(()=>document.getElementById('toast').textContent.includes('Synthetic launch failure'));
  assert.equal(await card.getByRole('button',{name:'Run AI review again',exact:true}).isDisabled(),false);
  assert.equal(launches.length,2);

  for(const width of [1440,390]){
   await page.setViewportSize({width,height:1000});
   const menu=card.locator('.pr-overflow');
   if(!await menu.evaluate(element=>element.open))await menu.locator('summary').click();
   assert.equal(await card.getByRole('button',{name:'Run AI review again',exact:true}).isVisible(),true);
   assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`page overflow at ${width}`);
  }
  await card.getByRole('button',{name:'Run AI review again',exact:true}).click();
  await card.getByRole('button',{name:'AI review in progress',exact:true}).waitFor({state:'attached'});
  assert.equal(launches.length,3);
  assert.deepEqual(errors,[]);
  console.log('Inbox review browser checks passed: first launch, active-run guard, rerun, failure recovery, desktop/mobile.');
 }finally{
  if(browser)await browser.close();
  const stopped=once(fixture,'exit');fixture.kill('SIGTERM');await stopped;
 }
})().catch(error=>{console.error(error);process.exitCode=1;});
