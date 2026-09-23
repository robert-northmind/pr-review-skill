import assert from "node:assert/strict";
import {
  diffEntries,
  splitPairs,
  selectionFor,
} from "../../assets/code-workspace/diff.mjs";
import {
  attach,
  removeContext,
  hydrate,
  uiState,
  isOlder,
} from "../../assets/code-workspace/model.mjs";
import { SaveQueue } from "../../assets/code-workspace/api.mjs";
const rows = Array.from({ length: 20 }, (_, id) => ({
  id,
  kind: id === 10 ? "add" : "context",
  old: id === 10 ? null : id + 1,
  new: id + 1,
  text: "line " + id,
}));
const file = { path: "a.ts", rows },
  data = { files: [file], base: "a", head: "b" };
const entries = diffEntries(file);
assert.equal(entries[0].gap, true);
assert.equal(entries[0].count, 7);
assert.equal(entries.at(-1).gap, true);
assert.equal(diffEntries(file, "head").length, 20);
const selection = selectionFor(data, 0, 10, 12, "head", true);
assert.deepEqual(selection.ids, [10, 11, 12]);
assert.equal(selection.label, "Head L11–13");
assert.deepEqual(selectionFor(data, 0, 10, 12, "base", true).ids, [11, 12]);
const pairs = splitPairs([
  { kind: "delete", id: 1 },
  { kind: "add", id: 2 },
  { kind: "add", id: 3 },
]);
assert.equal(pairs.length, 2);
assert.equal(pairs[1][0], undefined);
assert.equal(attach([selection], selection).length, 1);
const thread = {
  id: "one",
  context: selection,
  messages: [{ role: "user", text: "Old" }],
};
removeContext(thread, 0);
assert.equal(thread.contexts.length, 0);
assert.equal(thread.messages[0].contexts.length, 1);
const state = hydrate({
  threads: [thread],
  attachments: { one: [selection] },
  viewed: ["a.ts"],
});
assert.equal(state.threads[0].contexts.length, 1);
assert.equal(uiState(state).attachments.one.length, 1);
assert.equal(isOlder({ base: "a", head: "c" }, data), true);
let releases = [],
  calls = [];
const queue = new SaveQueue(
  {
    request: (_, body) =>
      new Promise((resolve) => {
        calls.push(body);
        releases.push(resolve);
      }),
  },
  "rev",
  2,
  (error) => {
    throw error;
  },
);
queue.enqueue({ viewed: ["a"] });
queue.enqueue({ viewed: ["a", "b"] });
queue.enqueue({ viewed: ["b"] });
assert.equal(calls.length, 1);
releases.shift()({ version: 3 });
await new Promise((resolve) => setImmediate(resolve));
assert.equal(calls.length, 2);
assert.equal(calls[1].version, 3);
assert.deepEqual(calls[1].viewed, ["b"]);
releases.shift()({ version: 4 });
await queue.flush();
assert.equal(queue.version, 4);
let failure;
const broken = new SaveQueue(
  {
    request: async () => {
      throw new Error("conflict");
    },
  },
  "rev",
  0,
  (e) => (failure = e),
);
broken.enqueue({});
await assert.rejects(() => broken.flush(), /could not be saved/);
assert.equal(failure.message, "conflict");
console.log(
  "Workspace model checks passed: diff projections, selections, attachment history, revisions and serialized saves.",
);

const {renderFileRows,contextHTML}=await import('../../assets/code-workspace/views.mjs');
const unsafe={...file,rows:[{id:0,old:null,new:1,kind:'add',text:'<img src=x onerror=alert(1)>'}]};
const rendered=renderFileRows(unsafe,0,{layout:'split',base:'a',head:'b'});
assert.ok(!rendered.includes('<img'));assert.ok(rendered.includes('&lt;img'));
assert.ok(contextHTML({...selection,path:'<img>.ts',snippet:'<script>bad()</script>'},0).includes('&lt;script&gt;'));
console.log('Workspace rendering checks passed: source and context escaping.');
const {sourceTarget}=await import('../../assets/code-workspace/model.mjs');
const pinned={repository:'owner/repo',head:'b'.repeat(40),base:'a'.repeat(40),files:[{path:'src/a.ts'}]};
assert.deepEqual(sourceTarget('https://github.com/owner/repo/blob/'+pinned.head+'/src/a.ts#L4-L7',pinned),{path:'src/a.ts',side:'head',start:4,end:7});
assert.equal(sourceTarget('https://github.com/elsewhere/repo/blob/'+pinned.head+'/src/a.ts#L4',pinned),null);
assert.equal(sourceTarget('https://github.com/owner/repo/blob/main/src/a.ts#L4',pinned),null);

const {reviewHTML, unavailableHTML} = await import('../../assets/code-workspace/review.mjs');
const {esc} = await import('../../assets/code-workspace/views.mjs');
const run = {run_id: 'saved-run', status: 'running', transport: 'terminal'};
assert.ok(!reviewHTML({run}, pinned, esc).includes('Review activity'));
assert.ok(reviewHTML({run: {...run, transport: 'in-app'}}, pinned, esc).includes('/?review=saved-run'));
const fallback = unavailableHTML(new Error('<offline>'), {artifact: {path: '/tmp/review & notes.html'}}, esc);
assert.ok(fallback.includes('&lt;offline&gt;'));
assert.ok(fallback.includes('/artifact?path=%2Ftmp%2Freview+%26+notes.html'));
assert.ok(fallback.includes('Its commit could not be checked'));
assert.equal(unavailableHTML(new Error('Offline'), null, esc), 'Offline');

const {chatProgress, activityHTML} = await import('../../assets/code-workspace/progress.mjs');
const progressThread = {status:'running', started_at:100, progress:'Reading file…', activity:[{at:102,text:'<source>'}]};
assert.equal(chatProgress(progressThread, 165000), 'Reading file… · 1m 5s');
assert.equal(chatProgress({...progressThread,status:'stopping'}), 'Stopping…');
assert.equal(chatProgress({...progressThread,status:'completed'}), '');
assert.ok(activityHTML(progressThread).includes('&lt;source&gt;'));
const {contextReadLabel} = await import('../../assets/code-workspace/model.mjs');
assert.equal(contextReadLabel({kind:'search_code',query:'flush',side:'head',path:''}), 'Search “flush” · head · /');
assert.equal(contextReadLabel({kind:'open_page',url:'https://example.com'}), 'Open page · https://example.com');
const {sourceLinksHTML} = await import('../../assets/code-workspace/views.mjs');
assert.equal(sourceLinksHTML([{title:'bad',url:'javascript:alert(1)'}]), '');
assert.equal(sourceLinksHTML([{title:'bad',url:'https://user:password@example.com/'}]), '');
assert.ok(sourceLinksHTML([{title:'<script>',url:'https://example.com/?a=1&b=2'}]).includes('&lt;script&gt;'));
assert.ok(sourceLinksHTML([{title:'Spec',url:'https://example.com'}]).includes('rel="noopener noreferrer"'));

assert.ok(!reviewHTML({run}, pinned, esc).includes("Explore code</button>"));
