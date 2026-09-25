"""Allowlist sanitizer for authored report diagrams (static HTML and inline SVG).

Diagrams are re-serialized from parsed tokens: unknown tags or attributes are
rejected rather than dropped, so the author sees and fixes the problem. Text is
escaped. No element can link, load, script or restyle the page.
"""
import html
from html.parser import HTMLParser
import re

HTML_TAGS = {'div', 'span', 'p', 'strong', 'em', 'b', 'i', 's', 'code', 'small', 'sub', 'sup', 'mark',
             'kbd', 'br', 'hr', 'ul', 'ol', 'li', 'h4', 'h5', 'table', 'thead', 'tbody', 'tr', 'th', 'td'}
SVG_TAGS = {'svg', 'g', 'path', 'rect', 'circle', 'ellipse', 'line', 'polyline', 'polygon', 'text',
            'tspan', 'defs', 'marker', 'title', 'desc'}
VOID = {'br', 'hr'}
COMMON = {'class', 'style', 'id', 'role', 'aria-label', 'aria-hidden', 'aria-labelledby', 'aria-describedby'}
HTML_ATTRS = {'colspan', 'rowspan', 'scope'}
SVG_ATTRS = {
    'viewbox', 'width', 'height', 'x', 'y', 'x1', 'y1', 'x2', 'y2', 'cx', 'cy', 'r', 'rx', 'ry', 'dx', 'dy',
    'd', 'points', 'fill', 'fill-opacity', 'stroke', 'stroke-width', 'stroke-dasharray', 'stroke-linecap',
    'stroke-linejoin', 'stroke-opacity', 'opacity', 'font-size', 'font-weight', 'font-family', 'font-style',
    'text-anchor', 'dominant-baseline', 'transform', 'marker-start', 'marker-mid', 'marker-end', 'refx',
    'refy', 'markerwidth', 'markerheight', 'markerunits', 'orient', 'preserveaspectratio', 'xmlns', 'focusable',
}
PREFIXED = re.compile(r'dg-[a-z0-9-]+')
# url() may only point at a marker or gradient inside the same diagram.
UNSAFE_VALUE = re.compile(r'\\|javascript:|expression|@import|url\s*\((?!\s*#dg-[a-z0-9-]+\s*\))', re.I)


class DiagramError(ValueError):
    pass


class _Sanitizer(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.stack = [], []

    def _attrs(self, tag, attrs):
        allowed = COMMON | (SVG_ATTRS if tag in SVG_TAGS else HTML_ATTRS)
        parts = []
        for name, value in attrs:
            value = value or ''
            if name not in allowed:
                raise DiagramError(f'Diagram attribute not allowed: {name} on <{tag}>')
            if UNSAFE_VALUE.search(value):
                raise DiagramError(f'Diagram attribute value not allowed in {name}')
            if name == 'class' and not all(PREFIXED.fullmatch(c) for c in value.split()):
                raise DiagramError('Diagram classes must use the dg- prefix')
            if name == 'id' and not PREFIXED.fullmatch(value):
                raise DiagramError('Diagram ids must use the dg- prefix')
            parts.append(f' {name}="{html.escape(value, quote=True)}"')
        return ''.join(parts)

    def handle_starttag(self, tag, attrs, closing=False):
        if tag not in HTML_TAGS | SVG_TAGS:
            raise DiagramError(f'Diagram element not allowed: <{tag}>')
        attributes = self._attrs(tag, attrs)
        if tag in VOID:
            self.out.append(f'<{tag}{attributes}>')
        elif closing:
            self.out.append(f'<{tag}{attributes}></{tag}>')
        else:
            self.out.append(f'<{tag}{attributes}>'); self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs, closing=True)

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        if not self.stack or self.stack[-1] != tag:
            raise DiagramError(f'Diagram markup is not well nested near </{tag}>')
        self.stack.pop(); self.out.append(f'</{tag}>')

    def handle_data(self, data):
        self.out.append(html.escape(data, quote=False))

    def handle_comment(self, data):
        pass

    def handle_decl(self, decl):
        raise DiagramError('Diagram markup cannot contain declarations')

    def handle_pi(self, data):
        raise DiagramError('Diagram markup cannot contain processing instructions')

    unknown_decl = handle_decl


def sanitize(markup):
    if not isinstance(markup, str) or not markup.strip():
        raise DiagramError('Diagram markup must be a non-empty string')
    if re.search(r'<!\[CDATA\[', markup, re.I):
        raise DiagramError('Diagram markup cannot contain CDATA')
    parser = _Sanitizer()
    parser.feed(markup); parser.close()
    if parser.stack:
        raise DiagramError(f'Diagram markup leaves <{parser.stack[-1]}> unclosed')
    return ''.join(parser.out)
