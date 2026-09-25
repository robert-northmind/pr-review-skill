#!/usr/bin/env node
'use strict';
const fs=require('fs');const path=require('path');const {pathToFileURL}=require('url');const {execFileSync}=require('child_process');
const {chromium}=require(process.env.PR_REVIEW_PLAYWRIGHT_MODULE||'playwright');
const [fileArg,outputArg,inputArg]=process.argv.slice(2);
if(!fileArg||!outputArg){console.error('Usage: check_review.cjs page.html validation-directory [input.json]');process.exit(2);}
const file=path.resolve(fileArg),output=path.resolve(outputArg);fs.mkdirSync(output,{recursive:true});
const result={file,errors:[],warnings:[],words:0,sections:[],quizClicks:0,sourceExcerpts:0,screenshots:[]};
function check(ok,message){if(!ok)result.errors.push(message);}
(async()=>{
 let browser;
 try{
  browser=await chromium.launch({headless:true,...(process.env.PR_REVIEW_CHROME_PATH?{executablePath:process.env.PR_REVIEW_CHROME_PATH}:{})});
  const context=await browser.newContext();const requests=[];
  await context.route(/^https?:/,route=>{requests.push(route.request().url());return route.abort();});
  const page=await context.newPage();page.on('pageerror',e=>result.errors.push('Page JavaScript: '+e.message));
  await page.setViewportSize({width:1280,height:900});await page.goto(pathToFileURL(file).href);
  const inventory=await page.evaluate(()=>{
   const count=root=>{const it=document.createTreeWalker(root,NodeFilter.SHOW_TEXT);let node,parts=[];while(node=it.nextNode())if(!node.parentElement.closest('pre,textarea,script,style,svg,.diagram-body,.cases table,[data-exclude-count]'))parts.push(node.textContent);return parts.join(' ').trim().split(/\s+/).filter(Boolean).length;};
   return {words:count(document.body),explanationWords:[...document.querySelectorAll('header[data-section],main > section')].filter(e=>!['review-findings','verification','self-check'].includes(e.id)).reduce((n,e)=>n+count(e),0)-(document.getElementById('review-assessment')?count(document.getElementById('review-assessment')):0),mode:document.documentElement.dataset.mode,sections:[...document.querySelectorAll('[data-section]')].map(e=>({section:e.dataset.section,words:count(e)})),csp:document.querySelector('meta[http-equiv="Content-Security-Policy"]')?.content,assets:[...document.querySelectorAll('script[src],link[rel=stylesheet],iframe,form,img[src]')].map(e=>e.outerHTML),links:[...document.querySelectorAll('a')].map(a=>({href:a.getAttribute('href'),target:a.target,rel:a.rel,reviewNotes:a.classList.contains('review-notes-link')})),long:[...document.querySelectorAll('p,li')].filter(e=>!e.closest('pre')).flatMap(e=>e.textContent.trim().split(/(?<=[.!?])\s+/).filter(s=>s.split(/\s+/).length>30)),whitespace:[...document.querySelectorAll('pre')].every(p=>['pre','pre-wrap'].includes(getComputedStyle(p).whiteSpace)),rows:[...document.querySelectorAll('.code-line')].map(e=>({height:e.getBoundingClientRect().height,lineHeight:parseFloat(getComputedStyle(e).lineHeight)})),sources:[...document.querySelectorAll('.source')].map(s=>({path:s.dataset.path,revision:s.dataset.revision,side:s.dataset.side,lines:[...s.querySelectorAll('.code-line')].map(l=>({number:Number(l.dataset.line),text:l.querySelector('.source-text').textContent}))}))};
  });
  result.words=inventory.words;result.sections=inventory.sections;result.mode=inventory.mode;
  const target={'Brief · Small':800,'Brief · Standard':1200,Deep:3000}[inventory.mode],ceiling=Math.round((target||0)*1.5);check(!!target,'Missing/invalid mode');check(inventory.explanationWords<=ceiling,'Explanation prose exceeds hard limit: '+inventory.explanationWords+' > '+ceiling+' (target '+target+')');if(target&&inventory.explanationWords>target&&inventory.explanationWords<=ceiling)result.warnings.push('Explanation prose is over target: '+inventory.explanationWords+' > '+target+'; trim repetition if possible without dropping essential caveats.');result.explanationWords=inventory.explanationWords;
  if(inventory.long.length)result.warnings.push(inventory.long.length+' sentences/paragraph fragments exceed 30 words; inspect readability without dropping essential conditions.');
  check(inventory.csp?.includes("default-src 'none'")&&inventory.csp?.includes("connect-src 'none'")&&inventory.csp?.includes("base-uri 'none'")&&inventory.csp?.includes("form-action 'none'"),'Missing restrictive CSP');
  check(!inventory.assets.length,'External assets, images, frames, or forms present');check(inventory.whitespace,'Code block does not preserve whitespace');check(inventory.rows.every(r=>Math.abs(r.height-r.lineHeight)<1),'Source rows have extra vertical spacing');
  const attachments=inputArg?(JSON.parse(fs.readFileSync(inputArg,'utf8')).attachments||[]).map(p=>pathToFileURL(fs.realpathSync(p)).href):[];
  for(const link of inventory.links){if(link.href.startsWith('#'))check(await page.locator('[id="'+link.href.slice(1)+'"]').count()===1,'Unresolved section link: '+link.href);else{check(link.href.startsWith('https://')||attachments.includes(link.href),'Unapproved source/artifact navigation');check(link.target==='_blank'&&link.rel.includes('noopener')&&link.rel.includes('noreferrer'),'Missing safe navigation attributes');}}
  const sourceInput=inputArg?JSON.parse(fs.readFileSync(inputArg,'utf8')):null;
  if(sourceInput?.review?.assessment){
   const assessment=page.locator('#review-assessment');
   check(await assessment.count()===1&&await assessment.isVisible(),'Missing visible overview assessment');
   check(await assessment.locator('details,.review-comment,.scenario,.flow,.sequence,.diagram,.cases').count()===0,'Overview assessment hides caveats or contains drafts');
   const box=await assessment.boundingBox();
   check(box&&box.y+box.height<=900,'Assessment extends below first desktop viewport; inspect overview length');
   await assessment.locator('.findings-link').click();
   check(await page.locator('#review-findings').evaluate(e=>e.getBoundingClientRect().top>=-1&&e.getBoundingClientRect().top<innerHeight),'Overview shortcut does not reach findings');
   await page.evaluate(()=>scrollTo(0,0));
  }
  if(sourceInput){for(const source of inventory.sources){
   const raw=source.revision==='working-tree'?fs.readFileSync(path.resolve(sourceInput.repository,source.path),'utf8'):execFileSync('git',['-C',sourceInput.repository,'show',source.revision+':'+source.path],{encoding:'utf8'});
   const lines=raw.split(/\r?\n/);for(const line of source.lines)check(lines[line.number-1]===line.text,'Source mismatch: '+source.path+':'+line.number);result.sourceExcerpts++;
  }}else result.warnings.push('No authoring input supplied; source fidelity not independently compared with Git.');
  check(await page.locator('#review-findings').count()===1,'Missing integrated review findings');
  const findings=page.locator('#review-findings > details.review-finding');result.findings=await findings.count();
  if(result.findings){
   check(await page.locator('details.review-finding[open]').count()===0,'Findings should start collapsed');
   for(let i=0;i<result.findings;i++){
    const summary=findings.nth(i).locator(':scope > summary');
    await summary.focus();await page.keyboard.press('Enter');
    check(await findings.nth(i).getAttribute('open')!==null,'Finding does not open with keyboard');
   }
   check(await page.locator('details.review-finding[open]').count()===result.findings,'Opening a finding closes another');
   check(await page.locator('details.review-finding details[open]').count()===0,'Nested evidence should remain collapsed');
   if(result.findings>1){
    await page.getByRole('button',{name:'Collapse all findings',exact:true}).click();
    check(await page.locator('details.review-finding[open]').count()===0,'Collapse all leaves findings open');
    await page.getByRole('button',{name:'Expand all findings',exact:true}).click();
    check(await page.locator('details.review-finding[open]').count()===result.findings,'Expand all leaves findings hidden');
   }
  }
  const comments=page.locator('.review-comment');result.comments=await comments.count();
  // Assert the exact Markdown payload, then exercise both clipboard outcomes.
  if(sourceInput){
   const expected=[];let current=null,fence=null;
   for(const line of sourceInput.review.markdown.split(/\r?\n/)){
    const token=line.trim().match(/^(`{3,}|~{3,})(.*)$/);
    if(token){if(!fence)fence=token[1];else if(token[1][0]===fence[0]&&token[1].length>=fence.length&&!token[2].trim())fence=null;}
    if(!fence&&line.trim()==='<!-- review-comment:start -->'){current=[];continue;}
    if(!fence&&line.trim()==='<!-- review-comment:end -->'){expected.push(current.join('\n').replace(/^\n+|\n+$/g,''));current=null;continue;}
    if(current)current.push(line);
   }
   check(expected.length===result.comments,'Comment block count differs from input');
   for(let i=0;i<result.comments;i++)check(await comments.nth(i).locator('.comment-source').inputValue()===expected[i],'Copy payload differs from authored Markdown');
  }
  for(let i=0;i<result.comments;i++){
   const comment=comments.nth(i),button=comment.locator('.copy-comment');
   await page.evaluate(()=>Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async value=>{window.copiedReviewComment=value;}}}));
   await button.click();await page.waitForFunction(()=>document.querySelector('.copy-status')!==null);
   check(await page.evaluate(()=>window.copiedReviewComment)===await comment.locator('.comment-source').inputValue(),'Copy loses Markdown or includes metadata');
   await page.evaluate(()=>Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async()=>{throw new Error('denied');}}}));
   await button.click();check(await comment.locator('.comment-source').isVisible(),'Missing manual-copy fallback');
   await comment.locator('.comment-source').evaluate(e=>{e.hidden=true;});
   await comment.locator('.copy-status').evaluate(e=>{e.textContent='';});
  }
  const scenarios=page.locator('.scenario');result.scenarios=await scenarios.count();
  for(let i=0;i<result.scenarios;i++){
   const scenario=scenarios.nth(i),buttons=scenario.locator('.scenario-controls button'),frames=scenario.locator(':scope > .scenario-frame');
   const n=await buttons.count();check(n>=2&&n<=5,'Scenario needs meaningful alternatives');
   check(await frames.count()===n,'Scenario controls and states differ');
   for(let j=0;j<n;j++){
    await buttons.nth(j).focus();await page.keyboard.press('Enter');
    for(let k=0;k<n;k++){
     check(await frames.nth(k).isVisible()===(j===k),'Scenario exposes the wrong state');
     check(await buttons.nth(k).getAttribute('aria-pressed')===String(j===k),'Scenario selection is not announced');
    }
   }
   await buttons.first().click();
  }
  if(result.scenarios){
   const fallbackContext=await browser.newContext({javaScriptEnabled:false});
   const fallback=await fallbackContext.newPage();await fallback.goto(pathToFileURL(file).href);
   await fallback.locator('details').evaluateAll(items=>items.forEach(e=>e.open=true));
   check(await fallback.locator('.scenario-frame-label').evaluateAll(items=>items.every(e=>e.getBoundingClientRect().height>0)),'Scenario labels disappear without JavaScript');
   check(await fallback.locator('.scenario-frame').evaluateAll(items=>items.every(e=>e.getBoundingClientRect().height>0)),'Scenario content disappears without JavaScript');
   check(await fallback.locator('.scenario-controls').evaluateAll(items=>items.every(e=>e.hidden)),'Inactive scenario controls shown without JavaScript');
   await fallbackContext.close();
  }
  const quiz=page.locator('.question');const count=await quiz.count();
  check(count<=(inventory.mode==='Deep'?5:3),'Too many self-checks');
  if(count){
   check(await page.locator('#quiz').getAttribute('open')===null,'Self-check should start collapsed');await page.locator('#quiz > summary').click();
   for(let q=0;q<count;q++){
    const group=quiz.nth(q);const choices=group.locator('.options button');const n=await choices.count();const answer=Number(await group.getAttribute('data-answer'));
    check(n>=2&&n<=4,'Question must have 2–4 choices');check(await group.locator('.quiz-explanation').isHidden(),'Answer explanation is exposed before choice');
    if(sourceInput){const original=sourceInput.questions[q];const correctText=await choices.nth(answer).innerText();check(correctText.slice(3)===original.options[original.answer],'Answer mapping changed during rendering');}
    for(let a=0;a<n;a++){
     await choices.nth(a).click();result.quizClicks++;check(await group.locator('.feedback').getAttribute('data-result')===(a===answer?'correct':'incorrect'),'Wrong feedback state');check((await group.locator('.feedback').innerText()).includes('Selected '+String.fromCharCode(65+a)), 'Feedback does not identify selected answer');check(await group.locator('.quiz-explanation').isVisible(),'Missing answer explanation');
    }
   }
   await page.locator('#reset-quiz').click();check(await page.locator('.options button[aria-pressed]').count()===0,'Reset retains selection');
   check((await page.locator('.feedback').allInnerTexts()).every(t=>!t),'Reset retains feedback');
   await page.locator('#quiz > summary').click();
  }
  for(const expected of ['light','dark','system']){await page.locator('#theme').click();check((await page.locator('html').getAttribute('data-theme')||'system')===expected,'Theme cycle mismatch');}
  result.themes=[];
  for(const width of [1280,390])for(const scheme of ['light','dark']){
   await page.emulateMedia({colorScheme:scheme});await page.setViewportSize({width,height:width===390?844:900});
   await page.evaluate(()=>scrollTo(0,0));
   const geometry=await page.evaluate(()=>({viewport:innerWidth,width:document.documentElement.scrollWidth,background:getComputedStyle(document.body).backgroundColor,overviewBottom:document.querySelector('.outcome')?.getBoundingClientRect().bottom}));
   check(geometry.width<=width,'Document overflow at '+width+'px ('+scheme+'): '+geometry.width+'px');if(width===1280)check(geometry.overviewBottom<900,'Outcome is below the first desktop viewport');result.themes.push({scheme,...geometry});
   const screenshot=path.join(output,(width===390?'phone':'desktop')+'-'+scheme+'.jpg');await page.screenshot({path:screenshot,fullPage:true,type:'jpeg',quality:80});result.screenshots.push(screenshot);
   if(result.findings){
    await findings.evaluateAll(items=>items.forEach(item=>item.open=false));
    const collapsed=path.join(output,(width===390?'phone':'desktop')+'-'+scheme+'-collapsed.jpg');await page.screenshot({path:collapsed,fullPage:true,type:'jpeg',quality:80});result.screenshots.push(collapsed);
    check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Collapsed findings cause overflow');
    await findings.evaluateAll(items=>items.forEach(item=>item.open=true));
   }
  }
  check(result.themes[0].background!==result.themes[1].background,'System theme does not respond to color scheme');
  check(requests.length===0,'Page attempted network requests');result.networkRequests=requests;
 }catch(error){result.errors.push(String(error.stack||error));}
 finally{if(browser)await browser.close();fs.writeFileSync(path.join(output,'validation.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2));if(result.errors.length)process.exitCode=1;}
})();
