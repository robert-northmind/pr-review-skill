import assert from 'node:assert/strict';
import {chatMarkdown} from '../../assets/code-workspace/chat-markdown.mjs';
const answer = '### Storage keys\n\n- **Head:** `namespace-record`\n- Base stays unchanged.\n\n| Setup | Key |\n| --- | --- |\n| Default | `otel-session-record` |\n\n```swift\nlet key = "<value>"\n```\n\n[Documentation](https://example.com/docs?a=1&b=2)';
const html=chatMarkdown(answer);
for(const tag of ['<h3>','<ul>','<strong>','<code>','<table>','<thead>','<tbody>','<pre'])assert.ok(html.includes(tag),tag);
assert.ok(html.includes('data-copy-code'));
assert.ok(html.includes('&lt;value&gt;'));
assert.ok(html.includes('rel="noopener noreferrer"'));
for(const source of [
 '<img src=x onerror=alert(1)><script>alert(1)</script>',
 '[run](javascript:alert%281%29)', '[run](JaVaScRiPt:alert%281%29)',
 '[run](javascript&#58;alert%281%29)', '[run](data:text/html,hi)',
 '[run](file:///etc/passwd)', '[run](https://user:password@example.com)',
 '[run](//example.com)', '[run](/workspace-chat)',
 '![remote](https://example.com/tracker.png)',
 '```\"><img src=x onerror=alert(1)>\n<script>hi</script>\n```',
]){
 const rendered=chatMarkdown(source);
 assert.ok(!/<(?:script|img|iframe|style)\b/i.test(rendered),rendered);
 assert.ok(!/href=/i.test(rendered),rendered);
}
assert.ok(chatMarkdown('```js\nconst value = "partial').includes('<code>const value ='));
assert.ok(chatMarkdown('1. First\n   - Nested\n2. Second').includes('<ol>'));
assert.ok(chatMarkdown('> Quoted evidence').includes('<blockquote>'));
console.log('Chat Markdown: structured answers, partial fences, escaped HTML, safe links and no remote images passed.');
