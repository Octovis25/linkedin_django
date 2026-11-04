"""Text of a revision and what changed between two revisions.

A revision's HTML (Elementor writes a copy into every revision) becomes plain
text: one line per block, no style or script, images as "[Image file.png]".
Two texts are compared sentence by sentence. Only the standard library.
"""
import difflib
import html
import re
from html.parser import HTMLParser

BLOCKS = {'p', 'div', 'section', 'article', 'li', 'ul', 'ol', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
          'blockquote', 'figure', 'figcaption', 'table', 'tr', 'td', 'th', 'br', 'hr', 'header',
          'footer', 'nav', 'main', 'aside', 'dd', 'dt', 'dl'}
SKIP = {'style', 'script', 'noscript', 'svg', 'template'}
IMAGE = re.compile(r'^\[Image [^\]]*\]$')


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in SKIP:
            self.skip += 1
            return
        if self.skip:
            return
        if tag == 'img':
            src = dict(attrs).get('src') or dict(attrs).get('data-src') or ''
            name = src.split('?')[0].rstrip('/').rsplit('/', 1)[-1]
            if name:
                self.out.append(f'\n[Image {name}]\n')
            return
        if tag in BLOCKS:
            self.out.append('\n')

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag in SKIP:
            self.skip = max(0, self.skip - 1)
            return
        if not self.skip and tag in BLOCKS:
            self.out.append('\n')

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def text_plain(html_text):
    """Plain text of a revision's HTML, one block per line."""
    p = _Text()
    p.feed(html_text or '')
    p.close()
    lines = []
    for line in ''.join(p.out).split('\n'):
        line = re.sub(r'\s+', ' ', html.unescape(line)).strip()
        if line:
            lines.append(line)
    return '\n'.join(lines)


def sentences(text):
    """The text as a list of sentences; an image token is a sentence of its own."""
    out = []
    for line in (text or '').split('\n'):
        line = line.strip()
        if not line:
            continue
        if IMAGE.match(line):
            out.append(line)
            continue
        out.extend(s for s in re.split(r'(?<=[.!?])\s+', line) if s)
    return out


def compare(before_text, after_text, before_title='', after_title=''):
    """What kind of change and how many sentences changed.

    kinds: a list out of 'Text', 'Title', 'Image' - empty when nothing that
    can be read changed (Elementor often saves the same text again).
    """
    a = [s for s in sentences(before_text)]
    b = [s for s in sentences(after_text)]
    text_a = [s for s in a if not IMAGE.match(s)]
    text_b = [s for s in b if not IMAGE.match(s)]
    changed = 0
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, text_a, text_b, autojunk=False).get_opcodes():
        if op != 'equal':
            changed += max(i2 - i1, j2 - j1)
    kinds = []
    if changed:
        kinds.append('Text')
    if (before_title or '').strip() != (after_title or '').strip():
        kinds.append('Title')
    if [s for s in a if IMAGE.match(s)] != [s for s in b if IMAGE.match(s)]:
        kinds.append('Image')
    return kinds, changed


def side_by_side(before_text, after_text, context=1):
    """Two HTML snippets: before with deletions marked, after with insertions.

    Long unchanged stretches are cut to `context` sentences around a change,
    a page has hundreds of sentences and only a few change.
    """
    a, b = sentences(before_text), sentences(after_text)
    left, right = [], []
    ops = difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes()
    for n, (op, i1, i2, j1, j2) in enumerate(ops):
        if op == 'equal':
            part = a[i1:i2]
            first, last = n == 0, n == len(ops) - 1
            if len(part) > 2 * context + 1 or (first and len(part) > context) or (last and len(part) > context):
                head = [] if first else part[:context]
                tail = [] if last else part[-context:]
                cut = [html.escape(s) for s in head] + ['<span class="gap">…</span>'] + [html.escape(s) for s in tail]
            else:
                cut = [html.escape(s) for s in part]
            left += cut
            right += cut
            continue
        if i2 > i1:
            left.append('<del>' + html.escape(' '.join(a[i1:i2])) + '</del>')
        if j2 > j1:
            right.append('<ins>' + html.escape(' '.join(b[j1:j2])) + '</ins>')
    return ' '.join(left), ' '.join(right)
