"""Clear out the recurring dates you unticked, and add the Advent Sundays.

Two jobs, both one-off:

  1. Everything you took out of the list in the calendar page ("In the list"
     unticked, active=0) is deleted for good, together with any per-year
     exceptions it had. Unticking is reversible on purpose; this is the step
     that makes it final, and it only ever touches rows that are already
     unticked.

  2. The four Advent Sundays are added. They were not in the list when the
     table was first filled, and the starter list is only ever written once -
     so an existing database does not get them on its own.

Safe to run twice: the Advent entries are matched by name and not added again.

    python kalender_pflege.py            # show what would happen
    python kalender_pflege.py --go       # do it
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dashboard.settings')

import django                                    # noqa: E402

django.setup()

from django.db import connection                 # noqa: E402

from planner.kalender import (                   # noqa: E402
    _tabellen_anlegen, datum_fuer, regel_text)

# name, kind, rule_type, month_no, day_no, weekday_no, nth_no, easter_offset,
# lead_days, series - the same shape the table takes, weekday 6 = Sunday.
ADVENT = [
    ('1st Advent', 'own', 'before', 12, 24, 6, 3, None, 21, ''),
    ('2nd Advent', 'own', 'before', 12, 24, 6, 2, None, 14, ''),
    ('3rd Advent', 'own', 'before', 12, 24, 6, 1, None, 14, ''),
    ('4th Advent', 'own', 'before', 12, 24, 6, 0, None, 14, ''),
]

ERNST = '--go' in sys.argv

_tabellen_anlegen()

with connection.cursor() as c:
    c.execute("""SELECT id, name, active FROM planner_recurring_dates ORDER BY id""")
    alle = c.fetchall()

drin = [r for r in alle if r[2]]
raus = [r for r in alle if not r[2]]

print('\n=== The list as it stands ===')
print('  %d in the calendar, %d unticked' % (len(drin), len(raus)))

print('\n=== Unticked, so to be deleted ===')
if not raus:
    print('  nothing is unticked - nothing to delete.')
else:
    for kennung, name, _ in raus:
        print('  #%-4s %s' % (kennung, name))

print('\n=== Advent Sundays ===')
vorhanden = {r[1] for r in alle}
fehlen = [a for a in ADVENT if a[0] not in vorhanden]
if not fehlen:
    print('  all four are already in the list.')
else:
    for eintrag in fehlen:
        regel = dict(zip(['name', 'kind', 'rule_type', 'month_no', 'day_no',
                          'weekday_no', 'nth_no', 'easter_offset', 'lead_days',
                          'series'], eintrag))
        print('  + %-12s %s' % (regel['name'], regel_text(regel)))

if not ERNST:
    print('\nNothing was changed. Run it with --go to carry that out.')
    sys.exit(0)

with connection.cursor() as c:
    for kennung, name, _ in raus:
        c.execute('DELETE FROM planner_date_exceptions WHERE recurring_id=%s', [kennung])
        c.execute('DELETE FROM planner_recurring_dates WHERE id=%s', [kennung])
    if fehlen:
        c.executemany("""INSERT INTO planner_recurring_dates
                         (name, kind, rule_type, month_no, day_no, weekday_no,
                          nth_no, easter_offset, lead_days, series)
                         VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", fehlen)

print('\n%d deleted, %d added.' % (len(raus), len(fehlen)))

# Read the Advent dates back out of the database, rather than trusting what was
# just written: a wrong weekday or a wrong week count would otherwise only show
# up on the page in December.
print('\n=== What the Advent Sundays now come out as ===')
with connection.cursor() as c:
    c.execute("""SELECT name, kind, rule_type, month_no, day_no, weekday_no,
                        nth_no, easter_offset
                 FROM planner_recurring_dates WHERE name LIKE '%%Advent'
                 ORDER BY nth_no DESC""")
    for zeile in c.fetchall():
        regel = dict(zip(['name', 'kind', 'rule_type', 'month_no', 'day_no',
                          'weekday_no', 'nth_no', 'easter_offset'], zeile))
        termine = []
        for jahr in (2026, 2027):
            tag = datum_fuer(regel, jahr)
            termine.append(tag.strftime('%d.%m.%Y (%a)') if tag else 'no date')
        print('  %-12s %s   %s' % (regel['name'], termine[0], termine[1]))

print('\nOpen /planner/kalender/ - they are in December, and the first one in November.')
