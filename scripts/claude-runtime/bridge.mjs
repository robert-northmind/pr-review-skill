/** T3-style query sessions over the installed Claude Code executable.
 * Only normalized public events leave this process; no raw protocol/stderr.
 */
import {query, createSdkMcpServer, tool} from '@anthropic-ai/claude-agent-sdk';
import {z} from 'zod';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {createInterface} from 'node:readline';
import {randomUUID} from 'node:crypto';
import {buildOptions} from './protocol.mjs';
import {consumeSession} from './session.mjs';
const exec = promisify(execFile);
const emit = event => process.stdout.write(JSON.stringify(event)+'\n');
let active, started = false, interrupted = false;
// Messages sent before the session starts wait here until input() drains them.
const inputs = {queue:[], pending:new Set(), wake:null, send:null};
const lines = createInterface({input: process.stdin});

function readTools(request) {
  const context = request.context || {};
  const result = text => ({content:[{type:'text',text}]});
  const run = async (binary,args) => {
    try { const value = await exec(binary,args,{cwd:request.cwd,timeout:20000,maxBuffer:200000,env:{...process.env,GIT_TERMINAL_PROMPT:'0',GH_PROMPT_DISABLED:'1'}}); return result(value.stdout); }
    catch { return {...result('Read failed or exceeded the output limit.'),isError:true}; }
  };
  return createSdkMcpServer({name:'review-reads',version:'1.0.0',tools:[
    tool('git_read','Read a file at the pinned base/head revision, or the complete pinned diff. No code execution.',
      {operation:z.enum(['file','diff']),side:z.enum(['base','head']).optional(),path:z.string().optional()}, async args => {
        if (![context.base,context.head].every(value=>typeof value==='string'&&/^[a-f0-9]{40}$/.test(value))) return {...result('No verified revisions.'),isError:true};
        const prefix=['--no-pager','-c','core.fsmonitor=false','-c','core.hooksPath=/dev/null','-C',request.cwd];
        if(args.operation==='diff') return run('git',[...prefix,'diff','--no-ext-diff','--no-textconv',context.base,context.head,'--']);
        const path=args.path||'';
        if(!path||path.startsWith('/')||path.split('/').includes('..')||/[\x00-\x1f]/.test(path)) return {...result('Invalid repository path.'),isError:true};
        return run('git',[...prefix,'show',`${args.side==='base'?context.base:context.head}:${path}`]);
      }),
    tool('github_read','Read a GitHub issue or pull request in this PR repository, including comments.',
      {kind:z.enum(['issue','pr']),number:z.number().int().positive()}, async args => {
        if(!/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(context.repository||'')) return {...result('No verified repository.'),isError:true};
        return run(context.github_cli||'gh',[args.kind,'view',String(args.number),'--repo',context.repository,'--json','title,body,comments,state,url']);
      }),
  ]});
}
async function run(request) {
  if(!['chat','review'].includes(request.mode)) throw new Error('Invalid mode');
  const options = buildOptions(request);
  options.canUseTool = async () => {
    emit({type:'attention',text:'Claude needs permission or user input. The request was declined; the task may be blocked.'});
    return {behavior:'deny',message:'This dashboard does not accept interactive permission requests. Report the blocked work.'};
  };
  if(request.mode==='chat') {
    options.mcpServers={'review-reads':readTools(request)};
    options.systemPrompt+='\nUse git_read for pinned base/head files and diffs; use github_read for authenticated GitHub issue/PR reads. Shell execution is unavailable.';
  }
  let closed=false;
  const user=text=>({type:'user',message:{role:'user',content:text},parent_tool_use_id:null,session_id:request.session_id||'',uuid:randomUUID()});
  // T3 uses streaming user input with query(), allowing controls while running.
  // Dashboard messages join the queue; the CLI folds them into the running turn.
  async function* input() {
    yield user(request.prompt);
    while(!closed) {
      while(inputs.queue.length) yield inputs.queue.shift();
      await new Promise(resolve=>{inputs.wake=resolve;});
    }
  }
  inputs.send=text=>{
    const message=user(text);
    inputs.pending.add(message.uuid);
    inputs.queue.push(message);
    inputs.wake?.();
  };
  try {
    active=query({prompt:input(),options});
    if(interrupted) await active.interrupt();
    await consumeSession(active,emit,()=>interrupted,inputs);
  } finally {closed=true;inputs.wake?.();active?.close();lines.close();}
}
lines.on('line',line=>{
  try {
    const message=JSON.parse(line);
    if(!started){started=true;run(message).catch(()=>{emit({type:'error'});lines.close();process.exitCode=1;});}
    else if(message.type==='interrupt'){interrupted=true;active?.interrupt().catch(()=>{});}
    else if(message.type==='message'&&typeof message.text==='string'&&message.text) inputs.send?.(message.text);
  }catch{emit({type:'error'});lines.close();process.exitCode=1;}
});
process.on('SIGTERM',()=>{active?.close();process.exit(0);});
