"""The year calendar: dates that come back every year, and what is planned on them.

Two tables, and the split between them is the whole idea:

  planner_recurring_dates   the list you maintain. One row per occasion, and it
                            holds a RULE, not a date - so it answers for 2026
                            and for 2031 alike.
  planner_date_exceptions   one row per deviation you made in ONE year:
                            "Whit Monday, 2028, hidden". Empty for almost every
                            year, which is the point.

A year is never written anywhere. Opening 2031 works the dates out on the spot
from the list, then lets the exceptions for 2031 change what they say. So
correcting an occasion fixes every year at once, and a single year can still
differ where you said so.

Posts are not copied either. The day rows read planner_posts and show the post
itself; the send time is the one _attach_send_time() works out for the Scheduled
page. "Scheduled" therefore means here what it means there - Buffer really has
it - and not merely that the status field says so.
"""
import json
from datetime import date, timedelta

from django.contrib.auth.decorators import login_required
from django.db import connection
from django.http import Http404, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt

from .views import COLOR_MAP, _attach_send_time, _q

# Monday = 0, the same as date.weekday(), so nothing has to be converted.
WOCHENTAGE = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
MONATE = ['January', 'February', 'March', 'April', 'May', 'June',
          'July', 'August', 'September', 'October', 'November', 'December']
ORDINAL = {1: 'first', 2: 'second', 3: 'third', 4: 'fourth', 5: 'fifth', -1: 'last'}

ARTEN = {'holiday': 'Holiday', 'awareness': 'Awareness', 'own': 'Ours'}

# The starter list is a suggestion, not a law - German public holidays plus the
# oncology and clinical-research days. It is written once, when the table is
# created, and from then on it is Ortrud's list to add to and take from.
STARTLISTE = [
    ("New Year's Day",                     'holiday',   'fixed',   1,    1, None, None, None,  7, ''),
    ('World Cancer Day',                   'awareness', 'fixed',   2,    4, None, None, None, 21, 'Oncology'),
    ('International Childhood Cancer Day', 'awareness', 'fixed',   2,   15, None, None, None, 14, 'Oncology'),
    ('Rare Disease Day',                   'awareness', 'last',    2, None, None, None, None, 14, 'Studies'),
    ("International Women's Day",          'awareness', 'fixed',   3,    8, None, None, None, 14, 'Team'),
    ('Good Friday',                        'holiday',   'easter', None, None, None, None,  -2,  7, ''),
    ('Easter Monday',                      'holiday',   'easter', None, None, None, None,   1,  7, ''),
    ('World Health Day',                   'awareness', 'fixed',   4,    7, None, None, None, 14, ''),
    ('Labour Day',                         'holiday',   'fixed',   5,    1, None, None, None,  7, ''),
    ("Mother's Day",                       'awareness', 'nth',     5, None,    6,    2, None, 10, ''),
    ('International Clinical Trials Day',  'awareness', 'fixed',   5,   20, None, None, None, 28, 'Studies'),
    ('Whit Monday',                        'holiday',   'easter', None, None, None, None,  50,  7, ''),
    ('World No Tobacco Day',               'awareness', 'fixed',   5,   31, None, None, None, 14, ''),
    ('World Brain Tumour Day',             'awareness', 'fixed',   6,    8, None, None, None, 14, 'Oncology'),
    ('World Lung Cancer Day',              'awareness', 'fixed',   8,    1, None, None, None, 14, 'Oncology'),
    ('Childhood Cancer Awareness Month',   'awareness', 'fixed',   9,    1, None, None, None, 28, 'Oncology'),
    ('World Patient Safety Day',           'awareness', 'fixed',   9,   17, None, None, None, 14, 'Studies'),
    ('World Heart Day',                    'awareness', 'fixed',   9,   29, None, None, None, 14, ''),
    ('Breast Cancer Awareness Month',      'awareness', 'fixed',  10,    1, None, None, None, 28, 'Oncology'),
    ('German Unity Day',                   'holiday',   'fixed',  10,    3, None, None, None,  7, ''),
    ('World Mental Health Day',            'awareness', 'fixed',  10,   10, None, None, None, 14, ''),
    ('World COPD Day',                     'awareness', 'nth',    11, None,    2,    3, None, 14, ''),
    ('World AIDS Day',                     'awareness', 'fixed',  12,    1, None, None, None, 14, ''),
    ('1st Advent',                         'own',       'before', 12,   24,    6,    3, None, 21, ''),
    ('2nd Advent',                         'own',       'before', 12,   24,    6,    2, None, 14, ''),
    ('3rd Advent',                         'own',       'before', 12,   24,    6,    1, None, 14, ''),
    ('4th Advent',                         'own',       'before', 12,   24,    6,    0, None, 14, ''),
    ('Christmas Eve',                      'holiday',   'fixed',  12,   24, None, None, None, 21, 'Team'),
    ('Christmas Day',                      'holiday',   'fixed',  12,   25, None, None, None, 21, ''),
    ('Boxing Day',                         'holiday',   'fixed',  12,   26, None, None, None, 21, ''),
    ("New Year's Eve",                     'holiday',   'fixed',  12,   31, None, None, None, 14, 'Team'),
]


# ----------------------------------------------------------------- the tables

_tabellen_geprueft = False


def _tabellen_anlegen():
    """Create both tables, and fill the list once - only when it is brand new.

    Checked once per process, not once per page load. views.py learned this the
    hard way: 17 ALTER attempts ran on every single request, each answered with
    an error that an except swallowed. Two CREATE TABLE IF NOT EXISTS and a
    COUNT are cheaper than that, but they are just as pointless the second time
    - the answer cannot change while the process lives. After a deploy the
    workers restart, so a fresh database still gets its tables on the first
    call.
    """
    global _tabellen_geprueft
    if _tabellen_geprueft:
        return
    with connection.cursor() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS planner_recurring_dates (
            id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(160) NOT NULL,
            kind VARCHAR(20) DEFAULT 'awareness',
            rule_type VARCHAR(10) NOT NULL,
            month_no TINYINT NULL,
            day_no TINYINT NULL,
            weekday_no TINYINT NULL,
            nth_no TINYINT NULL,
            easter_offset SMALLINT NULL,
            lead_days SMALLINT DEFAULT 14,
            series VARCHAR(80) DEFAULT '',
            active TINYINT(1) DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS planner_date_exceptions (
            id INT AUTO_INCREMENT PRIMARY KEY,
            recurring_id INT NOT NULL,
            year_no SMALLINT NOT NULL,
            kind VARCHAR(10) NOT NULL,
            new_date DATE NULL,
            new_name VARCHAR(160) NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY je_jahr_und_art (recurring_id, year_no, kind)
        )""")
        c.execute("SELECT COUNT(*) FROM planner_recurring_dates")
        _tabellen_geprueft = True
        if (c.fetchone() or [0])[0]:
            return
        c.executemany(
            """INSERT INTO planner_recurring_dates
               (name, kind, rule_type, month_no, day_no, weekday_no, nth_no,
                easter_offset, lead_days, series)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", STARTLISTE)


# ------------------------------------------------------------- the date maths

def _ostern(jahr):
    """Easter Sunday, by the anonymous Gregorian computus.

    Good Friday, Easter Monday and Whit Monday are all defined against it, so
    this one function carries every movable holiday in the list.
    """
    a = jahr % 19
    b, c = divmod(jahr, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    monat, tag = divmod(h + l - 7 * m + 114, 31)
    return date(jahr, monat, tag + 1)


def _letzter_tag(jahr, monat):
    """The last day of a month - February included, leap years and all."""
    if monat == 12:
        return date(jahr, 12, 31)
    return date(jahr, monat + 1, 1) - timedelta(days=1)


def _nter_wochentag(jahr, monat, wochentag, n):
    """The n-th <weekday> of a month; n = -1 means the last one."""
    if n == -1:
        letzter = _letzter_tag(jahr, monat)
        return letzter - timedelta(days=(letzter.weekday() - wochentag) % 7)
    erster = date(jahr, monat, 1)
    versatz = (wochentag - erster.weekday()) % 7
    return erster + timedelta(days=versatz + (n - 1) * 7)


def datum_fuer(regel, jahr):
    """Work a stored rule out for one year. Returns None if it cannot be read.

    A rule with missing or impossible parts (31 February, a 5th Monday the month
    does not have, a field the row never got) must not bring the whole page
    down - it is one bad row in a list that is maintained by hand. KeyError is
    in the net for exactly that reason: a rule half filled in is the likeliest
    bad row of all.
    """
    art = (regel.get('rule_type') or '').strip()
    try:
        if art == 'fixed':
            return date(jahr, int(regel['month_no']), int(regel['day_no']))
        if art == 'last':
            return _letzter_tag(jahr, int(regel['month_no']))
        if art == 'nth':
            monat = int(regel['month_no'])
            tag = _nter_wochentag(jahr, monat, int(regel['weekday_no']), int(regel['nth_no']))
            return tag if tag.month == monat else None
        if art == 'easter':
            return _ostern(jahr) + timedelta(days=int(regel['easter_offset']))
        if art == 'before':
            # The last <weekday> on or before a fixed date, optionally some
            # weeks further back. This is what the Advent Sundays need: the
            # fourth one is the Sunday on or before 24 December, and the other
            # three are one, two and three Sundays earlier. No fixed date and
            # no "n-th Sunday in December" can say that - in 2026 the fourth
            # Advent is the third Sunday of the month, in 2027 it is not.
            anker = date(jahr, int(regel['month_no']), int(regel['day_no']))
            zurueck = (anker.weekday() - int(regel['weekday_no'])) % 7
            return anker - timedelta(days=zurueck + 7 * int(regel['nth_no'] or 0))
    except (KeyError, TypeError, ValueError):
        return None
    return None


def regel_text(regel):
    """The rule in words, for the list and for the tooltip on a day."""
    art = (regel.get('rule_type') or '').strip()
    try:
        if art == 'fixed':
            return 'fixed · %d %s' % (int(regel['day_no']), MONATE[int(regel['month_no']) - 1])
        if art == 'last':
            return 'moves · last day of %s' % MONATE[int(regel['month_no']) - 1]
        if art == 'nth':
            n = int(regel['nth_no'])
            return 'moves · %s %s in %s' % (
                ORDINAL.get(n, '%dth' % n),
                WOCHENTAGE[int(regel['weekday_no'])],
                MONATE[int(regel['month_no']) - 1])
        if art == 'before':
            wochen = int(regel['nth_no'] or 0)
            wann = '%s on or before %d %s' % (WOCHENTAGE[int(regel['weekday_no'])],
                                              int(regel['day_no']),
                                              MONATE[int(regel['month_no']) - 1])
            if wochen:
                wann += ', %d week%s earlier' % (wochen, '' if wochen == 1 else 's')
            return 'moves \u00b7 ' + wann
        if art == 'easter':
            versatz = int(regel['easter_offset'])
            if versatz == 0:
                return 'moves · Easter Sunday'
            return 'moves · Easter %s%d days' % ('+' if versatz > 0 else '−', abs(versatz))
    except (KeyError, TypeError, ValueError, IndexError):
        pass
    return 'rule incomplete'


SPALTEN = ['id', 'name', 'kind', 'rule_type', 'month_no', 'day_no', 'weekday_no',
           'nth_no', 'easter_offset', 'lead_days', 'series', 'active']


def _regeln_lesen(nur_aktive=True):
    with connection.cursor() as c:
        sql = 'SELECT %s FROM planner_recurring_dates' % ', '.join(SPALTEN)
        if nur_aktive:
            sql += ' WHERE active=1'
        sql += ' ORDER BY id'
        return [dict(zip(SPALTEN, r)) for r in _q(c, sql)]


def _ausnahmen_lesen(jahr):
    """{recurring_id: {kind: (new_date, new_name)}} for one year."""
    raus = {}
    with connection.cursor() as c:
        for rid, art, neues_datum, neuer_name in _q(c,
                """SELECT recurring_id, kind, new_date, new_name
                   FROM planner_date_exceptions WHERE year_no=%s""", [jahr]):
            raus.setdefault(rid, {})[art] = (neues_datum, neuer_name)
    return raus


def jahres_termine(jahr):
    """Every occasion of one year, with that year's exceptions applied."""
    ausnahmen = _ausnahmen_lesen(jahr)
    termine = []
    for regel in _regeln_lesen():
        eigene = ausnahmen.get(regel['id'], {})
        if 'hide' in eigene:
            continue
        tag = datum_fuer(regel, jahr)
        if 'move' in eigene and eigene['move'][0]:
            tag = eigene['move'][0]
        if tag is None:
            continue
        name = regel['name']
        if 'rename' in eigene and eigene['rename'][1]:
            name = eigene['rename'][1]
        termine.append({
            'id': regel['id'], 'name': name, 'kind': regel['kind'],
            'art_text': ARTEN.get(regel['kind'], regel['kind']),
            'datum': tag, 'lead_days': regel['lead_days'],
            'series': regel['series'] or '',
            'regel_text': regel_text(regel),
            'verschoben': 'move' in eigene,
        })
    termine.sort(key=lambda t: (t['datum'], t['name']))
    return termine


# ------------------------------------------------------------------ the posts

def _tag_aus(stempel):
    """The date out of a 'dd.mm.yyyy hh:mm' stamp, or None if it is not one."""
    try:
        tag, monat, jahr = stempel[:10].split('.')
        return date(int(jahr), int(monat), int(tag))
    except (AttributeError, TypeError, ValueError):
        return None


def _tag_aus_iso(stempel):
    """The date out of Buffer's '2026-09-14T08:00:03.000Z', or None."""
    try:
        jahr, monat, tag = stempel[:10].split('-')
        return date(int(jahr), int(monat), int(tag))
    except (AttributeError, TypeError, ValueError):
        return None


def gesendet_am_aus(zeilen):
    """{post id: the day it went out}, from Buffer's rows.

    Buffer answers in ISO, the planner formats German. Reading one with the
    other's rules turns 09.11. into 11.09. without a word - a post two months
    out of place and nothing anywhere saying so. Hence its own function, and
    its own checks.
    """
    raus = {}
    for zeile in zeilen:
        kennung, _faellig, gesendet = zeile[0], zeile[1], zeile[2]
        if not kennung:
            continue
        tag = _tag_aus_iso(gesendet)
        if tag:
            raus[kennung] = tag
    return raus


def ist_veroeffentlicht(post, gesendet_am=None, wartet_bei_buffer=False):
    """Did this post really go out?

    linkedin_posted is a flag our own code sets - and our own code has set it
    wrongly. The promotion to Posted marked #53 as published on 20.09., a day
    before it was due; the status was put back by hand, the flag stayed. A
    calendar that believed it showed a post still waiting in Buffer as
    "Published", and the one scheduled post on the page could not be found.

    Buffer's sent_at is the witness from outside. When Buffer has sent it, it
    went out. When Buffer is still holding it, the flag is overruled. Only
    where Buffer knows nothing - a post sent through LinkedIn or Make directly -
    is the flag all there is.
    """
    if gesendet_am or post.get('status') == 'Posted':
        return True
    if wartet_bei_buffer:
        return False
    return bool(post.get('linkedin_posted'))


def fehlt_medium(post):
    """True when a post still to go out has nothing to show: no image, no GIF,
    no video - neither on the post nor at Buffer.

    Ortrud, 25.09.2026: the calendar should say when a picture or a video is
    missing. Only for posts that have not gone out: a published post cannot
    be given one any more, and a warning nobody can act on is noise. Buffer
    counts as a witness too - a post can have been scheduled with its image
    straight from Buffer, and then the planner row is empty but nothing is
    missing.
    """
    if post.get('veroeffentlicht'):
        return False
    return not (post.get('hat_bild') or post.get('gif_nc_path')
                or post.get('video_nc_path') or post.get('buffer_hat_bild'))


def kalendertag_fuer(post, gesendet_am=None):
    """Which day a post belongs on. Three answers, in the order they are trusted:

      1. the day it went out - that happened, and nothing outranks it
      2. the day it is due to go out (send_time)
      3. the day it is planned for

    2 and 3 are not always the same, and when they differ the send date is the
    one that will happen: post #53 is planned for 12 May and sits in Buffer for
    21 September. Placing it in May would put a September send time on a May
    row, and the gap in September would look free.

    1 exists because publishing clears post_scheduled_at. Without it a post
    that has gone out falls back to its plan, or - if it never had one - out of
    the year altogether. That is how posts went missing from the page.
    """
    return gesendet_am or _tag_aus(post.get('send_time')) or post.get('planned_date')


def _posts_des_jahres(jahr, nur_oj=False):
    """The posts planned in that year, with their send time worked out.

    Nothing is copied: this is planner_posts, read through the same
    _attach_send_time() the Scheduled page uses, so both pages agree on when a
    post goes out and on how binding that is.
    """
    # is_oj splits the planner in two, and the two are not to be mixed up:
    # every other page hides is_oj posts, so a calendar that showed both would
    # disagree with the rest of the planner about what exists. The OJ side gets
    # a calendar of its own instead - same page, other half of the data.
    #
    # Three places know when a post might go out, and all three have to be
    # asked. Filtering on planned_date alone would miss every post that was
    # scheduled into this year from another one - and show posts here that have
    # long since been moved out of it.
    aus_buffer = set()
    gesendet = {}
    wartend = set()
    buffer_mit_bild = set()
    with connection.cursor() as c:
        try:
            c.execute("""SELECT planner_post_id, COALESCE(due_at, ''), COALESCE(sent_at, ''),
                                COALESCE(has_image, 0)
                         FROM buffer_posts_posted
                         WHERE LEFT(due_at, 4) = %s OR LEFT(sent_at, 4) = %s""",
                      [str(jahr), str(jahr)])
            zeilen = c.fetchall()
            aus_buffer = {r[0] for r in zeilen if r[0]}
            gesendet = gesendet_am_aus(zeilen)
            # A Buffer row without a send date: Buffer has it and has not
            # sent it. That settles "published?" whatever our own flag says.
            wartend = {r[0] for r in zeilen if r[0] and not (r[2] or '').strip()}
            buffer_mit_bild = {r[0] for r in zeilen if r[0] and r[3]}
        except Exception as fehler:
            print('calendar, dates from buffer:', fehler)

        bedingung = """(p.planned_date BETWEEN %s AND %s
                        OR YEAR(p.post_scheduled_at) = %s)"""
        werte = [1 if nur_oj else 0, date(jahr, 1, 1), date(jahr, 12, 31), jahr]
        if aus_buffer:
            bedingung += ' OR p.id IN (%s)' % ','.join(['%s'] * len(aus_buffer))
            werte += sorted(aus_buffer)

        zeilen = _q(c, """SELECT p.id, p.title, p.content, p.status, p.planned_date,
                                 p.planned_time, t.name, t.color, p.linkedin_posted,
                                 DATE_FORMAT(p.post_scheduled_at, '%%d.%%m.%%Y %%H:%%i'),
                                 COALESCE(LENGTH(p.image), 0) > 0,
                                 COALESCE(p.gif_nc_path, ''), COALESCE(p.video_nc_path, '')
                          FROM planner_posts p
                          LEFT JOIN planner_topics t ON p.topic_id = t.id
                          WHERE COALESCE(p.is_oj, 0) = %s AND (""" + bedingung + """)
                          ORDER BY p.planned_date, p.planned_time, p.id""", werte)

    posts = []
    for r in zeilen:
        bg, fg = COLOR_MAP.get(r[7] or 'gray', ('#f5f5f5', '#6c757d'))
        posts.append({
            'id': r[0], 'title': (r[1] or '').strip(), 'content': r[2] or '',
            'status': r[3] or '', 'planned_date': r[4], 'planned_time': r[5],
            'topic_name': r[6] or '', 'bg': bg, 'fg': fg,
            'linkedin_posted': r[8], 'post_scheduled_at_fmt': r[9] or '',
            'hat_bild': bool(r[10]), 'gif_nc_path': r[11] or '', 'video_nc_path': r[12] or '',
            'buffer_hat_bild': r[0] in buffer_mit_bild,
        })
    _attach_send_time(posts)

    for p in posts:
        if not p['title']:
            roh = (p['content'] or '').replace('\n', ' ').strip()
            p['title'] = (roh[:70] + '…') if len(roh) > 70 else (roh or 'Untitled')
        # "Binding" means Buffer really has it - not that the status field says so.
        p['verbindlich'] = p.get('send_time_source') in ('told to Buffer', 'from Buffer')
        # The time alone; the day is already the row it sits in.
        p['uhrzeit'] = p.get('send_time', '')[-5:] if len(p.get('send_time', '')) >= 5 else ''
        # Worked out here rather than in the template: the same three words
        # drive the colour, the pill and the filter, and they should not be
        # spelled out three times in template logic.
        p['veroeffentlicht'] = ist_veroeffentlicht(
            p, gesendet.get(p['id']), p['id'] in wartend)
        p['zustand'] = ('done' if p['veroeffentlicht']
                        else 'sched' if p['verbindlich'] else 'plan')
        p['zustand_text'] = {'done': 'Published', 'sched': 'Scheduled'}.get(
            p['zustand'], p['status'] or 'Planned')
        p['kalendertag'] = kalendertag_fuer(p, gesendet.get(p['id']))
        p['ohne_medium'] = fehlt_medium(p)
        # Moving from the calendar changes the PLAN. A post that has gone out
        # has no plan left to change. One Buffer is holding keeps its send
        # time there - our code can create and delete at Buffer, not move -
        # so the row says so and offers the way to re-schedule it.
        p['verschiebbar'] = not p['veroeffentlicht']
        p['bei_buffer'] = p['zustand'] == 'sched'
        tag_fuer_feld = p['planned_date'] or p['kalendertag']
        p['plan_iso'] = tag_fuer_feld.isoformat() if tag_fuer_feld else ''
        p['abweichend'] = bool(p['planned_date'] and p['kalendertag']
                               and p['kalendertag'] != p['planned_date'])

    # A post scheduled into another year is that year's business, not ours.
    return [p for p in posts if p['kalendertag'] and p['kalendertag'].year == jahr]


def ohne_datum_gruppe(post):
    """Which of the two groups a dateless post belongs in.

    A draft without a date is an idea, and an idea without a date is fine. A
    post that WENT OUT without a date is something else: the day it happened is
    not on record anywhere, and it cannot be put in the year at all. Thirty
    ideas and three lost records in one undifferentiated list means the three
    are never seen.
    """
    return 'raus' if (post.get('linkedin_posted')
                      or post.get('status') == 'Posted') else 'offen'


def posts_ohne_datum(grenze=200, nur_oj=False):
    """Posts that carry no date at all - not planned, not scheduled, not sent.

    They cannot be put on a day, and inventing one would be worse than leaving
    them off: a made-up day in a calendar is read as a fact. So they are named
    instead, under the year, where they can be given a date.

    They exist because publishing clears post_scheduled_at, and a post that
    went out through LinkedIn or Make never had a Buffer row to keep a date in.
    """
    mit_buffer_datum = set()
    with connection.cursor() as c:
        try:
            c.execute("""SELECT planner_post_id FROM buffer_posts_posted
                         WHERE COALESCE(due_at, '') <> '' OR COALESCE(sent_at, '') <> ''""")
            mit_buffer_datum = {r[0] for r in c.fetchall() if r[0]}
        except Exception as fehler:
            print('calendar, posts without a date:', fehler)

        zeilen = _q(c, """SELECT p.id, p.title, p.content, p.status, t.name, t.color,
                                 p.linkedin_posted, p.created_at
                          FROM planner_posts p
                          LEFT JOIN planner_topics t ON p.topic_id = t.id
                          WHERE COALESCE(p.is_oj, 0) = %s
                            AND p.planned_date IS NULL AND p.post_scheduled_at IS NULL
                          ORDER BY p.created_at DESC""", [1 if nur_oj else 0])

    raus = []
    for r in zeilen:
        if r[0] in mit_buffer_datum:
            continue
        bg, fg = COLOR_MAP.get(r[5] or 'gray', ('#f5f5f5', '#6c757d'))
        titel = (r[1] or '').strip()
        if not titel:
            roh = (r[2] or '').replace('\n', ' ').strip()
            titel = (roh[:70] + '\u2026') if len(roh) > 70 else (roh or 'Untitled')
        eintrag = {'id': r[0], 'title': titel, 'status': r[3] or '',
                   'topic_name': r[4] or '', 'bg': bg, 'fg': fg,
                   'linkedin_posted': r[6], 'created_at': r[7]}
        eintrag['gruppe'] = ohne_datum_gruppe(eintrag)
        raus.append(eintrag)
        if len(raus) >= grenze:
            break
    return raus


def _schluessel(text):
    """Lowercase, apostrophes out, everything else that is not a letter or a
    digit becomes one space - so "World Heart Day – 29 September" and
    "World Heart Day" meet, and "Mother's Day" meets "Mothers Day"."""
    import re as _re
    t = (text or '').lower().replace("'", '').replace('\u2019', '')
    return ' ' + ' '.join(_re.findall(r'[0-9a-zäöüß]+', t)) + ' '


def vorschlaege_fuer(termine, kandidaten):
    """Dateless posts that name one of this day's occasions in their title.

    Only posts without any date are offered - a post that is already planned
    somewhere is never pulled off its day by a suggestion. And only whole
    words match: "Labour Day" must not claim a post about "Labour Daycare".

    Only posts on Ready are offered. A draft is not finished, and nothing
    unfinished turns up in the calendar unless someone gives it a date by
    hand (Ortrud, 25.09.: drafts and dateless posts do not go into the
    calendar by themselves). Archive is discarded, not waiting.
    """
    namen = [_schluessel(t.get('name')) for t in termine]
    namen = [n for n in namen if len(n.strip()) >= 4]
    raus, gesehen = [], set()
    for post in kandidaten:
        if post.get('status') != 'Ready':
            continue
        titel = _schluessel(post.get('title'))
        if post.get('id') in gesehen:
            continue
        if any(n in titel for n in namen):
            raus.append(post)
            gesehen.add(post.get('id'))
    return raus


def _zustand(termine, posts):
    """How binding a day is. The posts decide; a bare occasion is an open slot."""
    if not posts:
        return 'open' if termine else 'none'
    if all(p['veroeffentlicht'] for p in posts):
        return 'done'
    if any(p['verbindlich'] for p in posts):
        return 'sched'
    return 'plan'


def jahres_tage(jahr, nur_oj=False):
    """Every single day of the year - all 365 of them, empty ones included.

    The empty days are not filler: the gaps between the occasions are what the
    page is read for.
    """
    nach_tag = {}
    # The OJ side is a plain calendar: days and posts, no world days and no
    # holidays. Those belong to the planner's editorial year, and putting them
    # on a personal calendar would only be noise to read past.
    for t in ([] if nur_oj else jahres_termine(jahr)):
        nach_tag.setdefault(t['datum'], {'termine': [], 'posts': []})['termine'].append(t)
    for p in _posts_des_jahres(jahr, nur_oj):
        nach_tag.setdefault(p['kalendertag'], {'termine': [], 'posts': []})['posts'].append(p)

    heute = date.today()
    tage = []
    tag = date(jahr, 1, 1)
    while tag.year == jahr:
        eintrag = nach_tag.get(tag, {'termine': [], 'posts': []})
        tage.append({
            'datum': tag,
            'iso': tag.isoformat(),
            'tag': tag.day,
            'monat': tag.month,
            'monat_name': MONATE[tag.month - 1],
            'wochentag': WOCHENTAGE[tag.weekday()],
            'wochenende': tag.weekday() >= 5,
            'heute': tag == heute,
            'termine': eintrag['termine'],
            'posts': eintrag['posts'],
            'zustand': _zustand(eintrag['termine'], eintrag['posts']),
            # Flattened for the row: the names in the cell, the rules in the
            # tooltip, so one day never grows into a paragraph.
            'anlass_text': ', '.join(t['name'] for t in eintrag['termine']),
            'anlass_titel': ' | '.join(
                '%s — %s, draft %s d ahead' % (t['name'], t['regel_text'], t['lead_days'])
                for t in eintrag['termine']),
        })
        tag += timedelta(days=1)
    return tage


# ------------------------------------------------------------------ the pages

@login_required
def kalender_view(request, jahr=None, nur_oj=False):
    # One view serves both calendars, so the check cannot sit on a decorator:
    # /planner/kalender/ is everybody's, /planner/kalender/oj/ is not.
    if nur_oj and not request.user.is_superuser:
        raise Http404
    _tabellen_anlegen()
    try:
        jahr = int(jahr or request.GET.get('jahr') or date.today().year)
    except (TypeError, ValueError):
        jahr = date.today().year
    jahr = max(1970, min(2999, jahr))
    try:
        monat = int(request.GET.get('m') or 0)
    except (TypeError, ValueError):
        monat = 0
    if not 1 <= monat <= 12:
        # No month asked for: the current one when we are looking at this year,
        # otherwise the whole year at once.
        monat = date.today().month if jahr == date.today().year else 0

    tage = jahres_tage(jahr, nur_oj)
    monate = []
    for nr, name in enumerate(MONATE, start=1):
        im_monat = [t for t in tage if t['monat'] == nr]
        monate.append({
            'nr': nr, 'name': name, 'tage': im_monat,
            'posts': sum(len(t['posts']) for t in im_monat),
            'offen': sum(1 for t in im_monat if t['zustand'] == 'open'),
            'ohne_medium': sum(1 for t in im_monat for p in t['posts'] if p.get('ohne_medium')),
        })

    # Two calendars, two addresses. Everything the page builds a link from -
    # the year arrows, the month, a new post - hangs off this one string, so
    # the OJ side can never quietly link back into the other half.
    basis = '/planner/kalender/oj/' if nur_oj else '/planner/kalender/'
    ohne_datum = posts_ohne_datum(nur_oj=nur_oj)
    offen = [p for p in ohne_datum if p['gruppe'] == 'offen']
    for t in tage:
        t['vorschlaege'] = (vorschlaege_fuer(t['termine'], offen)
                            if (t['termine'] and not t['posts']) else [])

    return render(request, 'planner/kalender.html', {
        'tab': 'kalender',
        'page_title': ('\U0001F4C5 OJ calendar %d' if nur_oj
                       else '\U0001F4C5 Calendar %d') % jahr,
        'nur_oj': nur_oj, 'basis': basis,
        'jahr': jahr, 'vorjahr': jahr - 1, 'folgejahr': jahr + 1,
        'monate': monate,
        'monat': monat,
        'ohne_datum': ohne_datum,
        'ohne_datum_raus': [p for p in ohne_datum if p['gruppe'] == 'raus'],
        'ohne_datum_offen': [p for p in ohne_datum if p['gruppe'] == 'offen'],
        'termine': [] if nur_oj else jahres_termine(jahr),
        'wochentage': WOCHENTAGE,
        'monatsnamen': MONATE,
    })


@csrf_exempt
@login_required
def kalender_api(request):
    """Add a date to the list, take one out, or bend one for a single year."""
    _tabellen_anlegen()

    if request.method == 'GET':
        try:
            jahr = int(request.GET.get('jahr') or date.today().year)
        except (TypeError, ValueError):
            jahr = date.today().year
        ausnahmen = _ausnahmen_lesen(jahr)
        raus = []
        for regel in _regeln_lesen(nur_aktive=False):
            eigene = ausnahmen.get(regel['id'], {})
            berechnet = datum_fuer(regel, jahr)
            # What the rule says, and what this one year has been told instead.
            # Both go out, so the page can offer "back to the rule" without
            # having to work the rule out a second time in JavaScript.
            tag = (eigene['move'][0] if (eigene.get('move') and eigene['move'][0])
                   else berechnet)
            name = (eigene['rename'][1] if (eigene.get('rename') and eigene['rename'][1])
                    else regel['name'])
            raus.append(dict(regel,
                             datum=tag.isoformat() if tag else '',
                             berechnet=berechnet.isoformat() if berechnet else '',
                             name_im_jahr=name,
                             verschoben=bool(eigene.get('move')),
                             umbenannt=bool(eigene.get('rename')),
                             regel_text=regel_text(regel),
                             art_text=ARTEN.get(regel['kind'], regel['kind']),
                             dieses_jahr_versteckt='hide' in eigene))
        return JsonResponse({'jahr': jahr, 'termine': raus})

    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    try:
        daten = json.loads(request.body or '{}')
    except ValueError:
        return JsonResponse({'error': 'Could not read the request'}, status=400)
    aktion = daten.get('action', '')

    if aktion == 'create':
        name = (daten.get('name') or '').strip()
        art = (daten.get('rule_type') or '').strip()
        if not name:
            return JsonResponse({'error': 'The date needs a name'}, status=400)
        if art not in ('fixed', 'last', 'nth', 'easter', 'before'):
            return JsonResponse({'error': 'Unknown kind of rule'}, status=400)

        def zahl(feld, klein, gross):
            try:
                wert = int(daten.get(feld))
            except (TypeError, ValueError):
                return None
            return wert if klein <= wert <= gross else None

        regel = {'rule_type': art,
                 'month_no': zahl('month_no', 1, 12),
                 'day_no': zahl('day_no', 1, 31),
                 'weekday_no': zahl('weekday_no', 0, 6),
                 'nth_no': zahl('nth_no', -1, 5),
                 'easter_offset': zahl('easter_offset', -400, 400)}
        # Refuse a rule that cannot produce a date, rather than storing a row
        # that reads "rule incomplete" in every year from now on.
        if datum_fuer(regel, date.today().year) is None:
            return JsonResponse({'error': 'Those details do not add up to a date'}, status=400)

        with connection.cursor() as c:
            c.execute("""INSERT INTO planner_recurring_dates
                         (name, kind, rule_type, month_no, day_no, weekday_no,
                          nth_no, easter_offset, lead_days, series)
                         VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                      [name[:160], daten.get('kind') or 'awareness', art,
                       regel['month_no'], regel['day_no'], regel['weekday_no'],
                       regel['nth_no'], regel['easter_offset'],
                       zahl('lead_days', 0, 365) or 14,
                       (daten.get('series') or '').strip()[:80]])
            return JsonResponse({'ok': True, 'id': c.lastrowid})

    if aktion == 'set_active':
        # Out of the calendar, but still in the list - the reversible "remove".
        with connection.cursor() as c:
            c.execute('UPDATE planner_recurring_dates SET active=%s WHERE id=%s',
                      [1 if daten.get('active') else 0, daten.get('id')])
        return JsonResponse({'ok': True})

    if aktion == 'delete':
        with connection.cursor() as c:
            c.execute('DELETE FROM planner_date_exceptions WHERE recurring_id=%s',
                      [daten.get('id')])
            c.execute('DELETE FROM planner_recurring_dates WHERE id=%s', [daten.get('id')])
        return JsonResponse({'ok': True})

    if aktion in ('move_year', 'rename_year', 'reset_year'):
        try:
            rid, jahr = int(daten.get('id')), int(daten.get('jahr'))
        except (TypeError, ValueError):
            return JsonResponse({'error': 'Which date, and which year?'}, status=400)

        with connection.cursor() as c:
            if aktion == 'reset_year':
                c.execute("""DELETE FROM planner_date_exceptions
                             WHERE recurring_id=%s AND year_no=%s
                               AND kind IN ('move', 'rename')""", [rid, jahr])
                return JsonResponse({'ok': True})

            c.execute('SELECT %s FROM planner_recurring_dates WHERE id=%%s'
                      % ', '.join(SPALTEN), [rid])
            zeile = c.fetchone()
            if not zeile:
                return JsonResponse({'error': 'No such date'}, status=404)
            regel = dict(zip(SPALTEN, zeile))

            if aktion == 'move_year':
                try:
                    teile = [int(x) for x in (daten.get('datum') or '').split('-')]
                    neuer_tag = date(*teile)
                except (TypeError, ValueError):
                    return JsonResponse({'error': 'That is not a date'}, status=400)
                # Moving it out of the year would take it off the very page it
                # was set on, and nothing would say where it went.
                if neuer_tag.year != jahr:
                    return JsonResponse(
                        {'error': 'A date can only be moved within %d' % jahr}, status=400)
                # An exception that says what the rule already says is not an
                # exception. Storing it would fill the table with rows that do
                # nothing - and the whole argument for this design is that the
                # table stays nearly empty.
                if neuer_tag == datum_fuer(regel, jahr):
                    c.execute("""DELETE FROM planner_date_exceptions
                                 WHERE recurring_id=%s AND year_no=%s AND kind='move'""",
                              [rid, jahr])
                else:
                    c.execute("""INSERT INTO planner_date_exceptions
                                 (recurring_id, year_no, kind, new_date)
                                 VALUES (%s, %s, 'move', %s)
                                 ON DUPLICATE KEY UPDATE new_date = VALUES(new_date)""",
                              [rid, jahr, neuer_tag])
                return JsonResponse({'ok': True})

            neuer_name = (daten.get('name') or '').strip()[:160]
            if not neuer_name:
                return JsonResponse({'error': 'The date needs a name'}, status=400)
            if neuer_name == regel['name']:
                c.execute("""DELETE FROM planner_date_exceptions
                             WHERE recurring_id=%s AND year_no=%s AND kind='rename'""",
                          [rid, jahr])
            else:
                c.execute("""INSERT INTO planner_date_exceptions
                             (recurring_id, year_no, kind, new_name)
                             VALUES (%s, %s, 'rename', %s)
                             ON DUPLICATE KEY UPDATE new_name = VALUES(new_name)""",
                          [rid, jahr, neuer_name])
            return JsonResponse({'ok': True})

    if aktion == 'set_post_date':
        # Moving a post from the calendar - or placing a dateless one there.
        # Only planned_date changes. What Buffer holds stays as it is.
        try:
            pid = int(daten.get('id'))
            neuer_tag = date(*[int(x) for x in (daten.get('datum') or '').split('-')])
        except (TypeError, ValueError):
            return JsonResponse({'error': 'Which post, and which day?'}, status=400)
        with connection.cursor() as c:
            c.execute("""SELECT COALESCE(status,''), COALESCE(linkedin_posted,0),
                                COALESCE(is_oj,0)
                         FROM planner_posts WHERE id=%s""", [pid])
            zeile = c.fetchone()
            if not zeile:
                return JsonResponse({'error': 'No such post'}, status=404)
            status, veroeffentlicht_flag, ist_oj = zeile
            # An OJ post is moved from the OJ calendar only, and that one is
            # for administrators - the same rule as for looking at it.
            if ist_oj and not request.user.is_superuser:
                return JsonResponse({'error': 'No such post'}, status=404)
            # Read the same way the page reads it: any row Buffer has sent
            # means it went out, any row still unsent means Buffer holds it.
            gesendet_iso, wartet = '', False
            try:
                c.execute("""SELECT COALESCE(sent_at,'')
                             FROM buffer_posts_posted WHERE planner_post_id=%s""", [pid])
                for (stempel,) in c.fetchall():
                    if (stempel or '').strip():
                        gesendet_iso = gesendet_iso or stempel
                    else:
                        wartet = True
            except Exception:
                pass
            raus = ist_veroeffentlicht(
                {'status': status, 'linkedin_posted': veroeffentlicht_flag},
                _tag_aus_iso(gesendet_iso), wartet)
            if raus:
                return JsonResponse({'error': 'This post has gone out - there is no plan left to move'},
                                    status=400)
            c.execute('UPDATE planner_posts SET planned_date=%s WHERE id=%s', [neuer_tag, pid])
        return JsonResponse({'ok': True, 'bei_buffer': wartet})

    if aktion in ('hide_year', 'show_year'):
        # This is the whole of option C: one row per deviation, per year.
        try:
            rid, jahr = int(daten.get('id')), int(daten.get('jahr'))
        except (TypeError, ValueError):
            return JsonResponse({'error': 'Which date, and which year?'}, status=400)
        with connection.cursor() as c:
            if aktion == 'hide_year':
                c.execute("""INSERT IGNORE INTO planner_date_exceptions
                             (recurring_id, year_no, kind) VALUES (%s,%s,'hide')""", [rid, jahr])
            else:
                c.execute("""DELETE FROM planner_date_exceptions
                             WHERE recurring_id=%s AND year_no=%s AND kind='hide'""", [rid, jahr])
        return JsonResponse({'ok': True})

    return JsonResponse({'error': 'Unknown action'}, status=400)
