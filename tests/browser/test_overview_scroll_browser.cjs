// Preserve overview scroll across full-page review navigation and async card loading.
'use strict';
const {spawn}=require('node:child_process');
const {once}=require('node:events');
const path=require('node:path');
const assert=require('node:assert/strict');
const {chromium}=require(process.env.PR_REVIEW_PLAYWRIGHT_MODULE||'playwright');
(async()=>{
 const fixture=spawn(process.env.PYTHON||'python3',[path.join(__dirname,'../fixtures/workspace_browser_fixture.py')],{stdio:['ignore','pipe','inherit']});
 let browser;
 try{
  const [output]=await once(fixture.stdout,'data'),origin=output.toString().trim();
  browser=await chromium.launch({headless:true,channel:process.env.PR_REVIEW_BROWSER_CHANNEL||'chrome'});
  const context=await browser.newContext({viewport:{width:1440,height:1000}});
  await context.route('**/*',route=>new URL(route.request().url()).origin===origin?route.continue():route.abort());
  const page=await context.newPage(),errors=[],launches=[];
  page.on('pageerror',error=>errors.push(error.message));
  const snapshot=await (await context.request.get(origin+'/api/state')).json();
  const template=snapshot.prs[0];
  snapshot.prs=Array.from({length:30},(_,index)=>({...structuredClone(template),
   url:`https://github.com/example/repo/pull/${index+100}`,number:index+100,
   workflow:{stage:'up_next',bucket:'up_next',position:index,reasons:[]}}));
  await page.route('**/api/state',async route=>{
   // Returning before the cards load used to clamp the restored position to zero.
   await new Promise(resolve=>setTimeout(resolve,150));
   await route.fulfill({json:snapshot});
  });
  await page.route('**/workspace?*',route=>route.fulfill({contentType:'text/html; charset=utf-8',body:'<a href="/">‹ PR reviews</a>'}));
  await page.goto(origin);
  for(const view of ['inbox','queue']){
   await page.locator(view==='queue'?'#my-reviews-tab':'#inbox-tab').click();
   const list=view==='queue'?'#queue-list':'#pr-list';
   const link=page.locator(list+' a[href^="/workspace?"]').nth(12);
   await link.scrollIntoViewIfNeeded();
   const position=await page.evaluate(()=>scrollY);
   assert.ok(position>500);
   await link.click();await page.waitForURL('**/workspace?*');
   await page.locator('a[href="/"]').click();
   await page.locator(list+' .pr-card').first().waitFor({state:'visible'});
   await page.waitForFunction(y=>Math.abs(scrollY-y)<3,position);
   await link.click();await page.waitForURL('**/workspace?*');
   await page.goBack();
   await page.locator(list+' .pr-card').first().waitFor({state:'visible'});
   await page.waitForFunction(y=>Math.abs(scrollY-y)<3,position);
   // Polling must not jump back after the user scrolls elsewhere.
   await page.evaluate(async()=>{scrollTo(0,400);await loadState();});
   assert.equal(await page.evaluate(()=>scrollY),400);
  }
  assert.deepEqual(errors,[]);
  console.log('Overview scroll checks passed: Inbox and My reviews, return link, browser Back, delayed data, subsequent polling.');
 }finally{
  if(browser)await browser.close();
  const stopped=once(fixture,'exit');fixture.kill('SIGTERM');await stopped;
 }
})().catch(error=>{console.error(error);process.exitCode=1;});
