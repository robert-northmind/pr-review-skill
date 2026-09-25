/** Pure settings/event translation, independently testable without credentials. */
// Chat reads the checkout (its working directory) plus explicitly named review
// files; a bare Read rule would allow any file on the machine.
const SAFE_PATH=/^\/[^\x00-\x1f()*?[\]{}]*$/;
export function readRules(readable) {
  const paths=(Array.isArray(readable)?readable:[]).filter(p=>typeof p==='string'&&SAFE_PATH.test(p)&&!p.split('/').includes('..'));
  return paths.flatMap(p=>{
    const target=p.endsWith('/')?`/${p}**`:`/${p}`;
    return ['Read','Grep','Glob'].map(name=>`${name}(${target})`);
  });
}
export function buildOptions(request) {
  const review=request.mode==='review';
  return {
    cwd:request.cwd,pathToClaudeCodeExecutable:request.binary,
    env:{...process.env}, // Normal HOME/keychain/CLAUDE_CONFIG_DIR, like T3.
    ...(request.model?{model:request.model}:{}),
    ...(request.effort?{effort:request.effort}:{}),
    ...(request.session_id?{resume:request.session_id}:{}),
    systemPrompt:review?{type:'preset',preset:'claude_code',append:request.instructions}:request.instructions,
    settingSources:review?['user','project','local']:[],
    includePartialMessages:true,
    permissionMode:review?'auto':'dontAsk',
    ...(review?{}:{
      tools:['Read','Glob','Grep','WebSearch','WebFetch'],
      allowedTools:[...readRules(request.context?.readable),'WebSearch','WebFetch','mcp__review-reads__git_read','mcp__review-reads__github_read'],
      disallowedTools:['Bash','Edit','Write','NotebookEdit','Agent','Skill'],
      settings:{disableAllHooks:true},strictMcpConfig:true,
    }),
  };
}
export function publicEvents(message,drafts=new Map()) {
  const events=[];
  if(message.type==='system'&&message.subtype==='init') events.push({type:'session',id:message.session_id});
  // Subagent output is activity, never the parent chat's answer.
  if(message.type==='stream_event'&&!message.parent_tool_use_id){
    const event=message.event;
    if(event.type==='message_start') drafts.clear();
    if(event.type==='content_block_delta'&&event.delta?.type==='text_delta'){
      drafts.set(event.index,(drafts.get(event.index)||'')+event.delta.text);
      events.push({type:'draft',text:[...drafts.values()].join('')});
    }
  }
  if(message.type==='assistant'){
    for(const block of message.message?.content||[]){
      if(block.type==='text'&&!message.parent_tool_use_id) events.push({type:'update',text:block.text});
      if(block.type==='tool_use'){
        events.push({type:'tool',text:'Using '+String(block.name).slice(0,80)});
        const kind=block.name==='WebSearch'?'web_search':block.name==='WebFetch'?'open_page':block.name==='mcp__review-reads__github_read'?'github_read':'repository_read';
        events.push({type:'read',details:{kind}});
      }
    }
  }
  if(message.type==='result') events.push({type:'result',completed:!message.is_error&&message.subtype==='success',answer:message.result||'',usage:message.usage||{}});
  // Never forward thinking blocks, tool arguments/results, error text or raw JSON.
  return events;
}
