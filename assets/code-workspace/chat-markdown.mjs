import MarkdownIt from './vendor/markdown-it.mjs';

const safeLink = value => {
  try {
    const url = new URL(value);
    return /^https?:\/\//i.test(value) && ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password;
  } catch { return false; }
};
function configure(markdown) {
  const escape = markdown.utils.escapeHtml;
  markdown.validateLink = safeLink;
  markdown.renderer.rules.link_open = (tokens, index, options, env, renderer) => {
    tokens[index].attrSet('target', '_blank');
    tokens[index].attrSet('rel', 'noopener noreferrer');
    return renderer.renderToken(tokens, index, options);
  };
  // Keep image descriptions without issuing requests to untrusted image URLs.
  markdown.renderer.rules.image = (tokens, index) => escape(tokens[index].content);
  markdown.renderer.rules.fence = (tokens, index) => {
    const token = tokens[index], info = token.info.trim().split(/\s+/)[0];
    // GitHub review suggestions use a `suggestion` fence for replacement lines.
    const language = info === 'suggestion' ? 'Suggested change' : info || 'Code';
    return `<div class="chat-code"><div class="chat-code-heading"><span>${escape(language)}</span><button type="button" class="text-button" data-copy-code>Copy code</button></div><pre tabindex="0"><code>${escape(token.content)}</code></pre></div>\n`;
  };
  markdown.renderer.rules.table_open = () => '<div class="chat-table" tabindex="0" role="region" aria-label="Table; scroll horizontally for more columns"><table>\n';
  markdown.renderer.rules.table_close = () => '</table></div>\n';
  return markdown;
}

// Model output is untrusted. No raw HTML, embedded media or executable links.
const markdown = configure(new MarkdownIt({html:false, linkify:false, typographer:false}));
// GitHub comments commonly mix Markdown with HTML; it is sanitized before display.
const github = configure(new MarkdownIt({html:true, linkify:true, typographer:false}));

export function chatMarkdown(text) {
  return markdown.render(String(text ?? ''));
}

const KEEP = new Set(['A', 'ABBR', 'B', 'BLOCKQUOTE', 'BR', 'BUTTON', 'CODE', 'DD', 'DEL', 'DETAILS', 'DIV', 'DL', 'DT', 'EM',
  'H1', 'H2', 'H3', 'H4', 'H5', 'H6', 'HR', 'I', 'INS', 'KBD', 'LI', 'MARK', 'OL', 'P', 'PRE', 'Q', 'S', 'SAMP', 'SMALL',
  'SPAN', 'STRONG', 'SUB', 'SUMMARY', 'SUP', 'TABLE', 'TBODY', 'TD', 'TFOOT', 'TH', 'THEAD', 'TR', 'U', 'UL', 'VAR']);
const DROP = new Set(['SCRIPT', 'STYLE', 'IFRAME', 'OBJECT', 'EMBED', 'SVG', 'MATH', 'FORM', 'INPUT', 'TEXTAREA', 'SELECT',
  'TEMPLATE', 'NOSCRIPT', 'LINK', 'META', 'BASE', 'VIDEO', 'AUDIO', 'CANVAS', 'SOURCE', 'TRACK']);
// Only the renderer's own inert presentation attributes survive; everything else is removed.
const ATTRIBUTES = {
  class: value => /^(chat-[a-z-]+|text-button)$/.test(value),
  'data-copy-code': value => value === '',
  tabindex: value => value === '0',
  role: value => value === 'region',
  'aria-label': () => true,
  type: value => value === 'button',
  open: value => value === '',
  align: value => /^(left|right|center)$/.test(value),
  colspan: value => /^\d{1,2}$/.test(value),
  rowspan: value => /^\d{1,2}$/.test(value),
};
function clean(node, doc) {
  for (const child of [...node.childNodes]) {
    if (child.nodeType === 8) { child.remove(); continue; }
    if (child.nodeType !== 1) continue;
    const tag = child.tagName;
    if (tag === 'IMG') { child.replaceWith(doc.createTextNode(child.getAttribute('alt') || '')); continue; }
    if (DROP.has(tag)) { child.remove(); continue; }
    clean(child, doc);
    if (!KEEP.has(tag)) { child.replaceWith(...child.childNodes); continue; }
    for (const { name, value } of [...child.attributes]) {
      if (name === 'href' && tag === 'A' && safeLink(value)) continue;
      if (!(Object.hasOwn(ATTRIBUTES, name) && ATTRIBUTES[name](value))) child.removeAttribute(name);
    }
    if (tag === 'A') {
      if (child.hasAttribute('href')) { child.setAttribute('target', '_blank'); child.setAttribute('rel', 'noopener noreferrer'); }
    }
  }
}

/** GitHub-flavored comment body. Without a DOM (unit tests), HTML stays escaped text. */
export function commentMarkdown(text, doc = globalThis.document) {
  if (!doc?.createElement) return chatMarkdown(text);
  // Template content is inert: nothing loads or runs while it is sanitized.
  const template = doc.createElement('template');
  template.innerHTML = github.render(String(text ?? ''));
  clean(template.content, doc);
  return template.innerHTML;
}
