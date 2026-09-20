"""Do the recurring dates land on the right day - in every year?

This is the part of the calendar that can be quietly wrong for years. A fixed
date is hard to get wrong; the movable ones are not, and nobody notices a
wrong Good Friday in 2029 until 2029.

So the four date functions are cut out of planner/kalender.py as text and run
here against dates that are known from elsewhere. No Django, no database, no
server - the maths either agrees with the calendar or it does not.

    python _tests/kalender_test.py
"""
import os
import sys
from datetime import date, timedelta

HIER = os.path.dirname(os.path.abspath(__file__))
WURZEL = os.path.dirname(HIER)

with open(os.path.join(WURZEL, 'planner', 'kalender.py'), encoding='utf-8') as fh:
    SRC = fh.read()


def herausschneiden(name):
    """Cut one top-level function out of the file that ships.

    Copying it in here would drift away from the original within a week.
    """
    marke = '\ndef %s(' % name
    if marke not in SRC:
        raise SystemExit('not found in planner/kalender.py: ' + name)
    zeilen = SRC[SRC.index(marke) + 1:].split('\n')
    raus = [zeilen[0]]
    for zeile in zeilen[1:]:
        if zeile and not zeile[0].isspace():
            break
        raus.append(zeile)
    return '\n'.join(raus)


def listen_holen(name):
    """Lift a top-level list literal (MONATE, WOCHENTAGE, ...) out of the file."""
    marke = '\n%s = ' % name
    if marke not in SRC:
        raise SystemExit('not found: ' + name)
    rest = SRC[SRC.index(marke) + 1:]
    tiefe, ende = 0, None
    for i, zeichen in enumerate(rest):
        if zeichen in '[{(':
            tiefe += 1
        elif zeichen in ']})':
            tiefe -= 1
            if tiefe == 0:
                ende = i + 1
                break
    return rest[:ende]


RAUM = {'date': date, 'timedelta': timedelta, '__builtins__': __builtins__}
for name in ('WOCHENTAGE', 'MONATE', 'ORDINAL'):
    exec(compile(listen_holen(name), 'planner/kalender.py (cut out)', 'exec'), RAUM)
for name in ('_ostern', '_letzter_tag', '_nter_wochentag', 'datum_fuer',
             'regel_text', '_zustand', '_tag_aus', '_tag_aus_iso',
             'kalendertag_fuer', 'gesendet_am_aus', 'ohne_datum_gruppe'):
    exec(compile(herausschneiden(name), 'planner/kalender.py (cut out)', 'exec'), RAUM)

ostern = RAUM['_ostern']
letzter_tag = RAUM['_letzter_tag']
nter_wochentag = RAUM['_nter_wochentag']
datum_fuer = RAUM['datum_fuer']
regel_text = RAUM['regel_text']
zustand = RAUM['_zustand']
tag_aus = RAUM['_tag_aus']
kalendertag_fuer = RAUM['kalendertag_fuer']
tag_aus_iso = RAUM['_tag_aus_iso']
gesendet_am_aus = RAUM['gesendet_am_aus']
ohne_datum_gruppe = RAUM['ohne_datum_gruppe']

# The seed list, straight out of the shipping file, so the starter dates are
# checked as they really are.
exec(compile(listen_holen('STARTLISTE'), 'planner/kalender.py (cut out)', 'exec'), RAUM)
SPALTEN_NEU = ['name', 'kind', 'rule_type', 'month_no', 'day_no', 'weekday_no',
               'nth_no', 'easter_offset', 'lead_days', 'series']
STARTLISTE = [dict(zip(SPALTEN_NEU, z)) for z in RAUM['STARTLISTE']]

gut = 0
schlecht = 0


def pruefe(name, ok, extra=''):
    global gut, schlecht
    if ok:
        gut += 1
        print('  ok   ' + name)
    else:
        schlecht += 1
        print('  FAIL ' + name + ('  -> ' + str(extra) if extra != '' else ''))


print('\n=== Easter, against the dates printed in every calendar ===')
# Easter carries Good Friday, Easter Monday and Whit Monday. If it is off by a
# day, four holidays are off by a day, every year, silently.
BEKANNT = {
    2000: (4, 23), 2008: (3, 23), 2024: (3, 31), 2025: (4, 20), 2026: (4, 5),
    2027: (3, 28), 2028: (4, 16), 2029: (4, 1), 2030: (4, 21), 2038: (4, 25),
}
for jahr in sorted(BEKANNT):
    monat, tag = BEKANNT[jahr]
    pruefe('Easter %d is %02d.%02d.' % (jahr, tag, monat),
           ostern(jahr) == date(jahr, monat, tag), ostern(jahr))

pruefe('and Easter always falls on a Sunday, 1900 to 2100',
       all(ostern(j).weekday() == 6 for j in range(1900, 2101)))
pruefe('never before 22 March, never after 25 April',
       all(date(j, 3, 22) <= ostern(j) <= date(j, 4, 25) for j in range(1900, 2101)))

print('\n=== The holidays that hang off it ===')
FREITAG = {'rule_type': 'easter', 'easter_offset': -2}
MONTAG = {'rule_type': 'easter', 'easter_offset': 1}
PFINGST = {'rule_type': 'easter', 'easter_offset': 50}
pruefe('Good Friday 2026 is 03.04.', datum_fuer(FREITAG, 2026) == date(2026, 4, 3),
       datum_fuer(FREITAG, 2026))
pruefe('Easter Monday 2026 is 06.04.', datum_fuer(MONTAG, 2026) == date(2026, 4, 6),
       datum_fuer(MONTAG, 2026))
pruefe('Whit Monday 2026 is 25.05.', datum_fuer(PFINGST, 2026) == date(2026, 5, 25),
       datum_fuer(PFINGST, 2026))
pruefe('Good Friday really is a Friday, 2020 to 2040',
       all(datum_fuer(FREITAG, j).weekday() == 4 for j in range(2020, 2041)))
pruefe('and Whit Monday a Monday',
       all(datum_fuer(PFINGST, j).weekday() == 0 for j in range(2020, 2041)))

print('\n=== The last day of a month ===')
pruefe('Rare Disease Day 2026 is 28.02.',
       datum_fuer({'rule_type': 'last', 'month_no': 2}, 2026) == date(2026, 2, 28))
pruefe('but 29.02. in the leap year 2028',
       datum_fuer({'rule_type': 'last', 'month_no': 2}, 2028) == date(2028, 2, 29))
pruefe('2100 is NOT a leap year, so 28.02. again',
       datum_fuer({'rule_type': 'last', 'month_no': 2}, 2100) == date(2100, 2, 28))
pruefe('December ends on the 31st (the month after it is in the next year)',
       letzter_tag(2026, 12) == date(2026, 12, 31))
pruefe('every month ends on the last day it has, 2024 to 2030',
       all(letzter_tag(j, m).month == m and
           (letzter_tag(j, m) + timedelta(days=1)).day == 1
           for j in range(2024, 2031) for m in range(1, 13)))

print('\n=== The n-th weekday ===')
# Mother's Day: second Sunday in May. Weekday 6 = Sunday (Monday = 0).
MUTTER = {'rule_type': 'nth', 'month_no': 5, 'weekday_no': 6, 'nth_no': 2}
COPD = {'rule_type': 'nth', 'month_no': 11, 'weekday_no': 2, 'nth_no': 3}
pruefe("Mother's Day 2026 is 10.05.", datum_fuer(MUTTER, 2026) == date(2026, 5, 10),
       datum_fuer(MUTTER, 2026))
pruefe("Mother's Day 2027 is 09.05.", datum_fuer(MUTTER, 2027) == date(2027, 5, 9),
       datum_fuer(MUTTER, 2027))
pruefe('World COPD Day 2026 is 18.11.', datum_fuer(COPD, 2026) == date(2026, 11, 18),
       datum_fuer(COPD, 2026))
pruefe('it is a Sunday every year, 2020 to 2040',
       all(datum_fuer(MUTTER, j).weekday() == 6 for j in range(2020, 2041)))
pruefe('and really the SECOND one, not the first',
       all(8 <= datum_fuer(MUTTER, j).day <= 14 for j in range(2020, 2041)))
pruefe('the last Monday of February 2026 is 23.02.',
       nter_wochentag(2026, 2, 0, -1) == date(2026, 2, 23), nter_wochentag(2026, 2, 0, -1))

print('\n=== Rules that cannot work ===')
# One bad row in a hand-maintained list must not take the whole year down.
pruefe('31 February gives no date instead of an exception',
       datum_fuer({'rule_type': 'fixed', 'month_no': 2, 'day_no': 31}, 2026) is None)
pruefe('29 February gives no date in a normal year',
       datum_fuer({'rule_type': 'fixed', 'month_no': 2, 'day_no': 29}, 2026) is None)
pruefe('but does in a leap year',
       datum_fuer({'rule_type': 'fixed', 'month_no': 2, 'day_no': 29}, 2028) == date(2028, 2, 29))
pruefe('a fifth Monday the month does not have gives no date',
       datum_fuer({'rule_type': 'nth', 'month_no': 2, 'weekday_no': 0, 'nth_no': 5}, 2026) is None,
       datum_fuer({'rule_type': 'nth', 'month_no': 2, 'weekday_no': 0, 'nth_no': 5}, 2026))
pruefe('a missing month gives no date', datum_fuer({'rule_type': 'fixed', 'day_no': 4}, 2026) is None)
pruefe('an unknown kind of rule gives no date', datum_fuer({'rule_type': 'birthday'}, 2026) is None)
pruefe('an empty rule gives no date', datum_fuer({}, 2026) is None)

print('\n=== The starter list, resolved for six years ===')
kaputt = []
for jahr in range(2026, 2032):
    for regel in STARTLISTE:
        if datum_fuer(regel, jahr) is None:
            kaputt.append('%s %d' % (regel['name'], jahr))
pruefe('every entry gives a date in every year', not kaputt, kaputt[:4])

unlesbar = [r['name'] for r in STARTLISTE if regel_text(r) == 'rule incomplete']
pruefe('and every entry can say its own rule in words', not unlesbar, unlesbar)

namen = [r['name'] for r in STARTLISTE]
pruefe('no entry is in the list twice', len(namen) == len(set(namen)))

# The two dates Ortrud named first. If these move, the feature has missed its point.
weihnachten = [r for r in STARTLISTE if r['name'] == 'Christmas Eve'][0]
neujahr = [r for r in STARTLISTE if r['name'] == "New Year's Day"][0]
pruefe('Christmas Eve is the 24th in 2026, 2027 and 2031',
       all(datum_fuer(weihnachten, j) == date(j, 12, 24) for j in (2026, 2027, 2031)))
pruefe("New Year's Day is 01.01. in all of them",
       all(datum_fuer(neujahr, j) == date(j, 1, 1) for j in (2026, 2027, 2031)))

print('\n=== The Advent Sundays ===')
# They hang off Christmas Eve, not off the month: in 2026 the fourth Advent is
# the third Sunday of December, in 2025 the fourth. So "n-th Sunday in
# December" would be right in some years and wrong in others - which is exactly
# the kind of fault nobody notices until the post goes out on the wrong day.
ADVENT = {r['name']: r for r in STARTLISTE if 'Advent' in r['name']}
pruefe('all four are in the starter list', len(ADVENT) == 4, sorted(ADVENT))

BEKANNTE_ADVENTE = {
    2025: [(11, 30), (12, 7), (12, 14), (12, 21)],
    2026: [(11, 29), (12, 6), (12, 13), (12, 20)],
    2027: [(11, 28), (12, 5), (12, 12), (12, 19)],
    2023: [(12, 3), (12, 10), (12, 17), (12, 24)],   # Christmas Eve itself
}
for jahr in sorted(BEKANNTE_ADVENTE):
    for nr, (monat, tag) in enumerate(BEKANNTE_ADVENTE[jahr], start=1):
        name = '%d%s Advent' % (nr, {1: 'st', 2: 'nd', 3: 'rd'}.get(nr, 'th'))
        pruefe('%s %d is %02d.%02d.' % (name, jahr, tag, monat),
               datum_fuer(ADVENT[name], jahr) == date(jahr, monat, tag),
               datum_fuer(ADVENT[name], jahr))

pruefe('every Advent is a Sunday, 2020 to 2040',
       all(datum_fuer(r, j).weekday() == 6
           for r in ADVENT.values() for j in range(2020, 2041)))
pruefe('and they come exactly a week apart, in order',
       all(datum_fuer(ADVENT['2nd Advent'], j) - datum_fuer(ADVENT['1st Advent'], j)
           == timedelta(days=7)
           and datum_fuer(ADVENT['4th Advent'], j) - datum_fuer(ADVENT['3rd Advent'], j)
           == timedelta(days=7)
           for j in range(2020, 2041)))
pruefe('the fourth never falls after Christmas Eve',
       all(datum_fuer(ADVENT['4th Advent'], j) <= date(j, 12, 24)
           for j in range(2020, 2041)))
pruefe('but never more than six days before it either',
       all(date(j, 12, 24) - datum_fuer(ADVENT['4th Advent'], j) <= timedelta(days=6)
           for j in range(2020, 2041)))
pruefe('and the first is in November or early December',
       all(datum_fuer(ADVENT['1st Advent'], j).month == 11
           or datum_fuer(ADVENT['1st Advent'], j).day <= 3
           for j in range(2020, 2041)))
pruefe('the rule says so in words',
       'on or before 24 December' in regel_text(ADVENT['4th Advent']),
       regel_text(ADVENT['4th Advent']))

print('\n=== Which day a post is put on ===')
# The plan and the send date are not always the same day, and when they differ
# the send date is the one that happens. Post #53 is the live example: planned
# for 12 May, sitting in Buffer for 21 September. On the plan date the row
# would carry a September time, and September would look free.
# 1. The day it went out. Publishing clears post_scheduled_at, so without this
#    a published post falls back to its plan - and one that never had a plan
#    disappears from the calendar altogether. That is what was missing.
pruefe('the day it went out beats everything',
       kalendertag_fuer({'send_time': '21.09.2026 08:00',
                         'planned_date': date(2026, 5, 12)},
                        date(2026, 9, 14)) == date(2026, 9, 14),
       kalendertag_fuer({'send_time': '21.09.2026 08:00',
                         'planned_date': date(2026, 5, 12)}, date(2026, 9, 14)))
pruefe('a post with nothing but a send date still gets a day',
       kalendertag_fuer({'send_time': '', 'planned_date': None},
                        date(2026, 9, 14)) == date(2026, 9, 14))

pruefe('a send date beats the plan',
       kalendertag_fuer({'send_time': '21.09.2026 08:00',
                         'planned_date': date(2026, 5, 12)}) == date(2026, 9, 21),
       kalendertag_fuer({'send_time': '21.09.2026 08:00', 'planned_date': date(2026, 5, 12)}))
pruefe('without one, the plan is used',
       kalendertag_fuer({'send_time': '', 'planned_date': date(2026, 10, 1)}) == date(2026, 10, 1))
pruefe('a date without a time still counts',
       kalendertag_fuer({'send_time': '01.10.2026', 'planned_date': None}) == date(2026, 10, 1))
pruefe('a post with neither has no day at all',
       kalendertag_fuer({'send_time': '', 'planned_date': None}) is None)
pruefe('an unreadable stamp falls back to the plan instead of crashing',
       kalendertag_fuer({'send_time': 'tomorrow?', 'planned_date': date(2026, 3, 3)})
       == date(2026, 3, 3))
pruefe('and a nonsense date does too',
       kalendertag_fuer({'send_time': '31.02.2026 08:00', 'planned_date': date(2026, 3, 3)})
       == date(2026, 3, 3))
pruefe('the day is read, not the month',
       tag_aus('05.11.2026 09:00') == date(2026, 11, 5),
       tag_aus('05.11.2026 09:00'))

print("\n=== Reading Buffer's rows ===")
ZEILEN = [
    (12, '2026-01-12T08:00:00.000Z', '2026-01-12T08:00:04.000Z'),   # went out
    (49, '2026-09-01T08:00:00.000Z', ''),                            # still queued
    (53, '2026-09-21T08:00:00.000Z', None),                          # still queued
    (None, '2026-03-03T08:00:00.000Z', '2026-03-03T08:00:01.000Z'),  # no post id
]
GESENDET = gesendet_am_aus(ZEILEN)
pruefe('a post that went out gets the day it went out',
       GESENDET.get(12) == date(2026, 1, 12), GESENDET.get(12))
pruefe('one that is only queued gets no send day - it has not happened',
       49 not in GESENDET and 53 not in GESENDET, sorted(GESENDET))
pruefe('a row without a post is skipped instead of crashing', None not in GESENDET)
pruefe('an empty answer gives an empty result', gesendet_am_aus([]) == {})
# The due date must never be mistaken for the send date - that mix-up archived
# post #53 days before it goes out, twice.
pruefe('the DUE date is not taken as the send date',
       date(2026, 9, 1) not in GESENDET.values(), sorted(GESENDET.values()))

print("\n=== Buffer's own stamps ===")
# Buffer answers with ISO, the planner formats German. Reading one with the
# other's rules silently turns 09.11. into 11.09. - a post two months off, and
# nothing anywhere says so.
pruefe('an ISO stamp is read year-month-day',
       tag_aus_iso('2026-09-14T08:00:03.000Z') == date(2026, 9, 14),
       tag_aus_iso('2026-09-14T08:00:03.000Z'))
pruefe('a date on its own works too', tag_aus_iso('2026-11-05') == date(2026, 11, 5))
pruefe('an empty stamp gives nothing', tag_aus_iso('') is None)
pruefe('and so does a German one - they must not be mixed up',
       tag_aus_iso('14.09.2026 08:00') is None,
       tag_aus_iso('14.09.2026 08:00'))
pruefe('the German reader returns nothing for an ISO stamp, the other way round',
       tag_aus('2026-09-14T08:00:03.000Z') is None,
       tag_aus('2026-09-14T08:00:03.000Z'))
pruefe('rubbish gives nothing instead of an exception', tag_aus_iso('soon') is None)

print('\n=== How binding a day is ===')
# The colour on the page comes from this. "Scheduled" has to mean Buffer really
# has the post - not that the status field happens to say so.
def post(**kw):
    grund = {'linkedin_posted': 0, 'status': 'Draft', 'verbindlich': False}
    grund.update(kw)
    return grund

termin = [{'name': 'World Cancer Day'}]
pruefe('an occasion with no post is open', zustand(termin, []) == 'open')
pruefe('a day with neither is nothing at all', zustand([], []) == 'none')
pruefe('a post that Buffer holds is scheduled',
       zustand(termin, [post(status='Scheduled', verbindlich=True)]) == 'sched')
pruefe('a post that only SAYS Scheduled is merely planned',
       zustand([], [post(status='Scheduled')]) == 'plan',
       zustand([], [post(status='Scheduled')]))
pruefe('a published post is done', zustand([], [post(status='Posted')]) == 'done')
pruefe('linkedin_posted counts as published too',
       zustand([], [post(linkedin_posted=1)]) == 'done')
pruefe('one post still waiting keeps the day from being done',
       zustand([], [post(status='Posted'), post(status='Draft')]) != 'done')
pruefe('and a binding post wins over a loose one on the same day',
       zustand([], [post(status='Draft'), post(verbindlich=True)]) == 'sched')

# ---------------------------------------------------------------- the page

import ast
import re

with open(os.path.join(WURZEL, 'planner', 'templates', 'planner',
                       'kalender.html'), encoding='utf-8') as fh:
    VORLAGE = fh.read()

print('\n=== The page and the code still fit together ===')

# A template says nothing when it is wrong. A renamed key prints an empty
# string, a stray tag prints itself, and both look like "nothing happened".
# So the page is read here and held against the code that fills it.

# 1. Which keys does the view actually produce? Read them out of the module
#    rather than listing them here, so this cannot drift.
# Some of the fields are put there by _attach_send_time() over in views.py,
# which is the whole point of reusing it - so that file counts as a source of
# keys too. Reading both is what keeps this check honest instead of merely
# green.
with open(os.path.join(WURZEL, 'planner', 'views.py'), encoding='utf-8') as fh:
    SRC_VIEWS = fh.read()

BAUM = ast.parse(SRC + chr(10) + SRC_VIEWS)
SCHLUESSEL = set()
for knoten in ast.walk(BAUM):
    if isinstance(knoten, ast.Dict):
        for k in knoten.keys:
            if isinstance(k, ast.Constant) and isinstance(k.value, str):
                SCHLUESSEL.add(k.value)
    # p['x'] = ... on the left-hand side
    if isinstance(knoten, ast.Assign):
        for ziel in knoten.targets:
            if (isinstance(ziel, ast.Subscript)
                    and isinstance(ziel.slice, ast.Constant)
                    and isinstance(ziel.slice.value, str)):
                SCHLUESSEL.add(ziel.slice.value)
# dict(regel, datum=..., regel_text=...) - keyword form
for knoten in ast.walk(BAUM):
    if isinstance(knoten, ast.Call):
        for kw in knoten.keywords:
            if kw.arg:
                SCHLUESSEL.add(kw.arg)

# 2. Everything the page reads off a post, a day or a month.
LOOPS = {'p', 't', 'm'}
benutzt = set()
for stueck in re.findall(r'\{\{(.*?)\}\}|\{%(.*?)%\}', VORLAGE, re.S):
    text = (stueck[0] or stueck[1])
    for schleife, feld in re.findall(r'\b([ptm])\.([a-z_]+)', text):
        benutzt.add((schleife, feld))

fehlend = sorted('%s.%s' % x for x in benutzt if x[1] not in SCHLUESSEL)
pruefe('every field the page reads is one the view fills', not fehlend, fehlend)
pruefe('and the page really does read some', len(benutzt) > 12, len(benutzt))

# 2b. The same for the plain variables. {{ mnat }} instead of {{ monat }}
#     prints nothing at all, and the month picker would simply open on the
#     wrong month for ever. The allowed names are the ones the view hands to
#     render(), plus whatever the page's own {% for %} loops bind.
AUFRUF = [k for k in ast.walk(ast.parse(SRC))
          if isinstance(k, ast.Call) and getattr(k.func, 'id', '') == 'render']
KONTEXT = set()
for k in AUFRUF:
    for arg in k.args:
        if isinstance(arg, ast.Dict):
            KONTEXT |= {n.value for n in arg.keys
                        if isinstance(n, ast.Constant) and isinstance(n.value, str)}
SCHLEIFEN = set(re.findall(r'\{%\s*for\s+([a-z_]+)\s+in\b', VORLAGE))
# base.html and Django put these there; they are not this view's to provide.
VON_AUSSEN = {'forloop', 'user', 'request', 'csrf_token', 'block', 'True', 'False', 'None'}
ERLAUBT = KONTEXT | SCHLEIFEN | VON_AUSSEN

pruefe('the view really hands over a context', len(KONTEXT) > 5, sorted(KONTEXT))
namen = set()
for stueck in re.findall(r'\{\{(.*?)\}\}', VORLAGE, re.S):
    kopf = stueck.strip().split('|')[0].split('.')[0].strip()
    if re.match(r'^[a-z_][a-z_0-9]*$', kopf):
        namen.add(kopf)
unbekannte = sorted(namen - ERLAUBT)
pruefe('every variable the page prints is one it was given', not unbekannte, unbekannte)

# 3. The bug from this morning: {# ... #} comments out ONE line. A note that
#    runs over two is printed into the page, and on the post list it read like
#    the post's own title. Cheap to check, expensive to miss.
mehrzeilig = [k for k in re.findall(r'\{#.*?#\}', VORLAGE, re.S) if '\n' in k]
pruefe('no template comment runs over more than one line', not mehrzeilig,
       (mehrzeilig[0][:60] + '...') if mehrzeilig else '')

# 4. Block tags in balance. An {% endif %} too few swallows the rest of the
#    page without a word.
for auf, zu in (('if', 'endif'), ('for', 'endfor'), ('block', 'endblock')):
    offen = len(re.findall(r'\{%\s*' + auf + r'[\s%]', VORLAGE))
    geschlossen = len(re.findall(r'\{%\s*' + zu + r'\s*%\}', VORLAGE))
    pruefe('%s and %s are in balance' % (auf, zu), offen == geschlossen,
           '%d vs %d' % (offen, geschlossen))

# 5. The page talks to the API by name. A typo here is silent: the request
#    goes out, comes back with an error nobody shows, and the button does
#    nothing. This is the same trap the studio config had with its url keys.
AKTIONEN = set(re.findall(r"aktion == '([a-z_]+)'", SRC))
AKTIONEN |= set(re.findall(r"aktion in \('([a-z_]+)', '([a-z_]+)'\)", SRC)[0]
                if re.findall(r"aktion in \('([a-z_]+)', '([a-z_]+)'\)", SRC) else [])
gerufen = set(re.findall(r"action: '([a-z_]+)'", VORLAGE))
gerufen |= set(re.findall(r"\? '([a-z_]+)' : '([a-z_]+)'", VORLAGE)[0]
               if re.findall(r"\? '([a-z_]+)' : '([a-z_]+)'", VORLAGE) else [])
unbekannt = sorted(gerufen - AKTIONEN)
pruefe('every action the page sends is one the API answers', not unbekannt,
       unbekannt)
pruefe('and it sends more than one', len(gerufen) >= 4, sorted(gerufen))

# 6. The address the page posts to has to be the one urls.py routes.
with open(os.path.join(WURZEL, 'planner', 'urls.py'), encoding='utf-8') as fh:
    URLS = fh.read()
for pfad in sorted(set(re.findall(r"fetch\('(/planner/[a-z/]+)", VORLAGE))):
    kurz = pfad.replace('/planner/', '').strip('/')
    pruefe('%s is routed' % pfad, ("'%s/'" % kurz) in URLS, kurz)

# The table check must not run on every request. views.py carries a long
# comment about what that cost there - 17 ALTER attempts per page load, each
# answered with a swallowed error - and this file would have repeated it in a
# milder form.
ANLEGEN = herausschneiden('_tabellen_anlegen')
pruefe('the table check runs once per process, not once per request',
       'if _tabellen_geprueft:' in ANLEGEN and 'return' in ANLEGEN)
pruefe('and the flag is actually set somewhere in it',
       '_tabellen_geprueft = True' in ANLEGEN)

print('\n=== The two halves stay apart ===')
# is_oj splits the planner in two, and every other page honours that split.
# A calendar that showed both, or an OJ page that linked back into the other
# half, would quietly undo it - and nobody would notice until the wrong post
# turned up in the wrong place.
for name in ('_posts_des_jahres', 'posts_ohne_datum'):
    stueck = herausschneiden(name)
    pruefe('%s can be asked for either half' % name, 'nur_oj' in stueck.split(chr(10))[0])
    pruefe('%s really filters on it' % name,
           'COALESCE(p.is_oj, 0) = %s' in stueck and '1 if nur_oj else 0' in stueck)

ANSICHT = herausschneiden('kalender_view')
pruefe('the view takes the half as well', 'nur_oj=False' in ANSICHT.split(chr(10))[0])
for aufruf in ('jahres_tage(jahr, nur_oj)', 'posts_ohne_datum(nur_oj=nur_oj)'):
    pruefe('and passes it to %s' % aufruf.split('(')[0], aufruf in ANSICHT)

# Every link the OJ page builds must stay on the OJ page. One hardcoded path
# is enough to drop the user back into the other half without a word.
#
# The switch between the two is the single exception - naming both addresses
# is the whole of its job - so it is cut out before looking, rather than the
# check being loosened for everyone.
OHNE_SCHALTER = re.sub(r'<span class="kal-seite">.*?</span>', '', VORLAGE, flags=re.S)
pruefe('the switch really was cut out before checking',
       len(OHNE_SCHALTER) < len(VORLAGE))
HART = re.findall(r'(?:href|location\.href)\s*=\s*[\'"][^\'"]*?/planner/kalender/(?!api/)',
                  OHNE_SCHALTER)
pruefe('no link hardcodes the calendar address', not HART, HART[:3])
pruefe('the links are built from the one address instead',
       '{{ basis }}' in VORLAGE and 'BASIS +' in VORLAGE)
pruefe('and the page says which half it is showing', '{% if nur_oj %}' in VORLAGE)

print('\n=== No list page shows OJ posts by accident ===')
# The split is only worth anything if every page honours it. A new list view
# that forgets the filter puts OJ posts back among the others, and nothing
# says so - the posts simply appear. So the whole file is swept, and the two
# queries that are deliberately different are named here rather than skipped
# by a rule that would also let a new mistake through.
AUSNAHMEN = {
    # takes ids that a filtered query already produced
    'COALESCE(video_nc_path': 'video paths for posts already fetched',
    # what gets published automatically is a decision, not a display question
    "status = 'Scheduled'": 'the automatic send - Ortrud has not ruled on it',
}
ungefiltert = []
for knoten in ast.walk(ast.parse(SRC_VIEWS)):
    if not (isinstance(knoten, ast.Constant) and isinstance(knoten.value, str)):
        continue
    text = knoten.value
    if 'planner_posts' not in text or not re.search(r'\bSELECT\b', text, re.I):
        continue
    if 'is_oj' in text or re.search(r'WHERE\s+id\s*=\s*%s', text, re.I):
        continue
    if any(marke in text for marke in AUSNAHMEN):
        continue
    ungefiltert.append('line %s: %s' % (knoten.lineno, ' '.join(text.split())[:60]))

pruefe('every list query on planner_posts honours is_oj', not ungefiltert, ungefiltert[:2])
pruefe('and the two known exceptions are still the only ones',
       all(any(m in k.value for m in AUSNAHMEN)
           for k in ast.walk(ast.parse(SRC_VIEWS))
           if isinstance(k, ast.Constant) and isinstance(k.value, str)
           and 'planner_posts' in k.value and re.search(r'\bSELECT\b', k.value, re.I)
           and 'is_oj' not in k.value
           and not re.search(r'WHERE\s+id\s*=\s*%s', k.value, re.I)))

print('\n=== Posts with no date are told apart ===')
# Thirty drafts and three lost records in one list means the three are never
# seen. A draft without a date is an idea; a published post without one is a
# day that is not on record anywhere.
pruefe('a published post is the one to look at',
       ohne_datum_gruppe({'status': 'Posted', 'linkedin_posted': 0}) == 'raus')
pruefe('and so is one LinkedIn confirmed, whatever the status says',
       ohne_datum_gruppe({'status': 'Draft', 'linkedin_posted': 1}) == 'raus')
pruefe('a draft is not', ohne_datum_gruppe({'status': 'Draft', 'linkedin_posted': 0}) == 'offen')
pruefe('nor is one still in review',
       ohne_datum_gruppe({'status': 'Review', 'linkedin_posted': 0}) == 'offen')
# Archive without linkedin_posted is the planner's "Discarded" - it never went
# out, so there is no day to have lost.
pruefe('a discarded post is not a lost record',
       ohne_datum_gruppe({'status': 'Archive', 'linkedin_posted': 0}) == 'offen')
pruefe('an empty post does not crash the grouping',
       ohne_datum_gruppe({}) == 'offen')

ANSICHT3 = herausschneiden('kalender_view')
pruefe('the view hands the page both groups',
       "'ohne_datum_raus'" in ANSICHT3 and "'ohne_datum_offen'" in ANSICHT3)
pruefe('and reads the list only once',
       ANSICHT3.count('posts_ohne_datum(') == 1)
pruefe('the page shows the lost records openly',
       '{% if ohne_datum_raus %}' in VORLAGE and 'went out without a date on record' in VORLAGE)
pruefe('and folds the drafts away behind a summary',
       '{% if ohne_datum_offen %}' in VORLAGE and '<details>' in VORLAGE)

print('\n=== The OJ calendar is a plain one ===')
# Ortrud asked for a simple calendar on the OJ side: days and posts, no world
# days and no holidays. Those belong to the planner's editorial year.
TAGE = herausschneiden('jahres_tage')
pruefe('no occasions are gathered for the OJ side',
       '[] if nur_oj else jahres_termine(jahr)' in TAGE, )
ANSICHT2 = herausschneiden('kalender_view')
pruefe('and none are handed to the page either',
       "'termine': [] if nur_oj else jahres_termine(jahr)," in ANSICHT2)
# The page must drop the column as well, or the OJ calendar keeps an empty one.
for stueck, was in (('{% if not nur_oj %}<span>Occasion</span>', 'the occasion column'),
                    ('{% if not nur_oj %}<button class="kal-knopf" id="kal-zur-liste"',
                     'the jump to the list'),
                    ('{% if not nur_oj %}\n  <!-- ================= the list you maintain',
                     'the list of recurring dates')):
    pruefe('the page leaves out %s on the OJ side' % was,
           stueck.replace('\n', chr(10)) in VORLAGE)
pruefe('and gives the OJ page a narrower grid', 'schlicht' in VORLAGE)
# The script is shared, so it has to cope with the elements that are gone.
# _tests/kalender_js_test.mjs runs it both ways; this only checks the guards
# are still written, for the day nobody has node to hand.
pruefe('the script guards the list wiring it may not find',
       'if (regelnKoerper) {' in VORLAGE and 'if (zurListe) {' in VORLAGE)

print('\n=== The OJ area is shut, not merely hidden ===')
# Leaving the link out of the navigation was never access control - the
# address stayed open to anyone logged in who typed it.
ANSICHT = herausschneiden('kalender_view')
pruefe('the OJ calendar turns non-admins away',
       'nur_oj and not request.user.is_superuser' in ANSICHT
       and 'raise Http404' in ANSICHT)
pruefe('and the planner calendar is NOT shut with it',
       ANSICHT.count('raise Http404') == 1 and 'nur_oj and' in ANSICHT)
pruefe('Http404 is imported, so the refusal is not itself an error',
       'from django.http import Http404' in SRC)

pruefe("the planner's own OJ page is shut the same way",
       '@nur_fuer_admin' in SRC_VIEWS and 'def oj_view' in SRC_VIEWS)
WAECHTER = SRC_VIEWS[SRC_VIEWS.index('def nur_fuer_admin'):][:600]
pruefe('the guard checks is_superuser and raises 404',
       'is_superuser' in WAECHTER and 'raise Http404' in WAECHTER)
pruefe('and it keeps the view it wraps recognisable',
       'functools.wraps' in WAECHTER)
# The switch must not offer a door that is locked.
pruefe('the page offers the OJ switch to admins only',
       '{% if user.is_superuser %}' in VORLAGE)

print('\n%d ok, %d failed' % (gut, schlecht))
sys.exit(1 if schlecht else 0)
