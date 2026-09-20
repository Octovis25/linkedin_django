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
             'regel_text', '_zustand'):
    exec(compile(herausschneiden(name), 'planner/kalender.py (cut out)', 'exec'), RAUM)

ostern = RAUM['_ostern']
letzter_tag = RAUM['_letzter_tag']
nter_wochentag = RAUM['_nter_wochentag']
datum_fuer = RAUM['datum_fuer']
regel_text = RAUM['regel_text']
zustand = RAUM['_zustand']

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

print('\n%d ok, %d failed' % (gut, schlecht))
sys.exit(1 if schlecht else 0)
