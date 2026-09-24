import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {consumeSession} from '../../scripts/claude-runtime/session.mjs';

const result = answer => ({type:'result',subtype:'success',is_error:false,result:answer});
const system = (subtype, fields = {}) => ({type:'system',subtype,...fields});
const start = (id, extra = {}) => system('task_started', {task_id:id,is_backgrounded:true,...extra});
const done = (id, status = 'completed') => system('task_notification', {task_id:id,status});
const snapshot = tasks => system('background_tasks_changed', {tasks});
const run = async (messages, interrupted) => {
  const events = [];
  await consumeSession((async function* () {yield* messages;})(), e => events.push(e), interrupted);
  return events;
};
const answers = events => events.filter(e => e.type === 'result').map(e => e.answer);

// Reproduce PR #199: four reviewers, a monitoring task, then the lead yields.
// Resuming the generator after that result proves the bridge stayed connected.
let closed = false;
const events = [];
await consumeSession((async function* () {
  try {
    for (const id of ['correctness','contracts','security','runtime']) yield start(id);
    yield start('monitor', {ambient:true});
    yield result('Reviewers are running');
    assert.deepEqual(answers(events), []);
    assert.equal(closed, false);
    yield done('correctness');
    yield done('contracts');
    yield result('Still waiting for security and runtime');
    assert.deepEqual(answers(events), []);
    yield done('security');
    yield done('runtime');
    assert.deepEqual(answers(events), [], 'Task completion is not lead synthesis');
    yield {type:'assistant',message:{content:[{type:'text',text:'Building the report'}]}};
    yield result('Review notes are ready');
    assert.fail('The final result should close the iterator');
  } finally {closed = true;}
})(), e => events.push(e));
assert.equal(closed, true);
assert.deepEqual(answers(events), ['Review notes are ready']);
assert.ok(events.some(e => e.type === 'update' && e.text.includes('4 background task(s)')));

// Snapshot membership wins over potentially out-of-order task bookends.
assert.deepEqual(answers(await run([
  snapshot([{task_id:'worker'}]), start('worker'), result('Waiting'),
  snapshot([{task_id:'watcher',ambient:true}]), start('worker'), result('Finished'),
])), ['Finished']);
assert.deepEqual(answers(await run([
  snapshot([{task_id:'worker'}]), done('worker'), result('Still running'),
  snapshot([]), result('Finished'),
])), ['Finished']);

// Older CLIs: foreground work does not keep a finished turn open; a task
// explicitly moved into the background does. Failed/stopped tasks also settle.
assert.deepEqual(answers(await run([start('sync',{is_backgrounded:false}),result('Done')])), ['Done']);
assert.deepEqual(answers(await run([
  start('sync',{is_backgrounded:false}),
  system('task_updated',{task_id:'sync',patch:{is_backgrounded:true}}),
  result('Waiting'), done('sync','failed'), result('Report with gaps'),
])), ['Report with gaps']);
assert.deepEqual(answers(await run([start('worker'),done('worker','stopped'),result('Stopped task')])), ['Stopped task']);
assert.deepEqual(answers(await run([start('watcher',{skip_transcript:true}),result('Done')])), ['Done']);

// Errors/cancellation must terminate even while background work is active.
const failure = {type:'result',subtype:'error_max_turns',is_error:true,errors:['private']};
const failed = await run([start('worker'),failure]);
assert.equal(failed.at(-1).completed,false);
assert.ok(!JSON.stringify(failed).includes('private'));
assert.deepEqual(answers(await run([start('worker'),result('Interrupted')],()=>true)), ['Interrupted']);
assert.deepEqual(await run([start('worker'),result('Waiting')]).then(e=>e.at(-1)), {type:'error'});
assert.deepEqual(answers(await run([result('Ordinary chat response')])), ['Ordinary chat response']);

// A dashboard message queued before a turn ends runs as the next turn; its
// reply must not be cut off by the earlier result.
{
  const inputs = {pending:new Set(['question'])};
  const stamped = (answer, uuids) => ({...result(answer), user_message_uuid:uuids.at(-1), user_message_uuids:uuids});
  assert.deepEqual(answers(await (async () => {
    const events = [];
    await consumeSession((async function* () {
      yield stamped('Working', ['prompt']);
      assert.deepEqual([...inputs.pending], ['question']);
      yield {type:'assistant',user_message_uuid:'question',message:{content:[{type:'text',text:'Validating probes'}]}};
      yield stamped('Report ready', ['question']);
    })(), e => events.push(e), () => false, inputs);
    return events;
  })()), ['Report ready']);
  assert.equal(inputs.pending.size, 0);
  // Subagent frames do not consume the lead's messages; old CLIs cannot be tracked.
  const old = {pending:new Set(['question'])};
  assert.deepEqual(answers(await (async () => {
    const events = [];
    await consumeSession((async function* () {yield result('Done');})(), e => events.push(e), () => false, old);
    return events;
  })()), ['Done']);
}

// Exercise the actual bridge entrypoint, including the lifetime of its input
// generator. Stub SDK imports in the child process: no login or model calls.
const fakeSdk = `
  import assert from 'node:assert/strict';
  export const createSdkMcpServer = () => {throw Error('Unexpected chat tools');};
  export const tool = createSdkMcpServer;
  export function query({prompt}) {
    const stream = (async function* () {
      assert.equal((await prompt.next()).value.message.content, 'fixture');
      yield {type:'system',subtype:'init',session_id:'fixture'};
      yield {type:'system',subtype:'background_tasks_changed',tasks:[{task_id:'reviewer'}]};
      yield {type:'result',subtype:'success',is_error:false,result:'Waiting'};
      // Receiving a message after the waiting result proves the input stayed open.
      const steer = (await prompt.next()).value;
      assert.equal(steer.message.content, 'What is going on?');
      assert.match(steer.uuid, /^[0-9a-f-]{36}$/);
      yield {type:'assistant',user_message_uuid:steer.uuid,message:{content:[{type:'text',text:'Runtime probes are running'}]}};
      yield {type:'system',subtype:'background_tasks_changed',tasks:[]};
      yield {type:'system',subtype:'task_notification',task_id:'reviewer',status:'completed'};
      yield {type:'assistant',message:{content:[{type:'text',text:'Synthesizing'}]}};
      yield {type:'result',subtype:'success',is_error:false,result:'Report ready'};
    })();
    stream.close = () => {};
    stream.interrupt = async () => {};
    return stream;
  }
`;
const moduleUrl = code => 'data:text/javascript;base64,' + Buffer.from(code).toString('base64');
const loader = `
  import {registerHooks} from 'node:module';
  const modules = ${JSON.stringify({'@anthropic-ai/claude-agent-sdk':moduleUrl(fakeSdk),zod:moduleUrl('export const z = {};')})};
  registerHooks({resolve(specifier, context, next) {
    return modules[specifier] ? {url:modules[specifier],shortCircuit:true} : next(specifier, context);
  }});
`;
const bridge = spawnSync(process.execPath, ['--import',moduleUrl(loader),
  fileURLToPath(new URL('../../scripts/claude-runtime/bridge.mjs',import.meta.url))], {
  input:JSON.stringify({mode:'review',prompt:'fixture',cwd:process.cwd(),instructions:''})+'\n'
    +JSON.stringify({type:'message',text:'What is going on?'})+'\n',
  encoding:'utf8',timeout:10000,
});
assert.equal(bridge.status,0,bridge.stderr);
const bridgeEvents = bridge.stdout.trim().split('\n').map(line=>JSON.parse(line));
assert.deepEqual(answers(bridgeEvents),['Report ready']);
assert.ok(bridgeEvents.some(e=>e.type==='update' && e.text==='Synthesizing'));
assert.ok(bridgeEvents.some(e=>e.type==='update' && e.text==='Runtime probes are running'));
assert.ok(!bridgeEvents.some(e=>e.type==='error'));
console.log('Claude session: background review continuations, snapshots, errors and cancellation passed.');
