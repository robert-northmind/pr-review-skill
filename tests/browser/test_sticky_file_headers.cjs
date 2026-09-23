'use strict';
const {spawn}=require('node:child_process'),{once}=require('node:events'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require(process.env.PR_REVIEW_PLAYWRIGHT_MODULE||'playwright');
(async()=>{
 const fixture=spawn(process.env.PYTHON||'python3',[path.join(__dirname,'../fixtures/workspace_integration_fixture.py')],{stdio:['ignore','pipe','inherit']});let browser;
 try {
  const [chunk]=await once(fixture.stdout,'data');
  browser=await chromium.launch({headless:true,channel:'chrome'});
  const page=await browser.newPage({viewport:{width:1440,height:950}}),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.goto(chunk.toString().trim());await page.locator('#file-0 .code-row').first().waitFor();
  async function scrollFile(index,offset=200) {
   await page.evaluate(({index,offset})=>{
    const column=document.querySelector('.diff-column'),card=document.getElementById('file-'+index),toolbar=document.querySelector('.diff-toolbar');
    column.scrollTop+=card.getBoundingClientRect().top-toolbar.getBoundingClientRect().bottom+offset;
   },{index,offset});
   await page.waitForFunction(index=>Math.abs(document.querySelector('#file-'+index+' .file-header').getBoundingClientRect().top-document.querySelector('.diff-toolbar').getBoundingClientRect().bottom)<2,index);
   const state=await page.evaluate(index=>{
    const header=document.querySelector('#file-'+index+' .file-header'),control=header.querySelector('[data-viewed]').getBoundingClientRect(),top=document.querySelector('.diff-toolbar').getBoundingClientRect().bottom;
    return {pinned:[...document.querySelectorAll('.file-header')].filter(h=>Math.abs(h.getBoundingClientRect().top-top)<2).length,
     hit:document.elementFromPoint(control.x+control.width/2,control.y+control.height/2)?.closest('.file-card')?.id};
   },index);
   assert.equal(state.pinned,1);assert.equal(state.hit,'file-'+index);
  }
  await scrollFile(0);
  // The next file pushes the old header out; no stack of earlier headers.
  await page.locator('#file-1 .code-row').first().waitFor();await scrollFile(1,120);
  assert.ok(await page.evaluate(()=>document.querySelector('#file-0 .file-header').getBoundingClientRect().bottom<=document.querySelector('.diff-toolbar').getBoundingClientRect().bottom));
  await scrollFile(0);
  const saved=page.waitForResponse(r=>r.url().includes('/workspace-save')&&r.request().method()==='POST');
  await page.locator('#file-0 [data-viewed]').check();await saved;
  assert.equal(await page.locator('#file-0').getAttribute('class'),'file-card collapsed');
  const next=await page.evaluate(()=>document.getElementById('file-1').getBoundingClientRect().top-document.querySelector('.diff-toolbar').getBoundingClientRect().bottom);
  assert.ok(next>=0&&next<180,`next file skipped: ${next}`);
  await page.reload();await page.locator('#file-0 [data-viewed]').waitFor();assert.equal(await page.locator('#file-0 [data-viewed]').isChecked(),true);
  await page.locator('#file-0 [data-viewed]').uncheck();await page.locator('#file-0 .code-row').first().waitFor();
  for(const layout of ['split','unified'])for(const width of [1440,880,390]){
   await page.setViewportSize({width,height:950});await page.selectOption('#diff-layout',layout);
   if(width===390&&await page.locator('#files-toggle').getAttribute('aria-expanded')==='true')await page.click('#files-toggle');
   await scrollFile(0,200);
   assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`page overflow ${layout}/${width}`);
  }
  await page.setViewportSize({width:1440,height:950});await page.locator('#file-0 [data-full]').click();await scrollFile(0,300);
  assert.equal(await page.locator('#file-0 [data-full]').innerText(),'Back to diff');
  await page.locator('#file-0 [data-collapse]').click();
  assert.ok(await page.evaluate(()=>document.getElementById('file-1').getBoundingClientRect().top>=document.querySelector('.diff-toolbar').getBoundingClientRect().bottom));
  assert.deepEqual(errors,[]);console.log('Sticky file headers: current-file replacement, accessible Viewed, persistence, collapse position, full files, unified/split and responsive toolbar offsets passed.');
 }finally{await browser?.close();fixture.kill('SIGTERM');}
})().catch(error=>{console.error(error);process.exitCode=1;});
