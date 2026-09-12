"""Test for moving between the Planner and the status tabs.

Two things went wrong before September 2026:

  * Creating a post from the Draft tab took you into the Planner and left you
    standing there. The link simply said "/planner/?new=1" - it carried no
    memory of where it had come from.
  * Clicking a post in the Planner opened the dialog in the Planner. But the
    work on a post happens in the tab that belongs to its status.

Both are now settled through the URL, and this test watches the two pieces
that decide it: the status-to-tab map in planner.html and the way back in
_post_list.html.

    python _tests/navigation_test.py
"""
import os
import re
import sys

HIER = os.path.dirname(os.path.abspath(__file__))


def suche(*teile):
    kandidaten = [os.path.join(HIER, '..', *teile), os.path.join(HIER, teile[-1])]
    p = next((k for k in kandidaten if os.path.exists(k)), None)
    if not p:
        print('Not found: ' + os.path.join(*teile))
        for k in kandidaten:
            print('  looked in ' + os.path.abspath(k))
        sys.exit(2)
    return open(p, encoding='utf-8').read()


planner = suche('planner', 'templates', 'planner', 'planner.html')
liste = suche('planner', 'templates', 'planner', '_post_list.html')
views = suche('planner', 'views.py')
urls = suche('planner', 'urls.py')

gut = schlecht = 0


def pruefe(name, bedingung, zusatz=''):
    global gut, schlecht
    if bedingung:
        gut += 1
        print('  ok   ' + name)
    else:
        schlecht += 1
        print('  FEHL ' + name + ('  -> ' + str(zusatz) if zusatz else ''))


# ── The map itself ──────────────────────────────────────────────────────────
treffer = re.search(r'const STATUS_REITER = \{(.*?)\};', planner, re.S)
if not treffer:
    print('STATUS_REITER not found in planner.html - the navigation was rebuilt.')
    sys.exit(2)
karte = dict(re.findall(r"'([^']+)':\s*'([^']+)'", treffer.group(1)))

print('\n=== Every status leads to its own tab ===')
ERWARTET = {
    'Draft': '/planner/draft/',
    'Review': '/planner/pipeline/',
    'Ready': '/planner/ready/',
    'Scheduled': '/planner/scheduled/',
    'Posted': '/planner/archive/',
    'Archive': '/planner/archive/',
}
for status, ziel in ERWARTET.items():
    pruefe('%-10s -> %s' % (status, ziel), karte.get(status) == ziel, karte.get(status))

print('\n=== Planned deliberately has no tab ===')
# The slot is booked and nothing is written yet - that belongs in the Planner,
# and the code has to fall back to the dialog there.
pruefe("'Planned' is not in the map", 'Planned' not in karte, karte.get('Planned'))
pruefe('a status without a tab opens the dialog in place',
       re.search(r'if \(!ziel\)\s*\{\s*openEditModal\(', planner) is not None)

print('\n=== The targets really exist ===')
# A tab in the map that has no route would send the user to a 404.
for status, ziel in karte.items():
    pfad = ziel.replace('/planner/', '').strip('/')
    pruefe('%-10s route %-12s is registered' % (status, pfad + '/'),
           ("path('%s/'" % pfad) in urls, ziel)

print('\n=== And the tabs really show that status ===')
# The map is only worth anything if the target page does not filter the post
# away again. Checked against the WHERE clauses in the views.
FILTER = [
    ('draft_view', "p.status = 'Draft'"),
    ('pipeline_view', "p.status = 'Review'"),
    ('ready_view', "p.status = 'Ready'"),
    ('scheduled_view', "p.status = 'Scheduled'"),
    ('archive_view', "p.status IN ('Posted', 'Archive')"),
]
for name, bedingung in FILTER:
    stelle = views.find('def %s(' % name)
    ende = views.find('\ndef ', stelle + 1)
    koerper = views[stelle:ende if ende > 0 else len(views)]
    pruefe('%-16s filters on %s' % (name, bedingung), bedingung in koerper)

print('\n=== The way there: the click passes the id along ===')
pruefe('the title cell calls oeffnePostImReiter',
       planner.count('onclick="oeffnePostImReiter(') == 2,
       planner.count('onclick="oeffnePostImReiter('))
pruefe('the pencil stays the quick editor in place',
       planner.count('onclick="openEditModal(') >= 2,
       planner.count('onclick="openEditModal('))
pruefe('the id travels as ?edit=',
       "'?edit=' + encodeURIComponent(id)" in planner)

print('\n=== The way back: the tab opens the post ===')
pruefe('_post_list.html reads ?edit=', "params.get('edit')" in liste)
pruefe('and opens that post', re.search(r'openEdit\(p\.id\)', liste) is not None)
pruefe('every card is addressable', 'id="post-{{ p.id }}"' in liste)
pruefe('the post one arrives at is highlighted', "classList.add('pe-ziel')" in liste)

print('\n=== If the post is not on that page ===')
# Ready and Scheduled additionally require in_pipeline; a published post moves
# to the archive overnight. Then the user must not be left in front of a list
# that silently lacks their post.
pruefe('it falls back to All Posts', "/planner/all/?edit=" in liste)
pruefe('and the fallback cannot loop', "von=all" in liste and "params.get('von')" in liste)

print('\n=== Creating a post finds its way back ===')
pruefe('the new-post link carries where it came from',
       'back={{ request.path|urlencode }}' in liste)
pruefe('and the status that fits the tab',
       all(('status=' + s) in liste for s in ('Draft', 'Review', 'Ready', 'Scheduled', 'Archive')))
pruefe('the Planner reads back=', "params.get('back')" in planner)
pruefe('and goes there after saving',
       'window.location.href = window.OV_RETURN' in planner)
pruefe('no hard-coded /planner/ left as the way back',
       "window.OV_RETURN) { window.location.href = '/planner/'; }" not in planner)

print('\n=== Only our own addresses count as a way back ===')
# Otherwise ?back=https://example.com/ would be an open redirect.
pruefe('back= is checked against a pattern',
       re.search(r"test\(zurueck\)", planner) is not None)
# Read the JavaScript literal /…/flags and turn it into a Python pattern.
muster = re.search(r"if \(/(?P<kern>.+?)/(?P<flaggen>[a-z]*)\.test\(zurueck\)\)", planner)
if muster:
    regex = re.compile(muster.group('kern'),
                       re.I if 'i' in muster.group('flaggen') else 0)
    pruefe('an own path is accepted', bool(regex.match('/planner/draft/')))
    for boese in ('https://example.com/', '//example.com/', 'javascript:alert(1)'):
        pruefe('rejected: %-24s' % boese, not regex.match(boese))
else:
    pruefe('the pattern could be read', False, 'not found')

print('\n%d ok, %d failed' % (gut, schlecht))
sys.exit(1 if schlecht else 0)
