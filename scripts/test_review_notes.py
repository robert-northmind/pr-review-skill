import html
from html.parser import HTMLParser
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pr_dashboard as dashboard
from validate_review_notes import validate


class Parsed(HTMLParser):
    def __init__(self, source):
        super().__init__(); self.tags = []; self.sources = []; self.current = None
        self.feed(source)
    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        if tag == 'textarea': self.current = ''
    def handle_endtag(self, tag):
        if tag == 'textarea': self.sources.append(self.current); self.current = None
    def handle_data(self, data):
        if self.current is not None: self.current += data


class Rendering(unittest.TestCase):
    def test_legacy_quote_keeps_paragraphs_and_code(self):
        parsed = Parsed(dashboard.markdown_to_html('> Should we try this?\n>\n> ```dart\n> return value < 2;\n> ```'))
        self.assertIn('blockquote', parsed.tags)
        self.assertIn('pre', parsed.tags)
        self.assertNotIn('button', parsed.tags)

    def test_table_with_pipe_in_code_and_escaped_pipe(self):
        rendered = dashboard.markdown_to_html('| Check | Result |\n|---|---|\n| `a | b` | x\\|y |')
        parsed = Parsed(rendered)
        self.assertEqual(parsed.tags.count('th'), 2)
        self.assertEqual(parsed.tags.count('td'), 2)
        self.assertIn('<code>a | b</code>', rendered)
        self.assertIn('x|y', rendered)

    def test_copy_preserves_markdown_excludes_metadata(self):
        comment = 'Should we try this?\n\n```dart\nreturn a < b;\n```\n\n[Example](https://example.com/path)'
        markdown = '**Disposition:** Optional\n\n<!-- review-comment:start -->\n' + comment + '\n<!-- review-comment:end -->\n\n**Placement:** general PR comment'
        parsed = Parsed(dashboard.markdown_to_html(markdown))
        self.assertEqual(parsed.sources, [comment])
        self.assertEqual(parsed.tags.count('button'), 1)

    def test_fenced_markers_do_not_make_buttons(self):
        rendered = dashboard.markdown_to_html('````md\n<!-- review-comment:start -->\nText\n<!-- review-comment:end -->\n````')
        self.assertNotIn('button', Parsed(rendered).tags)

    def test_literal_end_marker_inside_draft_code(self):
        comment = 'Example:\n```html\n<!-- review-comment:end -->\n```'
        rendered = dashboard.markdown_to_html('<!-- review-comment:start -->\n' + comment + '\n<!-- review-comment:end -->')
        self.assertEqual(Parsed(rendered).sources, [comment])

    def test_details_and_source_html_are_safe(self):
        source = '<details>\n<summary>Evidence</summary>\n\n<script>alert(1)</script>\n\n</details>'
        rendered = dashboard.markdown_to_html(source)
        tags = Parsed(rendered).tags
        self.assertIn('details', tags); self.assertIn('summary', tags)
        self.assertNotIn('script', tags)
        self.assertNotIn('details', Parsed(dashboard.markdown_to_html('<details onclick="alert(1)">')).tags)

    def test_copy_source_cannot_escape_textarea(self):
        body = '</textarea><script>alert(1)</script>'
        rendered = dashboard.markdown_to_html('<!-- review-comment:start -->\n' + body + '\n<!-- review-comment:end -->')
        parsed = Parsed(rendered)
        self.assertEqual(parsed.sources, [body]); self.assertNotIn('script', parsed.tags)

    def test_nested_list_and_continuation(self):
        rendered = dashboard.markdown_to_html('- Parent\n  continuation\n  - Child\n- Sibling')
        parsed = Parsed(rendered)
        self.assertEqual(parsed.tags.count('ul'), 2)
        self.assertEqual(parsed.tags.count('li'), 3)
        self.assertIn('Parent continuation', rendered)

    def test_local_artifact_link_routes_through_server(self):
        result = dashboard.markdown_to_html('[Checks](/Users/example-user/.local/share/pr-review-tracker/runs/x/verification.md)')
        self.assertIn('href="/artifact?path=%2FUsers', result)
        self.assertNotIn('<a ', dashboard.markdown_to_html('[Bad](javascript:alert)'))

    def test_existing_corpus_renders(self):
        for path in (Path.home()/'.local/share/pr-review-tracker/runs').glob('*/review.md'):
            with self.subTest(path=path):
                result = dashboard.markdown_to_html(path.read_text())
                self.assertTrue(result)
                if any(line.startswith('>') for line in path.read_text().splitlines()):
                    self.assertIn('blockquote', Parsed(result).tags)


class Validation(unittest.TestCase):
    def test_valid_code_and_clean_review(self):
        self.assertEqual(validate('# Review\nNo findings.')[0], [])
        body = '<!-- review-comment:start -->\nCould we test it?\n\n```html\n<!-- review-comment:end -->\n```\n<!-- review-comment:end -->'
        self.assertEqual(validate(body)[0], [])

    def test_reject_malformed_or_metadata(self):
        for body in ('<!-- review-comment:end -->', '<!-- review-comment:start -->', '<!-- review-comment:start -->\n<!-- review-comment:end -->', '<!-- review-comment:start -->\n**Confidence:** 90\n<!-- review-comment:end -->'):
            with self.subTest(body=body): self.assertTrue(validate(body)[0])

    def test_unresolved_finding_cannot_be_copied(self):
        body = '**Disposition:** Needs confirmation\n\n<!-- review-comment:start -->\nCould we fix it?\n<!-- review-comment:end -->'
        self.assertTrue(validate(body)[0])

    def test_long_draft_warns_without_forcing_rejection(self):
        errors, warnings = validate('<!-- review-comment:start -->\n' + 'word ' * 151 + '\n<!-- review-comment:end -->')
        self.assertFalse(errors); self.assertTrue(warnings)


if __name__ == '__main__': unittest.main()
