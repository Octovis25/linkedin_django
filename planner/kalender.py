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
from django.http import JsonResponse
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

def _tabellen_anlegen():
    """Create both tables, and fill the list once - only when it is brand new."""
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

def _posts_des_jahres(jahr):
    """The posts planned in that year, with their send time worked out.

    Nothing is copied: this is planner_posts, read through the same
    _attach_send_time() the Scheduled page uses, so both pages agree on when a
    post goes out and on how binding that is.
    """
    with connection.cursor() as c:
        zeilen = _q(c, """SELECT p.id, p.title, p.content, p.status, p.planned_date,
                                 p.planned_time, t.name, t.color, p.linkedin_posted,
                                 DATE_FORMAT(p.post_scheduled_at, '%%d.%%m.%%Y %%H:%%i')
                          FROM planner_posts p
                          LEFT JOIN planner_topics t ON p.topic_id = t.id
                          WHERE p.planned_date BETWEEN %s AND %s
                          ORDER BY p.planned_date, p.planned_time, p.id""",
                     [date(jahr, 1, 1), date(jahr, 12, 31)])

    posts = []
    for r in zeilen:
        bg, fg = COLOR_MAP.get(r[7] or 'gray', ('#f5f5f5', '#6c757d'))
        posts.append({
            'id': r[0], 'title': (r[1] or '').strip(), 'content': r[2] or '',
            'status': r[3] or '', 'planned_date': r[4], 'planned_time': r[5],
            'topic_name': r[6] or '', 'bg': bg, 'fg': fg,
            'linkedin_posted': r[8], 'post_scheduled_at_fmt': r[9] or '',
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
        p['zustand'] = ('done' if (p['linkedin_posted'] or p['status'] == 'Posted')
                        else 'sched' if p['verbindlich'] else 'plan')
        p['zustand_text'] = {'done': 'Published', 'sched': 'Scheduled'}.get(
            p['zustand'], p['status'] or 'Planned')
    return posts


def _zustand(termine, posts):
    """How binding a day is. The posts decide; a bare occasion is an open slot."""
    if not posts:
        return 'open' if termine else 'none'
    if all(p['linkedin_posted'] or p['status'] == 'Posted' for p in posts):
        return 'done'
    if any(p['verbindlich'] for p in posts):
        return 'sched'
    return 'plan'


def jahres_tage(jahr):
    """Every single day of the year - all 365 of them, empty ones included.

    The empty days are not filler: the gaps between the occasions are what the
    page is read for.
    """
    nach_tag = {}
    for t in jahres_termine(jahr):
        nach_tag.setdefault(t['datum'], {'termine': [], 'posts': []})['termine'].append(t)
    for p in _posts_des_jahres(jahr):
        nach_tag.setdefault(p['planned_date'], {'termine': [], 'posts': []})['posts'].append(p)

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
def kalender_view(request, jahr=None):
    _tabellen_anlegen()
    try:
        jahr = int(jahr or request.GET.get('jahr') or date.today().year)
    except (TypeError, ValueError):
        jahr = date.today().year
    jahr = max(1970, min(2999, jahr))

    tage = jahres_tage(jahr)
    monate = []
    for nr, name in enumerate(MONATE, start=1):
        im_monat = [t for t in tage if t['monat'] == nr]
        monate.append({
            'nr': nr, 'name': name, 'tage': im_monat,
            'posts': sum(len(t['posts']) for t in im_monat),
            'offen': sum(1 for t in im_monat if t['zustand'] == 'open'),
        })

    return render(request, 'planner/kalender.html', {
        'tab': 'kalender', 'page_title': '\U0001F4C5 Calendar %d' % jahr,
        'jahr': jahr, 'vorjahr': jahr - 1, 'folgejahr': jahr + 1,
        'monate': monate,
        'termine': jahres_termine(jahr),
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
            tag = datum_fuer(regel, jahr)
            raus.append(dict(regel,
                             datum=tag.isoformat() if tag else '',
                             regel_text=regel_text(regel),
                             art_text=ARTEN.get(regel['kind'], regel['kind']),
                             dieses_jahr_versteckt='hide' in ausnahmen.get(regel['id'], {})))
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
