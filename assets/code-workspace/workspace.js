'use strict';
(() => {
 const $ = id => document.getElementById(id);
 const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const params = new URLSearchParams(location.search);
 let data, storageKey, saved = {viewed:[], collapsed:[], threads:[], notes:[]}, selection = null, threadId = null, activeFile = 0, toastTimer;
 let tab = params.get('tab') === 'review' ? 'review' : 'code';
 let layoutPreference='unified',diffLayout='unified';
 try {if(localStorage.getItem('pr-code-diff-layout')==='split')layoutPreference='split';}catch{}
 const full = new Map(), revealed = new Map();
 let alignmentFrame;
 function alignSplitRows(){
  cancelAnimationFrame(alignmentFrame);
  alignmentFrame=requestAnimationFrame(()=>{
   for(const grid of document.querySelectorAll('.split-diff')){
    const left=[...grid.querySelector('.split-pane').querySelectorAll('[data-pair]')];
    const right=[...grid.querySelectorAll('.split-pane')[1].querySelectorAll('[data-pair]')];
    [...left,...right].forEach(row=>row.style.minHeight='');
    const heights=left.map((row,i)=>Math.max(row.getBoundingClientRect().height,right[i].getBoundingClientRect().height));
    left.forEach((row,i)=>{row.style.minHeight=right[i].style.minHeight=heights[i]+'px';});
   }
  });
 }
 function updateLayout(){
  if(!data||$('code-view').hidden)return;
  const column=document.querySelector('.diff-column'),style=getComputedStyle(column);
  const width=column.clientWidth-parseFloat(style.paddingLeft)-parseFloat(style.paddingRight);
  const fits=width>=760,next=layoutPreference==='split'&&fits?'split':'unified';
  $('diff-layout').querySelector('[value="split"]').disabled=!fits;
  $('diff-layout').value=next;
  $('layout-hint').textContent=!fits?(layoutPreference==='split'?'Unified to fit · side by side returns with more room':'Hide Files or close chat for side by side'):'';
  $('files-toggle').setAttribute('aria-expanded',getComputedStyle(document.querySelector('.file-sidebar')).display!=='none');
  if(next!==diffLayout){
   const top=document.querySelector('.diff-toolbar').getBoundingClientRect().bottom;
   const anchor=[...document.querySelectorAll('.code-row')].find(row=>row.getBoundingClientRect().bottom>top&&row.getBoundingClientRect().height>0);
   const position=anchor?{file:anchor.dataset.file,row:anchor.dataset.row,side:anchor.dataset.side,top:anchor.getBoundingClientRect().top}:null;
   diffLayout=next;renderFiles();
   if(position){const targets=[...document.querySelectorAll(`[data-file="${position.file}"][data-row="${position.row}"]`)];const replacement=targets.find(row=>!row.dataset.side||row.dataset.side===position.side)||targets[0];if(replacement)column.scrollTop+=replacement.getBoundingClientRect().top-position.top;}
  }
  alignSplitRows();
 }

 const basename = path => path.split('/').pop();
 function notify(text) { $('workspace-toast').textContent=text; $('workspace-toast').hidden=false; clearTimeout(toastTimer); toastTimer=setTimeout(()=>$('workspace-toast').hidden=true,3500); }
 function persist() {
  try { localStorage.setItem(storageKey,JSON.stringify(saved)); }
  catch { $('storage-error').textContent='Browser storage is unavailable. Changes last only until this page closes.'; $('storage-error').hidden=false; }
 }
 function loadSaved() {
  try {
   const value=JSON.parse(localStorage.getItem(storageKey)||'null');
   if(value && ['viewed','collapsed','threads','notes'].every(k=>Array.isArray(value[k])))saved=value;
  } catch { $('storage-error').textContent='Saved demo state could not be read. Starting a new session.'; $('storage-error').hidden=false; }
 }
 function highlight(text) {
  return text.split(/('(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*"|\b(?:export|import|from|interface|class|private|const|return|if|try|catch|finally|throw|new|async|await|void|number|boolean|undefined|false|true)\b)/g).map((part,i)=>i%2?`<span class="${/^['"]/.test(part)?'token-string':'token-keyword'}">${esc(part)}</span>`:esc(part)).join('');
 }
 function filteredFiles() {
  const term=$('file-filter').value.toLowerCase();
  return data.files.map((file,index)=>({file,index})).filter(({file})=>file.path.toLowerCase().includes(term)&&(!$('unviewed-only').checked||!saved.viewed.includes(file.path)));
 }
 function renderProgress() {
  const count=data.files.filter(f=>saved.viewed.includes(f.path)).length;
  $('viewed-progress').textContent=`${count} / ${data.files.length} files viewed`;
  $('sidebar-progress').textContent=`${count} of ${data.files.length} files viewed`;
  $('collapse-all').textContent=data.files.every(f=>saved.collapsed.includes(f.path))?'Expand all':'Collapse all';
  $('file-progress').value=count; $('file-progress').max=data.files.length;
  $('note-count').textContent=saved.notes.length;
 }
 function renderTree() {
  $('file-tree').innerHTML=filteredFiles().map(({file,index})=>`<button class="file-link" data-jump="${index}" aria-current="${index===activeFile}"><span class="${saved.viewed.includes(file.path)?'viewed-icon':''}">${saved.viewed.includes(file.path)?'✓':'◇'}</span><span><span class="file-name">${esc(basename(file.path))}</span><span class="file-dir">${esc(file.path.split('/').slice(0,-1).join('/'))}</span></span><span class="file-type">${file.status==='added'?'A':'M'}</span></button>`).join('')||'<p class="muted">No matching files.</p>';
 }
 function visibleRows(index) {
  const file=data.files[index], mode=full.get(index);
  if(mode)return file.rows.filter(r=>mode==='base'?r.old!==null:r.new!==null);
  return file.rows;
 }
 function diffEntries(index) {
  const file=data.files[index],mode=full.get(index),extra=revealed.get(index)||new Set();
  const rows=visibleRows(index),changed=file.rows.filter(r=>r.kind!=='context').map(r=>r.id);
  const visible=r=>mode||r.kind!=='context'||extra.has(r.id)||changed.some(id=>Math.abs(id-r.id)<=3);
  const entries=[];
  for(let i=0;i<rows.length;){
   if(visible(rows[i])){entries.push(rows[i++]);continue;}
   const start=i;while(i<rows.length&&!visible(rows[i]))i++;
   entries.push({gap:true,start:rows[start].id,end:rows[i-1].id,count:i-start});
  }
  return entries;
 }
 function gapHTML(index,gap,pair=''){
  return `<button class="context-gap" ${pair} data-expand="${index}" data-start="${gap.start}" data-end="${gap.end}">↕ Show ${Math.min(12,gap.count)} more lines <span>(${gap.count} hidden)</span></button>`;
 }
 function splitRows(index,entries){
  const pairs=[];
  for(let i=0;i<entries.length;){
   const row=entries[i];
   if(row.gap||row.kind==='context'){pairs.push([row,row]);i++;continue;}
   const removed=[],added=[];
   while(i<entries.length&&!entries[i].gap&&entries[i].kind!=='context'){
    const changed=entries[i++];(changed.kind==='delete'?removed:added).push(changed);
   }
   for(let n=0;n<Math.max(removed.length,added.length);n++)pairs.push([removed[n],added[n]]);
  }
  return `<div class="split-diff">${['base','head'].map((side,lane)=>`<section class="split-pane" aria-label="${side==='base'?'Base':'Head'} version"><div class="split-heading">${side==='base'?'Base':'Head'} <code>${esc(side==='base'?data.base:data.head)}</code></div><div class="split-line-list">${pairs.map((pair,n)=>{
   const row=pair[lane];
   if(!row)return `<div class="split-blank" data-pair="${n}" aria-hidden="true"></div>`;
   if(row.gap)return gapHTML(index,row,`data-pair="${n}"`);
   const number=side==='base'?row.old:row.new;
   return `<div class="code-row split-cell ${row.kind}" data-pair="${n}" data-side="${side}" data-file="${index}" data-row="${row.id}"><button class="line-number" data-line="${side}" aria-label="Select ${side} line ${number}">${number}</button><span class="line-sign">${row.kind==='add'?'+':row.kind==='delete'?'−':' '}</span><code>${highlight(row.text)||' '}</code></div>`;
  }).join('')}</div></section>`).join('')}</div>`;
 }
 function fileRows(index) {
  const mode=full.get(index),entries=diffEntries(index);
  if(diffLayout==='split'&&!mode)return splitRows(index,entries);
  return entries.map(row=>{
   if(row.gap)return gapHTML(index,row);
   const kind=mode?'context':row.kind;
   return `<div class="code-row ${kind}" data-file="${index}" data-row="${row.id}"><button class="line-number" data-line="base" aria-label="Select base line ${row.old??'not present'}" ${row.old===null?'disabled':''}>${row.old??''}</button><button class="line-number" data-line="head" aria-label="Select head line ${row.new??'not present'}" ${row.new===null?'disabled':''}>${row.new??''}</button><span class="line-sign">${kind==='add'?'+':kind==='delete'?'−':' '}</span><code>${highlight(row.text)||' '}</code></div>`;
  }).join('')||'<p class="empty-code">This file does not exist at this revision.</p>';
 }
 function renderFiles() {
  $('files').innerHTML=filteredFiles().map(({file,index})=>{
   const collapsed=saved.collapsed.includes(file.path),mode=full.get(index);
   return `<article class="file-card ${collapsed?'collapsed':''}" id="file-${index}"><header class="file-header"><button class="file-collapse" data-collapse="${index}" aria-expanded="${!collapsed}"><span aria-hidden="true">${collapsed?'›':'⌄'}</span><code>${esc(file.path)}</code></button><span class="file-stats"><span class="added">+${file.additions}</span><span class="deleted">−${file.deletions}</span></span><div class="file-actions">${file.status==='added'?'<span class="file-status">Added</span>':''}${mode?`<select data-revision="${index}" aria-label="Full file revision"><option value="head" ${mode==='head'?'selected':''}>Head ${esc(data.head)}</option><option value="base" ${mode==='base'?'selected':''}>Base ${esc(data.base)}</option></select>`:''}<button data-full="${index}" aria-pressed="${!!mode}">${mode?'Back to diff':'Full file'}</button><label><input data-viewed="${index}" type="checkbox" ${saved.viewed.includes(file.path)?'checked':''}>Viewed</label></div></header><div class="code-lines" ${collapsed?'hidden':''}>${collapsed?'':fileRows(index)}</div></article>`;
  }).join('')||'<div class="empty-code"><h3>No files to show</h3><p>Clear the file filter or turn off Only unviewed.</p><button class="button" id="reset-filters">Show all files</button></div>';
  paintSelection();renderTree();renderProgress();alignSplitRows();
 }
 function paintSelection() {
  for(const row of document.querySelectorAll('.code-row'))row.classList.toggle('selected',!!selection&&Number(row.dataset.file)===selection.file&&selection.ids.includes(Number(row.dataset.row))&&(!row.dataset.side||row.dataset.side===selection.side));
  $('selection-bar').hidden=!selection||tab!=='code';
  $('ask-selection').textContent=currentThread()||activeContexts().length?'Add selection to chat':'Ask about selection';
  if(selection)$('selection-label').textContent=`${basename(data.files[selection.file].path)} · ${selection.label}`;
 }
 function makeSelection(file,start,end,side='head',sideOnly=false) {
  const ids=visibleRows(file).filter(row=>row.id>=Math.min(start,end)&&row.id<=Math.max(start,end)&&(!sideOnly||(side==='base'?row.old:row.new)!==null)).map(row=>row.id);
  const rows=data.files[file].rows.filter(r=>ids.includes(r.id));
  const lines=rows.map(r=>side==='base'?r.old:r.new).filter(n=>n!==null);
  const other=rows.some(r=>side==='base'?r.old===null:r.new===null);
  const label=(lines.length?`${side==='base'?'Base':'Head'} L${lines[0]}${lines.length>1?'–'+lines.at(-1):''}`:'Changed lines')+(other?' + opposite-side changes':'');
  return {file,ids,side,label,path:data.files[file].path,head:data.head,base:data.base,
   snippet:rows.map(r=>`${r.kind==='add'?'+':r.kind==='delete'?'-':' '} ${r.text}`).join('\n')};
 }
 function selectRows(file,start,end,side) {selection=makeSelection(file,start,end,side,diffLayout==='split'&&!full.has(file));paintSelection();}
 function setTab(value) {
  tab=value;$('code-view').hidden=tab!=='code';$('ai-view').hidden=tab!=='review';
  $('code-tab').setAttribute('aria-pressed',tab==='code');$('review-tab').setAttribute('aria-pressed',tab==='review');
  const url=new URL(location.href);url.searchParams.set('tab',tab);history.replaceState(null,'',url);paintSelection();updateLayout();
 }
 function jump(file,ids=null,side='head') {
  activeFile=file;$('file-filter').value='';$('unviewed-only').checked=false;
  saved.collapsed=saved.collapsed.filter(p=>p!==data.files[file].path);persist();setTab('code');
  if(ids){full.delete(file);const extra=revealed.get(file)||new Set();for(const id of ids)extra.add(id);revealed.set(file,extra);selection=makeSelection(file,ids[0],ids.at(-1),side);}
  $('code-view').classList.remove('files-open');$('files-toggle').setAttribute('aria-expanded','false');renderFiles();updateLayout();
  const target=ids?document.querySelector(`[data-file="${file}"][data-row="${ids[0]}"]`):$(`file-${file}`);
  target?.scrollIntoView({block:'start',behavior:'instant'});
 }
 function showRail(kind='chat') {
  $('conversation').hidden=false;$('workspace-body').classList.add('rail-open');$('chat-toggle').setAttribute('aria-expanded','true');
  $('chat-content').hidden=kind!=='chat';$('notes-content').hidden=kind!=='notes';$('rail-title').textContent=kind==='chat'?'Ask about this code':'Private notes';
  if(kind==='chat')renderChat();else renderNotes();updateLayout();
 }
 function closeRail() {$('conversation').hidden=true;$('workspace-body').classList.remove('rail-open');$('chat-toggle').setAttribute('aria-expanded','false');$('chat-toggle').focus();updateLayout();}
 function currentThread(){return saved.threads.find(t=>t.id===threadId);}
 let draftContexts=[];
 const contextsOf=value=>Array.isArray(value?.contexts)?value.contexts:value?.context?[value.context]:[];
 const contextKey=context=>JSON.stringify([context.path,context.base,context.head,context.side,context.ids]);
 const activeContexts=()=>currentThread()?contextsOf(currentThread()):draftContexts;
 function preserveMessageContexts(thread){
  const original=contextsOf(thread);
  for(const message of thread.messages)if(!Array.isArray(message.contexts))message.contexts=structuredClone(original);
 }
 function beginThread(context=null){threadId=null;draftContexts=context?[structuredClone(context)]:[];$('question').value='';showRail();$('question').focus({preventScroll:true});}
 function attachContext(context){
  if(!context)return;
  const thread=currentThread(),contexts=structuredClone(activeContexts());
  if(!contexts.some(c=>contextKey(c)===contextKey(context)))contexts.push(structuredClone(context));
  if(thread){preserveMessageContexts(thread);thread.contexts=contexts;persist();}else draftContexts=contexts;
  showRail();$('question').focus({preventScroll:true});
 }
 function contextHTML(context,index) {
  return `<div class="context-attachment"><div class="context-heading"><button data-context-jump="${index}">${esc(basename(context.path))} · ${esc(context.label)}</button><button class="context-remove" data-remove-context="${index}" aria-label="Remove code context: ${esc(basename(context.path))} ${esc(context.label)}" title="Remove from future questions. Earlier messages keep their code context.">×</button></div><p>${esc(context.path)} · ${esc(context.side==='base'?context.base:context.head)}</p><details><summary>Selected code · ${context.ids.length} lines</summary><pre>${esc(context.snippet)}</pre></details></div>`;
 }
 function messageContextHTML(message,index,thread){
  const contexts=Array.isArray(message.contexts)?message.contexts:contextsOf(thread);
  if(message.role!=='user'||!contexts.length)return '';
  return `<details class="message-contexts"><summary>${contexts.length} code ${contexts.length===1?'selection':'selections'} + PR diff</summary>${contexts.map((context,n)=>`<button class="text-button" data-message-context="${index}" data-context-index="${n}">${esc(basename(context.path))} · ${esc(context.label)}</button>`).join('')}</details>`;
 }
 function renderChat() {
  const thread=currentThread(),contexts=activeContexts();
  $('thread-picker').innerHTML='<option value="">New conversation</option>'+saved.threads.map(t=>`<option value="${esc(t.id)}" ${t.id===threadId?'selected':''}>${esc((contextsOf(t)[0]?basename(contextsOf(t)[0].path):'PR')+' · '+t.messages[0].text.slice(0,42))}</option>`).join('');
  $('chat-context').innerHTML=contexts.length?`<p class="context-count">${contexts.length} code ${contexts.length===1?'selection':'selections'} + PR diff</p>`+contexts.map(contextHTML).join(''):`<strong>Entire pull request</strong><p>Example comparison ${esc(data.base)} → ${esc(data.head)}</p>`;
  $('messages').innerHTML=thread?thread.messages.map((m,index)=>`<article class="message ${m.role}"><header>${m.role==='user'?'You':'AI preview'}${m.role==='assistant'?'<span>Scripted reply</span>':''}</header>${messageContextHTML(m,index,thread)}<p>${esc(m.text)}</p>${m.role==='assistant'?`<button class="text-button" data-save-message="${index}">Save to private notes</button>`:''}</article>`).join(''):`<div class="chat-empty"><strong>${contexts.length?'Start with a question.':'A second pair of eyes.'}</strong><p>${contexts.length?'Ask about these lines. Add more selections from any file to keep exploring in this conversation.':'Select lines in the diff for a focused conversation, or ask about the whole change.'}</p></div>`;
  $('question').placeholder=thread?'Ask a follow-up…':contexts.length?'Ask about the selected code…':'Ask about this pull request…';
  $('ask-selection').textContent=thread||contexts.length?'Add selection to chat':'Ask about selection';
  const last=$('messages').lastElementChild;if(last)$('messages').scrollTop+=last.getBoundingClientRect().top-$('messages').getBoundingClientRect().top;
 }
 function demoAnswer(question,contexts) {
  const context=contexts.at(-1);
  const q=question.toLowerCase(),path=context?.path||'';
  const prefix=(contexts.length>1?`${contexts.length} selections attached. This scripted reply focuses on the most recent.\n\n`:'')+(context?`About ${basename(path)} (${context.label}):\n\n`:'');
  if(/pull in|fetch|more context|read.*file|find.*caller/.test(q))return 'The connected assistant will be able to fetch more code at this review’s pinned revision when you ask, and show which files it read. This offline demo cannot fetch repository files or run a model.';
  if(/test|cover|verify/.test(q))return prefix+'The sample test covers a rejected send, retaining one event, and a successful retry.\n\nUseful next cases: push a new event while send is pending; call flush twice concurrently; reject the first send and verify the original batch stays ahead of new events. Also exercise rejection through the timer callback, where the returned promise is not awaited.\n\nThese are suggested checks for the example; no tests have been run.';
  if(/edge|risk|error|reject|unhandled|problem/.test(q))return prefix+'The direct caller can catch a rejected flush(), but start() and push() discard its promise. The new catch restores the batch and rethrows, so a failed timer-triggered send can still produce an unhandled rejection.\n\nAlso, repeated failures can grow the in-memory queue, and a request that never settles leaves flushing true. Those need an explicit transport policy; this example does not establish one.';
  if(/order|unshift|why|instead/.test(q))return prefix+'unshift(...batch) puts the failed batch back at the front. If event A is in flight and B arrives, a failure leaves [A, B], so the next attempt preserves their queue order. push(...batch) would leave [B, A].\n\nThe flushing guard prevents two flushes from removing batches at the same time. It does not guarantee exactly-once delivery: the server may accept a request before the client observes a network failure.';
  if(/explain|what.*do|how|change|summari/.test(q)){
   if(path.endsWith('.test.ts'))return prefix+'The added test makes the first send reject. It checks that flush() rejects and one item remains queued, then retries and checks the item was sent again. It exercises the direct flush() path; it does not cover timer-triggered rejection or concurrent pushes.';
   if(path.endsWith('.md'))return prefix+'The new guide describes batching defaults and the in-memory retry behavior. It says only one request runs at a time and that stop() does not drain pending items. There is no claim of durable storage or exactly-once delivery.';
   return prefix+'Previously, flush() removed a batch before sending it. A rejected send lost those events from the queue.\n\nThe example adds a flushing guard, restores a rejected batch at the front of the queue, and resets the guard in finally. New arrivals stay queued while a request is in flight.\n\nThis is a scripted explanation of the example file, not a model analysis of arbitrary selected lines.';
  }
  return 'This prototype saves your question and preserves the conversation context, but it does not call an AI model. Try “Explain this change”, “What edge cases should I check?”, or “What tests would help?” to explore the scripted flows.';
 }
 function ask(question) {
  question=question.trim();if(!question)return;
  let thread=currentThread();
  if(!thread){thread={id:crypto.randomUUID(),contexts:structuredClone(draftContexts),messages:[]};saved.threads.push(thread);threadId=thread.id;}
  const contexts=structuredClone(contextsOf(thread));
  thread.messages.push({role:'user',text:question,contexts},{role:'assistant',text:demoAnswer(question,contexts),contexts});
  persist();$('question').value='';renderChat();
 }
 function renderNotes() {
  $('saved-notes').innerHTML=saved.notes.length?saved.notes.map((note,index)=>{
   const contexts=contextsOf(note);
   return `<article class="saved-note"><small>${contexts.length?esc(contexts.length+' code '+(contexts.length===1?'selection':'selections')):'Pull request note'} · ${esc(data.head)}</small><p>${esc(note.text)}</p><div class="note-actions">${contexts.map((context,n)=>`<button class="text-button" data-note-jump="${index}" data-context-index="${n}">${esc(basename(context.path))} · ${esc(context.label)}</button>`).join('')}<button class="text-button" data-note-edit="${index}">Edit</button><button class="text-button" data-note-delete="${index}">Delete</button></div></article>`;
  }).join(''):'<p class="muted">No notes yet. Save an answer or write your own.</p>';
  renderProgress();
 }
 let editingNote=null;
 function renderReview() {
  $('review-count').textContent=data.reviewReady?'1 finding':'Not run';
  if(!data.reviewReady){$('ai-view').innerHTML='<div class="review-empty"><h2>Start with the code.</h2><p>No AI review has been generated for this example. You can still explore every file, mark your progress and ask questions about selected lines.</p><button class="button primary" data-show-code>Explore code</button> <button class="button" id="generate-demo">Generate AI review</button><p class="muted">The demo button reveals a prepared sample report. No model is called.</p></div>';return;}
  $('ai-view').innerHTML=`<div class="review-meta"><span>Example AI review</span><span>Compared ${esc(data.base)} → ${esc(data.head)}</span><span>Runtime checks not run</span></div><h2>A failed send no longer empties the queue.</h2><p class="review-intro">This change keeps telemetry available for the next flush when a request fails. It also prevents concurrent flushes from taking overlapping work.</p><div class="before-after"><div><h3>Before</h3><p>Remove events → send fails → events are lost from memory.</p></div><div><h3>After</h3><p>Remove events → send fails → put them back at the front for retry.</p></div></div><div class="review-route"><button class="button" data-show-code>Explore all 3 changed files</button><span class="muted">Implementation, retry test, and delivery documentation</span></div><h3>One point to investigate</h3><article class="finding"><div class="finding-heading"><span class="chip warn">P2</span><h4>Scheduled flushes still discard rejected promises</h4></div><p>The batch is restored on failure, but <code>flush()</code> rethrows. The timer callback and <code>push()</code> do not handle that rejection. Check the error policy for those callers before relying on background retry.</p><button class="button" id="finding-code">Inspect code · batch.ts</button><button class="button" id="finding-ask">Ask about this</button></article><h3>Suggested reading order</h3><p class="review-intro">Start with the flush guard and retry order, then inspect its callers. The test covers one rejected send; it leaves concurrent arrivals and scheduled errors to investigate.</p><p class="muted">Synthetic review of the example code. No repository or runtime validation was performed.</p>`;
 }
 function findingSelection(){const file=data.files[0];const rows=file.rows.filter(r=>r.new>=34&&r.new<=50);return makeSelection(0,rows[0].id,rows.at(-1).id);}
 document.addEventListener('click',event=>{
  if(!data)return;
  const button=event.target.closest('button');if(!button)return;
  const d=button.dataset;
  if(d.jump!==undefined)jump(Number(d.jump));
  if(d.collapse!==undefined){const path=data.files[Number(d.collapse)].path;saved.collapsed=saved.collapsed.includes(path)?saved.collapsed.filter(p=>p!==path):[...saved.collapsed,path];persist();renderFiles();document.querySelector(`[data-collapse="${d.collapse}"]`)?.focus({preventScroll:true});}
  if(d.expand!==undefined){const index=Number(d.expand),extra=revealed.get(index)||new Set(),start=Number(d.start),end=Number(d.end);for(let i=start;i<=Math.min(start+11,end);i++)extra.add(i);revealed.set(index,extra);renderFiles();document.querySelector(`[data-file="${index}"][data-row="${start}"] .line-number:not(:disabled)`)?.focus({preventScroll:true});}
  if(d.full!==undefined){const index=Number(d.full);full.has(index)?full.delete(index):full.set(index,'head');saved.collapsed=saved.collapsed.filter(p=>p!==data.files[index].path);persist();renderFiles();document.querySelector(`[data-full="${index}"]`)?.focus({preventScroll:true});}
  if(d.prompt)ask(d.prompt);
  if(d.saveMessage!==undefined){const t=currentThread(),message=t.messages[Number(d.saveMessage)];const contexts=structuredClone(Array.isArray(message.contexts)?message.contexts:contextsOf(t));saved.notes.push({text:'[Scripted demo reply]\n'+message.text,contexts,context:contexts.at(-1)||null});persist();renderProgress();notify('Saved to private notes.');}
  if(d.removeContext!==undefined){const thread=currentThread(),contexts=structuredClone(activeContexts()),removed=contexts.splice(Number(d.removeContext),1)[0];if(thread){preserveMessageContexts(thread);thread.contexts=contexts;persist();}else draftContexts=contexts;if(selection&&removed&&contextKey(selection)===contextKey(removed))selection=null;paintSelection();renderChat();$('question').focus({preventScroll:true});notify('Code detached. Your draft and conversation are kept.');}
  if(d.contextJump!==undefined){const context=activeContexts()[Number(d.contextJump)];if(context){jump(context.file,context.ids,context.side);if(innerWidth<=750)closeRail();}}
  if(d.messageContext!==undefined){const thread=currentThread(),message=thread.messages[Number(d.messageContext)],context=(message.contexts||contextsOf(thread))[Number(d.contextIndex)];if(context){jump(context.file,context.ids,context.side);if(innerWidth<=750)closeRail();}}
  if(d.noteJump!==undefined){const c=contextsOf(saved.notes[Number(d.noteJump)])[Number(d.contextIndex)];jump(c.file,c.ids,c.side);if(innerWidth<=750)closeRail();}
  if(d.noteDelete!==undefined){saved.notes.splice(Number(d.noteDelete),1);editingNote=null;$('note-text').value='';persist();renderNotes();}
  if(d.noteEdit!==undefined){editingNote=Number(d.noteEdit);$('note-text').value=saved.notes[editingNote].text;$('note-text').focus();}
  if(d.showCode!==undefined)setTab('code');
  if(button.id==='generate-demo'){data.reviewReady=true;renderReview();notify('Prepared example review shown.');}
  if(button.id==='finding-code'){selection=findingSelection();jump(0,selection.ids);}
  if(button.id==='finding-ask'){const c=findingSelection();jump(0,c.ids);attachContext(c);ask('What happens to rejected promises here?');}
  if(button.id==='reset-filters'){$('file-filter').value='';$('unviewed-only').checked=false;renderFiles();}
 });
 document.addEventListener('change',event=>{
  const d=event.target.dataset;if(!data)return;
  if(d.viewed!==undefined){const file=data.files[Number(d.viewed)];saved.viewed=saved.viewed.filter(p=>p!==file.path);saved.collapsed=saved.collapsed.filter(p=>p!==file.path);if(event.target.checked){saved.viewed.push(file.path);saved.collapsed.push(file.path);}persist();renderFiles();document.querySelector(`[data-viewed="${d.viewed}"]`)?.focus({preventScroll:true});}
  if(d.revision!==undefined){full.set(Number(d.revision),event.target.value);renderFiles();document.querySelector(`[data-revision="${d.revision}"]`)?.focus({preventScroll:true});}
 });
 let drag=null;
 document.addEventListener('pointerdown',event=>{
  const gutter=event.target.closest('[data-line]');if(!gutter||gutter.disabled||event.button!==0)return;
  const row=gutter.closest('.code-row'),file=Number(row.dataset.file),id=Number(row.dataset.row),side=gutter.dataset.line;
  const start=event.shiftKey&&selection?.file===file&&selection.side===side?selection.ids[0]:id;
  drag={file,start,side};selectRows(file,start,id,side);event.preventDefault();gutter.focus({preventScroll:true});
 });
 document.addEventListener('pointerover',event=>{if(!drag)return;const row=event.target.closest('.code-row');if(row&&Number(row.dataset.file)===drag.file&&(!row.dataset.side||row.dataset.side===drag.side))selectRows(drag.file,drag.start,Number(row.dataset.row),drag.side);});
 document.addEventListener('pointerup',()=>{drag=null;});
 document.addEventListener('pointercancel',()=>{drag=null;});
 document.addEventListener('click',event=>{const gutter=event.target.closest('[data-line]');if(!gutter||event.detail!==0||gutter.disabled)return;const row=gutter.closest('.code-row'),file=Number(row.dataset.file),id=Number(row.dataset.row);selectRows(file,event.shiftKey&&selection?.file===file&&selection.side===gutter.dataset.line?selection.ids[0]:id,id,gutter.dataset.line);});
 document.addEventListener('mouseup',()=>{
  const text=window.getSelection();if(!text||text.isCollapsed||!text.toString().trim())return;
  const parent=node=>node?.nodeType===Node.ELEMENT_NODE?node:node?.parentElement;
  const a=parent(text.anchorNode)?.closest('.code-row'),b=parent(text.focusNode)?.closest('.code-row');
  if(a&&b&&a.dataset.file===b.dataset.file&&a.dataset.side===b.dataset.side)selectRows(Number(a.dataset.file),Number(a.dataset.row),Number(b.dataset.row),a.dataset.side||(full.get(Number(a.dataset.file))==='base'?'base':'head'));
 });
 $('files-toggle').addEventListener('click',()=>{
  const overlay=innerWidth<=750||(innerWidth<=1150&&!$('conversation').hidden);
  if(overlay){$('code-view').classList.remove('files-hidden');$('code-view').classList.toggle('files-open');}
  else $('code-view').classList.toggle('files-hidden');
  updateLayout();
 });
 $('diff-layout').addEventListener('change',event=>{
  layoutPreference=event.target.value;
  try{localStorage.setItem('pr-code-diff-layout',layoutPreference);}catch{notify('Diff layout applies for this session; browser storage is unavailable.');}
  updateLayout();
 });
 new ResizeObserver(updateLayout).observe(document.querySelector('.diff-column'));
 $('reset-demo').addEventListener('click',()=>{saved={viewed:[],collapsed:[],threads:[],notes:[]};selection=null;threadId=null;draftContexts=[];editingNote=null;full.clear();revealed.clear();$('file-filter').value='';$('unviewed-only').checked=false;$('note-text').value='';$('question').value='';persist();renderFiles();closeRail();notify('This example’s progress, conversations and notes were cleared.');});
 $('file-filter').addEventListener('input',renderFiles);$('unviewed-only').addEventListener('change',renderFiles);
 $('wrap-lines').addEventListener('change',event=>{$('files').classList.toggle('wrap-code',event.target.checked);alignSplitRows();});
 $('collapse-all').addEventListener('click',()=>{const all=data.files.every(f=>saved.collapsed.includes(f.path));saved.collapsed=all?[]:data.files.map(f=>f.path);$('collapse-all').textContent=all?'Collapse all':'Expand all';persist();renderFiles();});
 $('code-tab').addEventListener('click',()=>setTab('code'));$('review-tab').addEventListener('click',()=>setTab('review'));
 $('chat-toggle').addEventListener('click',()=>{showRail();$('question').focus({preventScroll:true});});$('notes-toggle').addEventListener('click',()=>showRail('notes'));$('close-rail').addEventListener('click',closeRail);
 $('ask-selection').addEventListener('click',()=>{attachContext(selection);$('selection-bar').hidden=true;window.getSelection()?.removeAllRanges();});
 $('clear-selection').addEventListener('click',()=>{selection=null;paintSelection();});$('new-thread').addEventListener('click',()=>beginThread());
 $('thread-picker').addEventListener('change',event=>{threadId=event.target.value||null;draftContexts=[];$('question').value='';renderChat();});
 $('chat-form').addEventListener('submit',event=>{event.preventDefault();ask($('question').value);});
 $('question').addEventListener('keydown',event=>{if(event.key==='Enter'&&(event.metaKey||event.ctrlKey)){event.preventDefault();ask($('question').value);}});
 $('note-form').addEventListener('submit',event=>{event.preventDefault();const text=$('note-text').value.trim();if(!text)return;if(editingNote!==null){saved.notes[editingNote].text=text;editingNote=null;}else saved.notes.push({text,context:selection?structuredClone(selection):null});persist();$('note-text').value='';renderNotes();notify('Private note saved.');});
 document.addEventListener('keydown',event=>{if(event.key==='Escape'){if(!$('conversation').hidden)closeRail();else {selection=null;paintSelection();}}});
 async function init(){
  try{
   const response=await fetch('/api/code-workspace?demo='+encodeURIComponent(params.get('demo')||'ready'));
   if(!response.ok)throw new Error('The example could not be loaded. Return to PR reviews and open it again.');
   data=await response.json();storageKey=`pr-code-demo-v1:${data.repository}:${data.number}:${data.base}:${data.head}`;loadSaved();
   $('pr-identity').textContent=`${data.repository} #${data.number}`;$('pr-title').textContent=data.title;$('pr-author').textContent=`${data.author} wants to merge 1 example commit`;
   $('comparison').innerHTML=`<code>${esc(data.base)}</code> → <code>${esc(data.head)}</code>`;$('file-count').textContent=data.files.length;
   $('diff-totals').innerHTML=`<span class="added">+${data.files.reduce((sum,f)=>sum+f.additions,0)}</span><span class="deleted">−${data.files.reduce((sum,f)=>sum+f.deletions,0)}</span>`;
   $('scenario-switch').href=`?demo=${data.reviewReady?'empty':'ready'}&tab=${data.reviewReady?'code':'review'}`;$('scenario-switch').textContent=data.reviewReady?'Try without an AI review':'Try with an AI review';
   renderReview();renderFiles();setTab(tab);
  }catch(error){$('load-error').textContent=error.message;$('load-error').hidden=false;$('workspace-body').hidden=true;}
 }
 init();
})();
