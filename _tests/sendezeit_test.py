"""Does every post say when it goes out?

On a page called "Scheduled" the send time is the one thing that has to be
readable, and it was the one thing missing. Three places know something about
it and they are not equally good, so the order matters:

  1. what we told Buffer (post_scheduled_at) - the truth, when it is there
  2. what Buffer will do (due_at) - survives our own mistakes, which is why it
     is the repair when a wrong archiving cleared the field above
  3. the editorial plan (planned_date/planned_time) - may be stale, but better
     than an empty row

This cuts the real function out of planner/views.py and answers its database
call with a fixed reply. No database, no Django needed for the decision itself.

    python _tests/sendezeit_test.py
"""
import os
import sys
from datetime import date, time

HIER = os.path.dirname(os.path.abspath(__file__))
WURZEL = os.path.dirname(HIER)

with open(os.path.join(WURZEL, 'planner', 'views.py'), encoding='utf-8') as fh:
    SRC = fh.read()
with open(os.path.join(WURZEL, 'planner', 'templates', 'planner',
                       '_post_list.html'), encoding='utf-8') as fh:
    VORLAGE = fh.read()


def herausschneiden(name):
    marke = '\ndef %s(' % name
    if marke not in SRC:
        raise SystemExit('not found: ' + name)
    zeilen = SRC[SRC.index(marke) + 1:].split('\n')
    raus = [zeilen[0]]
    for zeile in zeilen[1:]:
        if zeile and not zeile[0].isspace():
            break
        raus.append(zeile)
    return '\n'.join(raus)


class FakeCursor:
    def __init__(self, zeilen):
        self.zeilen = zeilen

    def execute(self, sql, params=None):
        pass

    def fetchall(self):
        return self.zeilen

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeConnection:
    def __init__(self, zeilen):
        self.zeilen = zeilen

    def cursor(self):
        return FakeCursor(self.zeilen)


def baue(buffer_zeilen):
    raum = {'connection': FakeConnection(buffer_zeilen), 'print': lambda *a, **k: None,
            '__builtins__': __builtins__}
    exec(compile(herausschneiden('_attach_send_time'),
                 'planner/views.py (cut out)', 'exec'), raum)
    return raum['_attach_send_time']


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


print('\n=== What we told Buffer wins ===')
fn = baue([(1, '2026-09-30T10:00:00.000Z')])
posts = [{'id': 1, 'post_scheduled_at_fmt': '21.09.2026 08:00',
          'planned_date': date(2026, 5, 12), 'planned_time': time(21, 8)}]
fn(posts)
pruefe('it is what shows', posts[0]['send_time'] == '21.09.2026 08:00', posts[0]['send_time'])
pruefe('and it says where it comes from',
       posts[0]['send_time_source'] == 'told to Buffer', posts[0]['send_time_source'])

print('\n=== Without it, Buffer is asked ===')
# This is post #53 after the wrong archiving: post_scheduled_at was cleared,
# but Buffer still knows.
fn = baue([(53, '2026-09-21T08:00:00.000Z')])
posts = [{'id': 53, 'post_scheduled_at_fmt': '',
          'planned_date': date(2026, 5, 12), 'planned_time': time(21, 8)}]
fn(posts)
pruefe('Buffer\'s time is used', posts[0]['send_time'] == '21.09.2026 08:00', posts[0]['send_time'])
pruefe('and named as such', posts[0]['send_time_source'] == 'from Buffer',
       posts[0]['send_time_source'])
pruefe('the editorial plan does NOT win over it',
       '12.05.2026' not in posts[0]['send_time'], posts[0]['send_time'])

print('\n=== Without Buffer either, the plan is better than nothing ===')
fn = baue([])
posts = [{'id': 7, 'post_scheduled_at_fmt': '',
          'planned_date': date(2026, 10, 1), 'planned_time': time(9, 30)}]
fn(posts)
pruefe('date and time are shown', posts[0]['send_time'] == '01.10.2026 09:30', posts[0]['send_time'])
pruefe('and marked as merely planned', posts[0]['send_time_source'] == 'planned',
       posts[0]['send_time_source'])

fn = baue([])
posts = [{'id': 8, 'post_scheduled_at_fmt': '', 'planned_date': date(2026, 10, 1),
          'planned_time': None}]
fn(posts)
pruefe('a date without a time still shows', posts[0]['send_time'] == '01.10.2026',
       posts[0]['send_time'])

print('\n=== When nothing is known ===')
fn = baue([])
posts = [{'id': 9, 'post_scheduled_at_fmt': '', 'planned_date': None, 'planned_time': None}]
fn(posts)
pruefe('the field is empty, not a crash or a fake date',
       posts[0]['send_time'] == '', posts[0]['send_time'])

print('\n=== Odd input ===')
fn = baue([(10, 'not-a-date')])
posts = [{'id': 10, 'post_scheduled_at_fmt': '', 'planned_date': None, 'planned_time': None}]
fn(posts)
pruefe('unreadable stamps do not bring the page down',
       isinstance(posts[0].get('send_time'), str), posts[0].get('send_time'))

fn = baue([])
pruefe('an empty page is fine', fn([]) == [])

print('\n=== And the row really shows it ===')
# Check the condition, not just the variable: wrapping it in {% if False %}
# leaves the variable in the file and a laxer check passes while the row shows
# nothing. It did.
pruefe('the row is guarded by the send time itself',
       '{% if p.send_time %}' in VORLAGE)
pruefe('and prints it', '{{ p.send_time }}' in VORLAGE)
# The two used to be an if/elif, so a published post hid its own send time.
stelle = VORLAGE[VORLAGE.index('p.send_time'):VORLAGE.index('p.send_time') + 600]
pruefe('and "in ✓" no longer replaces it',
       '{% elif' not in stelle.split('linkedin_posted')[0])

print('\n%d ok, %d failed' % (gut, schlecht))
sys.exit(1 if schlecht else 0)
