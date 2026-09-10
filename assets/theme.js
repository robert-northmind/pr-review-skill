// Apply before the stylesheet paints; System follows later OS theme changes.
(()=>{
 const key='pr-inbox-theme', choices=['system','light','dark'];
 const system=window.matchMedia('(prefers-color-scheme: dark)');
 let preference='system';
 try{const stored=localStorage.getItem(key);if(choices.includes(stored))preference=stored;}catch{}
 function apply(){
  document.documentElement.dataset.theme=preference==='system'?(system.matches?'dark':'light'):preference;
  const control=document.getElementById('theme');if(control)control.value=preference;
 }
 apply();
 system.addEventListener('change',()=>{if(preference==='system')apply();});
 document.addEventListener('DOMContentLoaded',()=>{
  apply();document.getElementById('theme').addEventListener('change',event=>{
   preference=choices.includes(event.target.value)?event.target.value:'system';
   try{localStorage.setItem(key,preference);}catch{}
   apply();
  });
 });
 window.addEventListener('storage',event=>{if(event.key===key||event.key===null){preference=choices.includes(event.newValue)?event.newValue:'system';apply();}});
})();
