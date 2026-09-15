'use strict';
const themeButton=document.getElementById('theme');
const modes=['system','light','dark'];let mode=0;
themeButton.addEventListener('click',()=>{mode=(mode+1)%modes.length;const selected=modes[mode];if(selected==='system')document.documentElement.removeAttribute('data-theme');else document.documentElement.setAttribute('data-theme',selected);themeButton.textContent='Theme: '+selected[0].toUpperCase()+selected.slice(1);});
for(const question of document.querySelectorAll('.question')){
 const buttons=[...question.querySelectorAll('.options button')];
 for(const [index,button] of buttons.entries())button.addEventListener('click',()=>{
  for(const other of buttons)other.removeAttribute('aria-pressed');button.setAttribute('aria-pressed','true');
  const correct=index===Number(question.dataset.answer);const feedback=question.querySelector('.feedback');
  feedback.dataset.result=correct?'correct':'incorrect';feedback.textContent='Selected '+String.fromCharCode(65+index)+'. '+(correct?'Correct.':'Not quite.');question.querySelector('.quiz-explanation').hidden=false;
 });
}
const reset=document.getElementById('reset-quiz');
if(reset)reset.addEventListener('click',()=>{for(const q of document.querySelectorAll('.question')){q.querySelectorAll('button').forEach(b=>b.removeAttribute('aria-pressed'));const f=q.querySelector('.feedback');f.textContent='';f.removeAttribute('data-result');q.querySelector('.quiz-explanation').hidden=true;}});

const findings=[...document.querySelectorAll('#review-findings > details.review-finding')];
if(findings.length>1){
 const toggle=document.createElement('button');
 toggle.type='button';toggle.id='toggle-findings';toggle.className='finding-controls';
 toggle.setAttribute('aria-controls','review-findings');
 const update=()=>{toggle.textContent=findings.every(f=>f.open)?'Collapse all findings':'Expand all findings';};
 toggle.addEventListener('click',()=>{const open=!findings.every(f=>f.open);for(const finding of findings)finding.open=open;update();});
 for(const finding of findings)finding.addEventListener('toggle',update);
 findings[0].before(toggle);update();
}

document.addEventListener('click', async event => {
 const button=event.target.closest('.copy-comment');
 if(!button)return;
 const section=button.closest('.review-comment'),source=section.querySelector('.comment-source'),status=section.querySelector('.copy-status');
 try{await navigator.clipboard.writeText(source.value);status.textContent='Copied';}
 catch{source.hidden=false;source.focus();source.select();status.textContent='Select and copy the Markdown below.';}
});
