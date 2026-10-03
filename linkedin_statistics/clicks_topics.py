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


def _start():
    """The list of 03.10.2026: {post_id: {'topic': key, 'format': short|company}}."""
    global _START
    if _START is None:
        path = os.path.join(os.path.dirname(__file__), 'topics_start.json')
        try:
            with open(path, encoding='utf-8') as f:
                _START = {str(k): v for k, v in json.load(f).items() if isinstance(v, dict)}
        except (OSError, ValueError):
            _START = {}
    return _START


def start_list():
    """post_id -> topic key, from the list of 03.10.2026."""
    return {k: v['topic'] for k, v in _start().items() if v.get('topic') in TOPIC_NAMES}


def start_formats():
    """post_id -> 'short' | 'company', suggested on 03.10.2026 from the post
    picture (light template with Octo = short, petrol = company). Before 2026
    there were no short posts."""
    return {k: v['format'] for k, v in _start().items() if v.get('format') in FORMAT_NAMES}


# Post format: the two series of the posting rhythm (Planner field post_type).
FORMATS = [('short', 'Short'), ('company', 'Company')]
FORMAT_NAMES = dict(FORMATS)

_TABLE_READY = False


def ensure_table():
    """The table is created on first use (Render runs no migrate on deploy).
    One row per post with a manual choice; either column may be empty."""
    global _TABLE_READY
    if _TABLE_READY:
        return
    with connection.cursor() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS linkedin_post_topics (
            post_id     VARCHAR(64) NOT NULL PRIMARY KEY,
            topic       VARCHAR(8)  NULL,
            post_format VARCHAR(8)  NULL,
            updated_at  DATETIME    DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        )""")
        # a table from the first version (topic only, NOT NULL)
        c.execute("""SELECT COLUMN_NAME FROM information_schema.COLUMNS
                     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'linkedin_post_topics'""")
        spalten = {r[0].lower() for r in c.fetchall()}
        if 'post_format' not in spalten:
            c.execute("ALTER TABLE linkedin_post_topics ADD COLUMN post_format VARCHAR(8) NULL")
            c.execute("ALTER TABLE linkedin_post_topics MODIFY topic VARCHAR(8) NULL")
    _TABLE_READY = True


def manual_choices():
    """(post_id -> topic, post_id -> format) set in the Clicks table."""
    ensure_table()
    with connection.cursor() as c:
        c.execute("SELECT post_id, topic, post_format FROM linkedin_post_topics")
        rows = c.fetchall()
    topics = {str(p): t for p, t, f in rows if t in TOPIC_NAMES}
    formats = {str(p): f for p, t, f in rows if f in FORMAT_NAMES}
    return topics, formats


def manual_topics():
    return manual_choices()[0]


def _set(post_id, column, value):
    ensure_table()
    with connection.cursor() as c:
        c.execute(f"INSERT INTO linkedin_post_topics (post_id, {column}) VALUES (%s, %s) "
                  f"ON DUPLICATE KEY UPDATE {column} = VALUES({column})", [post_id, value or None])
        # nothing left to remember: the post falls back to list, Planner or rules
        c.execute("DELETE FROM linkedin_post_topics WHERE post_id = %s "
                  "AND topic IS NULL AND post_format IS NULL", [post_id])


def set_topic(post_id, topic):
    """topic '' removes the manual choice - the post falls back to the list
    or the rules."""
    _set(post_id, 'topic', topic)


def set_format(post_id, fmt):
    """fmt '' removes the manual choice - back to the Planner or the list."""
    _set(post_id, 'post_format', fmt)


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


def resolve_format(post_id, manual, planner):
    """(format or '', source): manual > Planner post_type > list of 03.10.2026."""
    pid = str(post_id)
    if pid in manual:
        return manual[pid], 'manual'
    if pid in planner:
        return planner[pid], 'planner'
    start = start_formats()
    if pid in start:
        return start[pid], 'suggested'
    return '', ''
