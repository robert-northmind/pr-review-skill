"""Add local exploration affordances to source links in embedded reports only."""
BRIDGE = r'''<script>
(()=>{
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
    return body + BRIDGE
