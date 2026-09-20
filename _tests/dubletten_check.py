"""Which posts exist more than once?

#98 turned out to be a copy of #16. One copy is a nuisance; a habit of copies
is something else, and the two call for different answers - so this counts them
before anything is tidied up by hand.

Two posts are treated as the same when their titles match, or when the start of
their text matches. The normalisation is the one linkedin_statistics already
uses to pair posts with their metrics: whitespace out, lowercased, first N
characters. Borrowed on purpose - two different notions of "the same text" in
one code base is how contradictions start.

Nothing is changed. It reads and prints.

    python _tests/dubletten_check.py
"""
import os
import re
import sys

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HIER))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dashboard.settings')

import django                                   # noqa: E402

django.setup()

from django.db import connection                # noqa: E402

ZEICHEN = 60


def schluessel(text):
    t = re.sub(r'<[^>]+>', ' ', text or '')     # drafts can hold pasted HTML
    for weg in ('\n', '\r', '\t', ' ', ' '):
        t = t.replace(weg, '')
    return t[:ZEICHEN].lower()


with connection.cursor() as c:
    c.execute("""SELECT id, COALESCE(title,''), COALESCE(content,''),
                        COALESCE(status,''), linkedin_posted, planned_date
                 FROM planner_posts ORDER BY id""")
    alle = c.fetchall()

nach_titel = {}
nach_text = {}
for kennung, titel, inhalt, status, veroeffentlicht, geplant in alle:
    zeile = (kennung, titel, status, veroeffentlicht, geplant)
    if titel.strip():
        nach_titel.setdefault(schluessel(titel), []).append(zeile)
    if inhalt.strip():
        nach_text.setdefault(schluessel(inhalt), []).append(zeile)


def zeigen(titel, gruppen, wie):
    treffer = [g for g in gruppen.values() if len(g) > 1]
    print('\n=== %s ===' % titel)
    if not treffer:
        print('  none.')
        return 0
    treffer.sort(key=lambda g: -len(g))
    for gruppe in treffer:
        # Keep the one that went out; a published post is the record of what
        # actually happened and is never the copy to throw away.
        raus = [z for z in gruppe if z[3] or z[2] == 'Posted']
        print('\n  %s  (%d posts)' % ((gruppe[0][1] or '(no title)')[:60], len(gruppe)))
        for kennung, name, status, veroeffentlicht, geplant in gruppe:
            marke = 'KEEP - it went out' if (veroeffentlicht or status == 'Posted') else ''
            print('    #%-5s %-9s %-12s %s' % (
                kennung, status, geplant or 'no date', marke))
        if not raus:
            print('    (none of them ever went out - which one to keep is yours to say)')
    print('\n  %d group%s, %d posts in total.'
          % (len(treffer), '' if len(treffer) == 1 else 's',
             sum(len(g) for g in treffer)))
    return len(treffer)


print('\n%d posts in the database.' % len(alle))
a = zeigen('Same title', nach_titel, 'title')
b = zeigen('Same beginning of the text (first %d characters)' % ZEICHEN, nach_text, 'text')

print('\n=== What to do with one ===')
print('  Nothing is deleted here. Two ways out, and they are not the same:')
print('   - Status -> Archive: the post is kept, and the archive shows it as')
print('     "Discarded" - never went out, put away by hand. Reversible.')
print('   - The bin in the post list: gone for good, including its history.')
print('  A post that went out is the record of what happened. Keep that one.')
