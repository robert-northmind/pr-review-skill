
// Walk layout: one scene at a time, and inspectable Mermaid participants.
(()=>{
 const root=document.documentElement;
 for(const figure of document.querySelectorAll('.mermaid-figure')){
  const svg=figure.querySelector('svg');if(!svg)continue;
  const notes=new Map([...figure.querySelectorAll('.mermaid-notes [data-participant]')].map(n=>[n.dataset.participant,n.textContent]));
  const actors=[...svg.querySelectorAll('[data-et="participant"]')];if(!actors.length)continue;
  const card=document.createElement('div');card.className='mermaid-card';card.hidden=true;card.setAttribute('aria-live','polite');
  const hint=document.createElement('p');hint.className='mermaid-hint';hint.textContent='Click a participant to highlight its messages. Click again to clear.';
  figure.querySelector('.mermaid-body').after(card,hint);
  let selected=null;
  const clear=()=>{svg.querySelectorAll('.dim,.hot').forEach(e=>e.classList.remove('dim','hot'));card.hidden=true;selected=null;};
  for(const actor of actors){
   // Mermaid wraps long names over several <text> lines.
   const id=actor.dataset.id,label=[...actor.querySelectorAll('text')].map(t=>t.textContent.trim()).filter(Boolean).join(' ')||id;
   actor.setAttribute('tabindex','0');actor.setAttribute('role','button');actor.setAttribute('aria-label',label);
   const select=()=>{
    if(selected===id)return clear();clear();selected=id;actor.classList.add('hot');
    svg.querySelectorAll('[data-et="message"]').forEach(line=>{if(line.dataset.from!==id&&line.dataset.to!==id){line.classList.add('dim');const t=line.previousElementSibling;if(t?.classList.contains('messageText'))t.classList.add('dim');}});
    card.textContent='';const strong=document.createElement('strong');strong.textContent=label;card.append(strong);
    const note=notes.get(label)||notes.get(id);if(note){const p=document.createElement('p');p.style.margin='2px 0 0';p.textContent=note;card.append(p);}
    card.hidden=false;
   };
   actor.addEventListener('click',select);
   actor.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();select();}});
  }
 }
 if(root.dataset.layout!=='walk')return;
 const scenes=[...document.querySelectorAll('.walk-scenes > section')];
 const links=[...document.querySelectorAll('.walk-rail a')];
 if(!scenes.length)return;
 const sceneOf=el=>el instanceof Element?el.closest('.walk-scenes > section'):null;
 const body=document.querySelector('.walk-body');
 const embedded=window.parent!==window;
 // Is the top of the scene area on screen? In the workspace iframe only the parent knows its
 // scroll position, so track it with an observer (its root is the top-level viewport).
 let bodyTopVisible=true;
 const sentinel=document.createElement('div');sentinel.className='walk-sentinel';body.before(sentinel);
 new IntersectionObserver(([e])=>{bodyTopVisible=e.isIntersecting;}).observe(sentinel);
 const revealTop=()=>{
  if(root.dataset.scenes!=='one')return;
  if(embedded){if(!bodyTopVisible)parent.postMessage({type:'workspace-report-scroll',top:Math.max(0,body.getBoundingClientRect().top+window.scrollY-8)},'*');}
  else if(body.getBoundingClientRect().top<0)window.scrollTo({top:body.getBoundingClientRect().top+window.scrollY-8});
 };
 const show=(scene,scroll)=>{
  if(!scene)return;
  scenes.forEach(s=>s.classList.toggle('walk-current',s===scene));
  links.forEach(a=>a.setAttribute('aria-current',String(a.getAttribute('href')==='#'+scene.id)));
  if(scroll)revealTop();
 };
 scenes.forEach((s,i)=>{const h=s.querySelector(':scope > h2, :scope > .walk-scene-head h2');if(h)h.dataset.sceneN=String(i+1).padStart(2,'0');});
 // Previous / next at the end of every scene, so a long scene doesn't need a scroll back up.
 const label=s=>links.find(a=>a.getAttribute('href')==='#'+s.id)?.textContent.trim()||s.dataset.section||'';
 scenes.forEach((s,i)=>{
  const nav=document.createElement('div');nav.className='walk-step';
  const make=(target,text,cls)=>{const b=document.createElement('button');b.type='button';b.className=cls;b.textContent=text;b.addEventListener('click',()=>{show(target,true);history.replaceState(null,'','#'+target.id);});return b;};
  if(i>0)nav.append(make(scenes[i-1],'← '+label(scenes[i-1]),'walk-prev'));
  if(i<scenes.length-1)nav.append(make(scenes[i+1],label(scenes[i+1])+' →','walk-next'));
  s.append(nav);
 });
 root.dataset.scenes='one';
 show(sceneOf(location.hash&&document.getElementById(location.hash.slice(1)))||scenes[0]);
 // Rail links switch scenes without jumping; other in-page links (verdict, finding badges)
 // switch to the target's scene and then scroll to the target as usual.
 document.addEventListener('click',e=>{
  const a=e.target.closest('a[href^="#"]');if(!a||root.dataset.scenes!=='one')return;
  const target=document.getElementById(a.getAttribute('href').slice(1));const scene=sceneOf(target);if(!scene)return;
  if(a.closest('.walk-rail')){e.preventDefault();e.stopImmediatePropagation();show(scene,true);history.replaceState(null,'','#'+scene.id);}
  else show(scene,false);
 },true);
 document.addEventListener('focusin',e=>{const scene=sceneOf(e.target);if(scene&&root.dataset.scenes==='one'&&!scene.classList.contains('walk-current'))show(scene);});
 window.addEventListener('hashchange',()=>show(sceneOf(document.getElementById(location.hash.slice(1)))));
 document.addEventListener('keydown',e=>{
  if(e.target.closest('input,textarea,select,button,summary,[role=button]')||e.metaKey||e.ctrlKey||e.altKey)return;
  const current=scenes.findIndex(s=>s.classList.contains('walk-current'));
  let next=-1;if(/^[1-9]$/.test(e.key))next=Number(e.key)-1;else if(e.key==='ArrowRight')next=current+1;else if(e.key==='ArrowLeft')next=current-1;
  if(next>=0&&next<scenes.length){e.preventDefault();show(scenes[next],true);history.replaceState(null,'','#'+scenes[next].id);}
 });
 // Toggle: all scenes on one page (find-in-page, print).
 const toggle=document.createElement('button');toggle.type='button';toggle.className='walk-all';toggle.textContent='Show all scenes';
 toggle.addEventListener('click',()=>{root.dataset.scenes=root.dataset.scenes==='one'?'all':'one';toggle.textContent=root.dataset.scenes==='one'?'Show all scenes':'One scene at a time';});
 document.querySelector('.walk-rail').append(toggle);
 window.addEventListener('beforeprint',()=>{root.dataset.scenes='all';});
})();
