import MarkdownIt from './vendor/markdown-it.mjs';

// Model output is untrusted. No raw HTML, embedded media or executable links.
const markdown = new MarkdownIt({html:false, linkify:false, typographer:false});
const escape = markdown.utils.escapeHtml;
markdown.validateLink = value => {
  try {
    const url = new URL(value);
    return /^https?:\/\//i.test(value) && ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password;
  } catch { return false; }
};
markdown.renderer.rules.link_open = (tokens, index, options, env, renderer) => {
  tokens[index].attrSet('target', '_blank');
  tokens[index].attrSet('rel', 'noopener noreferrer');
  return renderer.renderToken(tokens, index, options);
};
// Keep image descriptions without issuing requests to model-supplied image URLs.
markdown.renderer.rules.image = (tokens, index) => escape(tokens[index].content);
markdown.renderer.rules.fence = (tokens, index) => {
  const token = tokens[index], language = token.info.trim().split(/\s+/)[0] || 'Code';
  return `<div class="chat-code"><div class="chat-code-heading"><span>${escape(language)}</span><button type="button" class="text-button" data-copy-code>Copy code</button></div><pre tabindex="0"><code>${escape(token.content)}</code></pre></div>\n`;
};
markdown.renderer.rules.table_open = () => '<div class="chat-table" tabindex="0" role="region" aria-label="Table; scroll horizontally for more columns"><table>\n';
markdown.renderer.rules.table_close = () => '</table></div>\n';

export function chatMarkdown(text) {
  return markdown.render(String(text ?? ''));
}
