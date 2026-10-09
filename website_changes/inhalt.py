"""What a page says, taken from its HTML: headings, texts, buttons, images.

Elementor writes an HTML copy of the page into every revision. This turns it
into a flat list of parts that can be compared between two revisions. Only
the standard library - no new package.
"""
import html
import re
from html.parser import HTMLParser

BLOCK = {'p', 'li', 'blockquote', 'figcaption', 'td', 'th', 'dd', 'dt'}
HEADINGS = {'h1', 'h2', 'h3', 'h4', 'h5', 'h6'}


def _clean(text):
    return re.sub(r'\s+', ' ', html.unescape(text or '')).strip()


class _Leser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.teile = []          # (kind, text, extra)
        self.stapel = []         # open tags we collect text for
        self.puffer = []
        self.link = None         # (href, is_button)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'img':
            src = a.get('src') or a.get('data-src') or ''
            if src:
                self.teile.append(('image', a.get('alt') or '', src.split('?')[0]))
            return
        if tag == 'a':
            klasse = a.get('class') or ''
            self.link = (a.get('href') or '', 'button' in klasse or a.get('role') == 'button')
        if tag in HEADINGS or tag in BLOCK or tag == 'a':
            self.stapel.append(tag)
            self.puffer.append([])

    def handle_endtag(self, tag):
        if not self.stapel or self.stapel[-1] != tag:
            return
        self.stapel.pop()
        text = _clean(''.join(self.puffer.pop()))
        if self.puffer:                       # nested: give the text to the parent too
            self.puffer[-1].append(' ' + text + ' ')
        if not text:
            return
        if tag in HEADINGS:
            self.teile.append(('heading', text, tag))
        elif tag == 'a':
            href, knopf = self.link or ('', False)
            if knopf:
                self.teile.append(('button', text, href))
            self.link = None
        elif not self.stapel:                 # outermost block only, no doubles
            self.teile.append(('text', text, tag))

    def handle_data(self, data):
        if self.puffer:
            self.puffer[-1].append(data)


def parts(html_text):
    """[(kind, text, extra)] in page order: heading/text/button/image."""
    leser = _Leser()
    leser.feed(html_text or '')
    return leser.teile


def summary(html_text):
    teile = parts(html_text)
    zahl = {k: sum(1 for t in teile if t[0] == k) for k in ('heading', 'text', 'button', 'image')}
    return {'counts': zahl, 'headings': [t[1] for t in teile if t[0] == 'heading'][:5],
            'bytes': len(html_text or '')}
