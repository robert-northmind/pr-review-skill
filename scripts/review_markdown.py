"""Dependency-free block rendering for local review artifacts; raw HTML is escaped."""

import re

START = '<!-- review-comment:start -->'
END = '<!-- review-comment:end -->'
FENCE = re.compile(r'^\s*(`{3,}|~{3,})(.*)$')
ITEM = re.compile(r'^(\s*)([-+*]|\d+[.)])\s+(.*)$')


def find_close(lines, start, end_marker):
    fence = None
    depth = 0
    for i in range(start, len(lines)):
        s = lines[i].strip()
        m = FENCE.match(lines[i])
        if m:
            token = m[1]
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence) and not m[2].strip():
                fence = None
            continue
        if fence:
            continue
        if end_marker == '</details>' and s == '<details>':
            depth += 1
        elif s == end_marker:
            if depth == 0:
                return i
            depth -= 1
    return None


def cells(line):
    # Ignore escaped pipes and pipes inside inline code spans.
    result, current, fence = [], [], 0
    s = line.strip().strip('|')
    i = 0
    while i < len(s):
        c = s[i]
        if c == '\\' and i + 1 < len(s) and s[i + 1] == '|':
            current.append('|'); i += 2; continue
        if c == '`':
            j = i
            while j < len(s) and s[j] == '`': j += 1
            width = j - i
            fence = 0 if fence == width else (width if not fence else fence)
            current.append(s[i:j]); i = j; continue
        if c == '|' and not fence:
            result.append(''.join(current).strip()); current = []
        else:
            current.append(c)
        i += 1
    result.append(''.join(current).strip())
    return result


def render(text, inline, escape, depth=0):
    if depth > 24:
        return '<pre>' + escape(text) + '</pre>'
    lines = text.replace('\r\n', '\n').split('\n')
    parts, i = [], 0
    def sub(body):
        return render('\n'.join(body), inline, escape, depth + 1)
    def table_at(index):
        if index + 1 >= len(lines) or '|' not in lines[index]: return False
        cols, delimiters = cells(lines[index]), cells(lines[index + 1])
        return len(cols) == len(delimiters) and all(re.fullmatch(r':?-{3,}:?', c) for c in delimiters)
    def begins(index):
        s = lines[index].strip()
        return (not s or FENCE.match(lines[index]) or ITEM.match(lines[index])
                or re.match(r'^(#{1,6})\s|^>', s) or s in (START, '<details>', '---', '***', '___')
                or table_at(index))
    while i < len(lines):
        line, s = lines[i], lines[i].strip()
        if not s:
            i += 1; continue
        fence = FENCE.match(line)
        if fence:
            token, language = fence[1], fence[2].strip()
            block, i = [], i + 1
            while i < len(lines):
                m = FENCE.match(lines[i])
                if m and m[1][0] == token[0] and len(m[1]) >= len(token) and not m[2].strip():
                    i += 1; break
                block.append(lines[i]); i += 1
            parts.append('<pre><code>' + escape('\n'.join(block)) + '</code></pre>')
        elif s == START and (end := find_close(lines, i + 1, END)) is not None:
            body = '\n'.join(lines[i + 1:end]).strip('\n')
            parts.append('<section class="review-comment"><button type="button" class="copy-comment">Copy comment</button>'
                         '<span class="copy-status" role="status"></span><div class="comment-body">'
                         + sub(body.split('\n')) + '</div><textarea class="comment-source" hidden readonly aria-label="Comment Markdown">'
                         + escape(body) + '</textarea></section>')
            i = end + 1
        elif s == '<details>' and (end := find_close(lines, i + 1, '</details>')) is not None:
            start = i + 1
            while start < end and not lines[start].strip(): start += 1
            summary = re.fullmatch(r'<summary>(.*?)</summary>', lines[start].strip()) if start < end else None
            if summary:
                parts.append('<details><summary>' + inline(summary[1]) + '</summary>' + sub(lines[start + 1:end]) + '</details>')
                i = end + 1
            else:
                parts.append('<p>' + escape(line) + '</p>'); i += 1
        elif s.startswith('>'):
            block = []
            while i < len(lines) and lines[i].lstrip().startswith('>'):
                block.append(re.sub(r'^\s*> ?', '', lines[i], count=1)); i += 1
            parts.append('<blockquote>' + sub(block) + '</blockquote>')
        elif table_at(i):
            headers, align = cells(lines[i]), cells(lines[i + 1])
            width = len(headers)
            styles = ['center' if c.startswith(':') and c.endswith(':') else 'right' if c.endswith(':') else 'left' for c in align]
            def row(cols, tag):
                cols = (cols + [''] * width)[:width]
                return '<tr>' + ''.join(f'<{tag} style="text-align:{styles[n]}">{inline(c)}</{tag}>' for n, c in enumerate(cols)) + '</tr>'
            output = ['<div class="table-scroll"><table><thead>', row(headers, 'th'), '</thead><tbody>']
            i += 2
            while i < len(lines) and lines[i].strip() and '|' in lines[i]:
                output.append(row(cells(lines[i]), 'td')); i += 1
            output.append('</tbody></table></div>'); parts.append(''.join(output))
        elif heading := re.match(r'^(#{1,6})\s+(.*)$', s):
            level = len(heading[1]); parts.append(f'<h{level}>{inline(heading[2])}</h{level}>'); i += 1
        elif s in ('---', '***', '___'):
            parts.append('<hr>'); i += 1
        elif item := ITEM.match(line):
            indent = len(item[1]); ordered = item[2][0].isdigit(); tag = 'ol' if ordered else 'ul'
            items = []
            while i < len(lines):
                m = ITEM.match(lines[i])
                if not m or len(m[1]) != indent or m[2][0].isdigit() != ordered: break
                content_indent = len(m[1]) + len(m[2]) + 1
                content = [m[3]]; i += 1
                while i < len(lines):
                    if not lines[i].strip():
                        # Keep a blank only when the following line continues this item.
                        j = i + 1
                        while j < len(lines) and not lines[j].strip(): j += 1
                        if j < len(lines) and len(lines[j]) - len(lines[j].lstrip()) > indent:
                            content.append(''); i += 1; continue
                        break
                    spaces = len(lines[i]) - len(lines[i].lstrip())
                    if spaces <= indent: break
                    content.append(lines[i][min(content_indent, spaces):]); i += 1
                items.append('<li>' + sub(content) + '</li>')
                while i < len(lines) and not lines[i].strip(): i += 1
            parts.append(f'<{tag}>' + ''.join(items) + f'</{tag}>')
        else:
            paragraph = [line]; i += 1
            while i < len(lines) and not begins(i):
                paragraph.append(lines[i]); i += 1
            parts.append('<p>' + inline(' '.join(paragraph)) + '</p>')
    return '\n'.join(parts)
