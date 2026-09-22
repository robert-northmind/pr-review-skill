"""Add local exploration affordances to source links in embedded reports only."""
EMBED_STYLE = '''<style id="workspace-report-style">
html,body{margin:0!important;min-height:0!important;height:auto!important;background:var(--bg)!important}
body{display:flow-root;font:14px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
body>main{width:100%;max-width:none;margin:0;padding:0 0 32px}
.topbar,#theme,.pr-link{display:none!important}
h1{font-size:1.5rem;line-height:1.3;margin:0 0 16px}
.outcome{font-size:1rem;max-width:none}
</style>'''
BRIDGE = r'''<script>
(()=>{
 let lastHeight=0;
 const resize=()=>{const height=Math.ceil(Math.max(1,...[...document.body.children].filter(el=>el.getBoundingClientRect().height&&getComputedStyle(el).position!=='fixed').map(el=>el.getBoundingClientRect().bottom+window.scrollY+(parseFloat(getComputedStyle(el).marginBottom)||0))));if(height>0&&height!==lastHeight){lastHeight=height;parent.postMessage({type:'workspace-report-size',height},'*');}};
 const observer=new ResizeObserver(resize);
 observer.observe(document.body);
 for(const element of document.body.children)observer.observe(element);
 document.addEventListener('toggle',resize,true);
 window.addEventListener('message',event=>{
  if(event.source!==parent||event.data?.type!=='workspace-report-theme')return;
  const {theme,colors}=event.data;
  if(!['light','dark'].includes(theme))return;
  document.documentElement.dataset.theme=theme;
  for(const key of ['bg','panel','fg','muted','line','accent','soft']){
   if(typeof colors?.[key]==='string')document.documentElement.style.setProperty('--'+key,colors[key]);
  }
  resize();
 });
 parent.postMessage({type:'workspace-report-ready'},'*');
 resize();
 document.addEventListener('click',event=>{
  const anchor=event.target.closest('a[href^="#"]');
  if(!anchor)return;
  let target;try{target=document.getElementById(decodeURIComponent(anchor.hash.slice(1)));}catch{return;}
  if(target){event.preventDefault();parent.postMessage({type:'workspace-report-scroll',top:target.getBoundingClientRect().top+window.scrollY},'*');}
 });
 const sourceLink=anchor=>{try{const u=new URL(anchor.href);return u.hostname==='github.com'&&/^\/[^/]+\/[^/]+\/blob\/[0-9a-f]{40}\//.test(u.pathname)&&/^#L\d+(?:-L\d+)?$/.test(u.hash);}catch{return false;}};
 const send=(anchor,action)=>parent.postMessage({type:'workspace-code',action,url:anchor.href},'*');
 document.addEventListener('click',event=>{
  const anchor=event.target.closest('a');
  if(event.isTrusted&&anchor&&sourceLink(anchor)){event.preventDefault();send(anchor,'inspect');}
 });
 for(const anchor of document.querySelectorAll('a[href]')){
  if(!sourceLink(anchor))continue;
  anchor.title='Explore these lines in Code changes';
  const ask=document.createElement('button');ask.type='button';ask.textContent='Ask AI';
  ask.style.cssText='margin-left:8px;font:inherit;font-size:12px';
  ask.addEventListener('click',event=>{if(event.isTrusted)send(anchor,'ask');});
  anchor.after(ask);
 }
})();
</script>'''


def embed(body):
    # Appended after the report so links already exist. No report content is
    # interpolated into JavaScript; the parent validates every message/link.
    return body + EMBED_STYLE + BRIDGE
