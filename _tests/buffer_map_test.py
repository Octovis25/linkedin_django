"""Does a post that is only queued still look queued after the sync?

Twice now Buffer's dueAt - the PLANNED time - was written into sent_at. A post
waiting in the queue then carried a timestamp, promote_scheduled_to_posted()
read any timestamp as proof of publication, and the post was archived days
before it went out. Fixed on 2026-09-14, lost again in 487ad48 on 2026-09-18,
found again on 2026-09-20 through post #53.

Which is why this test exists: the mistake is easy to make, invisible in normal
use, and only shows up when a post disappears from the planner.

It cuts the two mapping functions out of planner/views.py and answers their
GraphQL call with a fixed reply - no Buffer, no network, no database.

    python _tests/buffer_map_test.py
"""
import os
import sys

HIER = os.path.dirname(os.path.abspath(__file__))
WURZEL = os.path.dirname(HIER)

with open(os.path.join(WURZEL, 'planner', 'views.py'), encoding='utf-8') as fh:
    SRC = fh.read()
with open(os.path.join(WURZEL, 'posts_posted', 'views.py'), encoding='utf-8') as fh:
    SRC_POSTS = fh.read()


def herausschneiden(quelle, name):
    marke = '\ndef %s(' % name
    if marke not in quelle:
        raise SystemExit('not found: ' + name)
    zeilen = quelle[quelle.index(marke) + 1:].split('\n')
    raus = [zeilen[0]]
    for zeile in zeilen[1:]:
        if zeile and not zeile[0].isspace():
            break
        raus.append(zeile)
    return '\n'.join(raus)


# Two posts, the way Buffer really answers: one waiting, one gone out.
WARTET = {'id': 'b-wait', 'channelId': 'c1', 'status': 'scheduled',
          'dueAt': '2026-09-21T08:00:00.000Z', 'sentAt': None,
          'text': 'waiting in the queue', 'externalLink': None, 'assets': []}
GESENDET = {'id': 'b-sent', 'channelId': 'c1', 'status': 'sent',
            'dueAt': '2026-09-14T08:00:00.000Z', 'sentAt': '2026-09-14T08:00:03.000Z',
            'text': 'already out', 'externalLink': None, 'assets': [],
            'metricsUpdatedAt': None, 'metrics': []}


def antwort(_token, _query, _variables=None):
    return {'data': {'posts': {'pageInfo': {'hasNextPage': False, 'endCursor': None},
                               'edges': [{'node': WARTET}, {'node': GESENDET}]}}}


def baue(name):
    raum = {'_buffer_graphql': antwort, '__builtins__': __builtins__}
    exec(compile(herausschneiden(SRC, name), 'planner/views.py (cut out)', 'exec'), raum)
    return raum[name]


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


for funktion in ('_buffer_fetch_posts_basic', '_buffer_fetch_post_metrics'):
    print('\n=== %s ===' % funktion)
    try:
        posts = {p['buffer_post_id']: p for p in baue(funktion)('token', 'org')}
    except Exception as fehler:
        pruefe('runs at all', False, '%s: %s' % (type(fehler).__name__, fehler))
        continue

    wartet = posts.get('b-wait', {})
    gesendet = posts.get('b-sent', {})

    pruefe('a queued post has NO send date',
           wartet.get('sent_at') in (None, ''), wartet.get('sent_at'))
    pruefe('but keeps its planned time, in its own field',
           wartet.get('due_at') == '2026-09-21T08:00:00.000Z', wartet.get('due_at'))
    pruefe('a sent post has its real send date',
           gesendet.get('sent_at') == '2026-09-14T08:00:03.000Z', gesendet.get('sent_at'))
    pruefe('and that is NOT the planned time',
           gesendet.get('sent_at') != gesendet.get('due_at'),
           gesendet.get('sent_at'))

print('\n=== The GraphQL queries ask for both times ===')
# Without sentAt in the query the answer never carries one, and the mapping
# above would have nothing to read - which is how the metrics fetch got it
# wrong in the first place.
for funktion in ('_buffer_fetch_posts_basic', '_buffer_fetch_post_metrics'):
    quelle = herausschneiden(SRC, funktion)
    # Look for the field inside the QUERY, not anywhere in the function: the
    # mapping below it says node.get('sentAt') too, and a check that settles
    # for that passes while the query has stopped asking. It did, once.
    im_query = lambda feld: ('\n            %s\n' % feld) in quelle
    pruefe('%s asks the query for sentAt' % funktion, im_query('sentAt'))
    pruefe('%s asks the query for dueAt' % funktion, im_query('dueAt'))

print('\n=== And a date alone no longer counts as proof ===')
# The second line of defence: even if a planned time ever lands in sent_at
# again, a date in the future must not promote anything.
befoerderung = herausschneiden(SRC_POSTS, 'promote_scheduled_to_posted')
pruefe('the promotion compares the send date against now',
       'UTC_TIMESTAMP()' in befoerderung)
pruefe('and only accepts one that is not in the future',
       '<= UTC_TIMESTAMP()' in befoerderung.replace('\n', ' ').replace('  ', ' '))

print('\n%d ok, %d failed' % (gut, schlecht))
sys.exit(1 if schlecht else 0)
