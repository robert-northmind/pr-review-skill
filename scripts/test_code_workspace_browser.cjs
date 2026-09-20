/* Browser regression suite, using the production routes and isolated boundaries. */
'use strict';
const {spawn}=require('node:child_process');
const {once}=require('node:events');
const path=require('node:path');
const assert=require('node:assert/strict');
const {chromium}=require(process.env.PR_REVIEW_PLAYWRIGHT_MODULE||'playwright');
(async()=>{
 const fixture=spawn(process.env.PYTHON||'python3',[path.join(__dirname,'workspace_integration_fixture.py')],{stdio:['ignore','pipe','inherit']});
 let browser;
 try{
  const [output]=await once(fixture.stdout,'data');
  browser=await chromium.launch({headless:true,channel:process.env.PR_REVIEW_BROWSER_CHANNEL||'chrome'});
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.goto(output.toString().trim());
  await page.locator('#file-0 [data-line="head"]').first().waitFor();
  await page.locator('#diff-layout').selectOption('split');
  assert.equal(await page.locator('#file-0 .split-pane').count(),2);
  await page.locator('#file-0').getByRole('button',{name:'Select head line 40',exact:true}).click();
  await page.locator('#ask-selection').click();
  await page.locator('#question').fill('Explain this guard');
  await page.locator('#send-question').click();
  await page.locator('.message.assistant').waitFor();
  assert.equal(await page.locator('.message script').count(),0);
  const thread=new URL(page.url()).searchParams.get('chat');assert.ok(thread);
  await page.locator('#file-tree button').nth(1).click();
  await page.locator('#file-1').getByRole('button',{name:'Select head line 20',exact:true}).click();
  await page.locator('#ask-selection').click();
  await page.locator('#question').fill('Keep this draft');
  await page.locator('[data-remove-context="0"]').click();
  assert.equal(await page.locator('#question').inputValue(),'Keep this draft');
  assert.equal(await page.locator('.context-attachment').count(),1);
  assert.equal(await page.locator('.message').count(),2);
  await page.locator('#question').fill('What test is missing?');
  await page.locator('#send-question').click();
  await page.locator('.message.assistant').nth(1).waitFor();
  assert.equal(new URL(page.url()).searchParams.get('chat'),thread);
  await page.locator('[data-save-message="3"]').click();
  await page.locator('#notes-toggle').click();
  await page.locator('.saved-note').waitFor();
  await page.locator('#close-rail').click();
  await page.locator('#file-1 [data-viewed]').check();
  // Navigation waits for serialized server saves; no arbitrary sleep.
  await page.locator('#refresh-comparison').click();
  await page.waitForURL(url=>!url.searchParams.has('chat'));
  await page.locator('#file-1 [data-viewed]').waitFor();
  assert.equal(await page.locator('#file-1 [data-viewed]').isChecked(),true);
  await page.locator('#chat-toggle').click();
  await page.locator('#thread-picker').selectOption(thread);
  assert.equal(await page.locator('.message').count(),4);
  await page.locator('#review-tab').click();
  await page.frameLocator('.review-frame').getByRole('heading',{name:'Fixture AI review'}).waitFor();
  assert.equal(await page.locator('.review-frame').getAttribute('sandbox'),'allow-scripts allow-popups allow-popups-to-escape-sandbox');
  await page.locator('#code-tab').click();
  await page.locator('#question').fill('Cancel this question');
  await page.locator('#send-question').click();await page.locator('#stop-chat').click();
  await page.waitForFunction(()=>document.getElementById('chat-status').textContent==='Stopped.');
  for(const width of [1440,880,390,320]){
   await page.setViewportSize({width,height:950});
   assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`overflow ${width}`);
  }
  assert.deepEqual(errors,[]);
  console.log('Workspace browser checks passed: layouts, source selection, durable chat/notes/viewed state, cancellation, report sandbox and responsive layout.');
 }finally{if(browser)await browser.close();fixture.kill('SIGTERM');}
})().catch(error=>{console.error(error);process.exitCode=1;});
