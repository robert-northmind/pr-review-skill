import assert from 'node:assert/strict';
import {buildOptions,publicEvents} from '../../scripts/claude-runtime/protocol.mjs';
const request={mode:'review',cwd:'/tmp/review',binary:'/usr/local/bin/claude',model:'claude-opus-5-5',effort:'high',instructions:'review',session_id:'existing'};
const review=buildOptions(request);
assert.equal(review.pathToClaudeCodeExecutable,request.binary);
assert.equal(review.resume,'existing');assert.equal(review.effort,'high');
assert.equal(review.permissionMode,'auto');assert.equal(review.allowDangerouslySkipPermissions,undefined);
assert.deepEqual(review.settingSources,['user','project','local']);
assert.equal(review.env.HOME,process.env.HOME);
const chat=buildOptions({...request,mode:'chat',effort:''});
assert.equal(chat.effort,undefined);assert.equal(chat.permissionMode,'dontAsk');
assert.equal(chat.tools.includes('Bash'),false);assert.equal(chat.tools.includes('Read'),true);
assert.deepEqual(chat.settingSources,[]);assert.equal(chat.settings.disableAllHooks,true);
// Chat may read only its checkout plus explicitly named review files, never the whole disk.
assert.equal(chat.allowedTools.includes('Read'),false);
const scoped=buildOptions({...request,mode:'chat',context:{readable:['/runs/r1/','/claude/t.jsonl','relative/x','/bad/../x','/a(b)/','/star/*']}});
assert.deepEqual(scoped.allowedTools.filter(r=>/^(Read|Grep|Glob)\(/.test(r)),
  ['Read(//runs/r1/**)','Grep(//runs/r1/**)','Glob(//runs/r1/**)','Read(//claude/t.jsonl)','Grep(//claude/t.jsonl)','Glob(//claude/t.jsonl)']);
const events=publicEvents({type:'assistant',message:{content:[{type:'thinking',thinking:'secret'},{type:'tool_use',name:'Read',input:{file_path:'secret-path'}},{type:'text',text:'Public update'}]}});
assert.ok(events.some(e=>e.type==='update'&&e.text==='Public update'));assert.ok(!JSON.stringify(events).includes('secret'));
assert.deepEqual(publicEvents({type:'stream_event',parent_tool_use_id:'subagent',event:{type:'content_block_delta',index:0,delta:{type:'text_delta',text:'not parent answer'}}}),[]);
assert.equal(publicEvents({type:'result',subtype:'error_max_turns',is_error:true,errors:['private'],result:''})[0].completed,false);
console.log('Claude protocol: settings isolation, session resume, permissions, event redaction and subagent filtering passed.');
