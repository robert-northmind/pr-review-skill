'use strict';
const {spawn}=require('node:child_process'),{once}=require('node:events'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require(process.env.PR_REVIEW_PLAYWRIGHT_MODULE||'playwright');
(async()=>{
 const fixture=spawn(process.env.PYTHON||'python3',[path.join(__dirname,'../fixtures/workspace_integration_fixture.py')],{stdio:['ignore','pipe','inherit']});let browser;
 try {
  const [chunk]=await once(fixture.stdout,'data'),url=chunk.toString().trim();
  browser=await chromium.launch({headless:true,channel:'chrome'});
  const context=await browser.newContext({viewport:{width:1440,height:1050},permissions:['clipboard-read','clipboard-write']});
  const page=await context.newPage(),errors=[];page.on('pageerror',error=>errors.push(error.message));
  await page.goto(url);await page.locator('#file-0 [data-line="head"]').first().waitFor();
  await page.click('#chat-toggle');await page.fill('#question','Explain the storage keys');await page.click('#send-question');
  await page.locator('.message.streaming .chat-markdown').waitFor();
  assert.equal(await page.locator('.message.streaming script').count(),0);
  await page.locator('.message.assistant .chat-markdown table').waitFor();
  assert.equal(await page.locator('.chat-markdown h3').innerText(),'Why the keys stay separate');
  assert.equal(await page.locator('.chat-markdown li').count(),2);
  assert.equal(await page.locator('.chat-markdown tbody tr').count(),2);
  assert.equal(await page.locator('.chat-markdown script').count(),0);
  await page.locator('[data-copy-code]').click();
  assert.match(await page.evaluate(()=>navigator.clipboard.readText()),/let key = "mobile-session-record"/);
  const rail=page.locator('#conversation'),handle=page.locator('#chat-resize');
  const initial=(await rail.boundingBox()).width,box=await handle.boundingBox();
  await page.mouse.move(box.x+box.width/2,box.y+50);await page.mouse.down();
  await page.mouse.move(box.x-230,box.y+50,{steps:8});await page.mouse.up();
  const expanded=(await rail.boundingBox()).width;assert.ok(expanded>initial+200);
  assert.equal(await page.evaluate(()=>document.body.classList.contains('resizing-chat')),false);
  await handle.focus();await page.keyboard.press('ArrowLeft');
  const keyboard=(await rail.boundingBox()).width;assert.equal(keyboard,expanded+24);
  await page.reload();await page.locator('.chat-markdown table').waitFor();
  assert.equal((await rail.boundingBox()).width,keyboard);
  // Viewport clamping must preserve the larger saved desktop preference.
  await page.setViewportSize({width:800,height:1050});await page.waitForFunction(()=>document.getElementById('conversation').getBoundingClientRect().width<=440);
  await page.setViewportSize({width:1440,height:1050});await page.waitForFunction(width=>document.getElementById('conversation').getBoundingClientRect().width===width,keyboard);
  const fs=require('node:fs'),out=require('node:os').tmpdir()+'/pr-review-chat-reading';fs.mkdirSync(out,{recursive:true});
  for(const theme of ['light','dark'])for(const width of [1440,880,390,320]){
   await page.evaluate(t=>document.documentElement.dataset.theme=t,theme);await page.setViewportSize({width,height:1050});
   assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`page overflow ${theme}/${width}`);
   assert.ok(await rail.evaluate(el=>el.scrollWidth<=el.clientWidth),`rail overflow ${theme}/${width}`);
   assert.equal(await handle.isVisible(),width>750);
   await page.locator('.chat-markdown h3').scrollIntoViewIfNeeded();
   await page.screenshot({path:path.join(out,`${theme}-${width}.png`)});
  }
  await page.setViewportSize({width:1440,height:1050});await handle.focus();await page.keyboard.press('Enter');assert.equal((await rail.boundingBox()).width,420);
  await page.keyboard.press('End');assert.equal((await rail.boundingBox()).width,900);
  await page.keyboard.press('Home');assert.equal((await rail.boundingBox()).width,320);
  await handle.dblclick();assert.equal((await rail.boundingBox()).width,420);
  const resetBox=await handle.boundingBox();await page.mouse.move(resetBox.x+5,resetBox.y+50);await page.mouse.down();await page.mouse.move(resetBox.x-100,resetBox.y+50);await page.keyboard.press('Escape');await page.mouse.up();assert.equal((await rail.boundingBox()).width,420);assert.equal(await rail.isVisible(),true);
  assert.deepEqual(errors,[]);console.log('Chat reading: Markdown, streaming, code copy, drag/keyboard resize, persisted width, viewport clamping and light/dark mobile layouts passed.');
 } finally {await browser?.close();fixture.kill('SIGTERM');}
})().catch(error=>{console.error(error);process.exitCode=1;});
