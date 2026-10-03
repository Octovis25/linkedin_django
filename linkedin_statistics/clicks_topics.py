"""Topics of the LinkedIn posts, for the Clicks tab.

Single words turned out to be too unstable to say anything (03.10.2026: 92
words tested, none held up). Broader content themes are the next coarser
level, so every post gets exactly one topic.

Where a post's topic comes from, in this order:

1. ``manual``  - set in the Clicks tab, stored in ``linkedin_post_topics``
2. ``checked`` - the list of 03.10.2026 (``topics_start.json``): suggested
   from the text and checked by hand, 80 posts
3. ``auto``    - keyword rules below, for every newer post

The rules are deliberately simple and visible. A wrong suggestion costs one
click in the table; a clever classifier nobody can follow costs trust.
"""
import json
import os
import re

from django.db import connection

TOPICS = [
    ('DM', 'Data Management'),
    ('SQ', 'SOP, Quality & GCP'),
    ('OV', 'Oversight'),
    ('SD', 'Study Design & Planning'),
    ('ST', 'Statistics & R'),
    ('SV', 'Services & Team'),
    ('EV', 'Events & Seasons'),
    ('OT', 'Other'),
]
TOPIC_KEYS = [k for k, _ in TOPICS]
TOPIC_NAMES = dict(TOPICS)

# Events are recognised in the first lines: a post that merely mentions
# "holiday" further down is not a seasonal post.
EVENT = re.compile(r"world [a-z' ]{0,30}day|advent|easter|season.s greetings|christmas|"
                   r"welcome,? 20\d\d|awareness month|international [a-z ]{0,30}day", re.I)

RULES = [
    ('DM', r"data management|data manager|quer(?:y|ies)|ecrf|\bedc\b|edit check|data cleaning|"
           r"clean data|database|user acceptance|\buat\b|change request|data quality|data point|dataset"),
    ('SQ', r"\bsops?\b|standard operating|procedure|documentation|quality management|\bqms\b|"
           r"\bich\b|\bgcp\b|e6\(r3\)|regulator|audit|inspection|complian"),
    ('OV', r"oversight|rbqm|risk.based|monitoring|sponsor"),
    ('SD', r"protocol|study design|feasibility|planning|set.?up"),
    ('ST', r"biostatistic|statistic|statistician|\bsas\b|\br\b(?=[ ,.])|analys[ie]s|reproducib|"
           r"significan|sample size"),
    ('SV', r"our team|our services|we help|partner|tailor|expert support|contact us|pitch in|"
           r"in-house team"),
]
RULES = [(k, re.compile(p, re.I)) for k, p in RULES]
HASHTAG = re.compile(r"#\w+")


def suggest(text, first_line='', category=''):
    """Topic key for a post from its text. Hashtags are ignored - the same
    block of hashtags sits under almost every post."""
    if (category or '').lower() == 'event':
        return 'EV'
    head = ((first_line or '') + ' ' + (text or '')[:200])
    if EVENT.search(head):
        return 'EV'
    body = HASHTAG.sub(' ', text or first_line or '')
    best, hits = 'OT', 0
    for key, rx in RULES:
        n = len(rx.findall(body))
        if n > hits:
            best, hits = key, n
    return best


def hook_type(first_line):
    """q = question, n = number/list, w = starts with We/Our, s = statement."""
    f = (first_line or '').strip()
    if '?' in f[:120]:
        return 'q'
    if re.match(r"^\W*\d", f) or re.search(r"\b\d+ (reasons|ways|steps|tips)\b", f, re.I):
        return 'n'
    if re.match(r"^(we|our)\b", re.sub(r"^\W+", '', f), re.I):
        return 'w'
    return 's'


HOOK_NAMES = {'q': 'question', 'n': 'number', 'w': '“We…”', 's': 'statement'}

_START = None


def start_list():
    global _START
    if _START is None:
        path = os.path.join(os.path.dirname(__file__), 'topics_start.json')
        try:
            with open(path, encoding='utf-8') as f:
                _START = {str(k): v for k, v in json.load(f).items() if v in TOPIC_NAMES}
        except (OSError, ValueError):
            _START = {}
    return _START


_TABLE_READY = False


def ensure_table():
    """The table is created on first use (Render runs no migrate on deploy)."""
    global _TABLE_READY
    if _TABLE_READY:
        return
    with connection.cursor() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS linkedin_post_topics (
            post_id    VARCHAR(64) NOT NULL PRIMARY KEY,
            topic      VARCHAR(8)  NOT NULL,
            updated_at DATETIME    DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        )""")
    _TABLE_READY = True


def manual_topics():
    ensure_table()
    with connection.cursor() as c:
        c.execute("SELECT post_id, topic FROM linkedin_post_topics")
        return {str(p): t for p, t in c.fetchall() if t in TOPIC_NAMES}


def set_topic(post_id, topic):
    """topic '' removes the manual choice - the post falls back to the list
    or the rules."""
    ensure_table()
    with connection.cursor() as c:
        if not topic:
            c.execute("DELETE FROM linkedin_post_topics WHERE post_id = %s", [post_id])
        else:
            c.execute("INSERT INTO linkedin_post_topics (post_id, topic) VALUES (%s, %s) "
                      "ON DUPLICATE KEY UPDATE topic = VALUES(topic)", [post_id, topic])


EVENTS = 'EV'


def split_events(posts):
    """(posts for the analysis, event posts). Advent, Christmas, world days …
    follow their own rules (date fixed, other audience) and stay out of every
    model and the main table; the tab lists them separately."""
    rest = [p for p in posts if p.get('topic') != EVENTS]
    events = [p for p in posts if p.get('topic') == EVENTS]
    return rest, events


def resolve(post_id, text, first_line, category, manual):
    """(topic key, source) for one post."""
    pid = str(post_id)
    if pid in manual:
        return manual[pid], 'manual'
    start = start_list()
    if pid in start:
        return start[pid], 'checked'
    return suggest(text, first_line, category), 'auto'
