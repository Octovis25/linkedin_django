"""Which posts does the calendar leave out, and why?

The page can only show a post it can put on a day. A post gets its day from
one of three places - the day it went out, the day it is due to go out, the day
it is planned for - and a post that has none of them cannot be drawn anywhere.

This walks every post in the database, works out its day with the very same
functions the page uses, and says for each one that is missing WHY it is
missing. Nothing is changed: it reads and prints.

    python _tests/kalender_check.py            # the current year
    python _tests/kalender_check.py 2026
    python _tests/kalender_check.py 2026 Heart  # where is that one post?

With a search word it looks the other way round: every post whose title or
text contains it, and for each the day the calendar puts it on. A post that
"is missing" is usually on a day nobody was looking at.
"""
import os
import sys
from datetime import date

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HIER))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dashboard.settings')

import django                                   # noqa: E402

django.setup()

from django.db import connection                # noqa: E402

from planner.kalender import (                  # noqa: E402
    _posts_des_jahres, _tag_aus_iso, posts_ohne_datum)

try:
    JAHR = int(sys.argv[1])
    SUCHE = ' '.join(sys.argv[2:]).strip()
except (IndexError, ValueError):
    JAHR = date.today().year
    SUCHE = ' '.join(sys.argv[1:]).strip()

print('\n=== The calendar for %d ===' % JAHR)

with connection.cursor() as c:
    c.execute("""SELECT p.id, COALESCE(p.title,''), COALESCE(p.content,''),
                        COALESCE(p.status,''), p.linkedin_posted,
                        p.planned_date, p.post_scheduled_at,
                        COALESCE(t.name,''), COALESCE(p.is_oj,0)
                 FROM planner_posts p
                 LEFT JOIN planner_topics t ON p.topic_id = t.id
                 ORDER BY p.id""")
    alle = c.fetchall()

    puffer = {}
    try:
        c.execute("""SELECT planner_post_id, COALESCE(due_at,''), COALESCE(sent_at,'')
                     FROM buffer_posts_posted""")
        for kennung, faellig, gesendet in c.fetchall():
            if kennung:
                puffer[kennung] = (faellig, gesendet)
    except Exception as fehler:
        print('  (no buffer table: %s)' % fehler)

im_jahr = {p['id']: p for p in _posts_des_jahres(JAHR)}
ohne_datum = {p['id'] for p in posts_ohne_datum(grenze=10000)}

print('  %d posts in the database, %d of them drawn in %d.'
      % (len(alle), len(im_jahr), JAHR))


def kurz(titel, inhalt, breite=44):
    text = (titel or '').strip() or (inhalt or '').replace('\n', ' ').strip()
    return (text[:breite - 1] + '…') if len(text) > breite else text


if SUCHE:
    print('\n=== Posts matching %r ===' % SUCHE)
    nadel = SUCHE.lower()
    treffer = [z for z in alle
               if nadel in (z[1] or '').lower()      # title
               or nadel in (z[2] or '').lower()      # text
               or nadel in (z[7] or '').lower()]     # topic - the chip on the page
    if not treffer:
        print('  nothing matches - the post may be worded differently than you')
        print('  remember, or it may not be in planner_posts at all.')
    for (kennung, titel, inhalt, status, veroeffentlicht, geplant, gesagt,
         thema, nur_oj) in treffer:
        faellig, gesendet = puffer.get(kennung, ('', ''))
        tag_gesendet = _tag_aus_iso(gesendet)
        tag_faellig = _tag_aus_iso(faellig)
        tag = tag_gesendet or tag_faellig or (gesagt.date() if gesagt else None) or geplant
        if kennung in im_jahr:
            wo = 'DRAWN on %s - look at %s' % (
                im_jahr[kennung]['kalendertag'].strftime('%d.%m.%Y'),
                im_jahr[kennung]['kalendertag'].strftime('%B'))
        elif tag is None:
            wo = 'no day anywhere - it is in the list under the calendar'
        else:
            wo = 'has a day in %d (%s), so not on this year\'s page' % (
                tag.year, tag.strftime('%d.%m.%Y'))
        print('\n  #%-5s %-9s %-10s %s' % (kennung, status, thema or '-',
                                            kurz(titel, inhalt, 44)))
        print('        %s' % wo)
        if nur_oj:
            print('        is_oj=1 - every other planner page hides this post too')
        print('        planned_date=%s  post_scheduled_at=%s  linkedin_posted=%s'
              % (geplant, gesagt, veroeffentlicht))
        print('        buffer due_at=%r  sent_at=%r' % (faellig, gesendet))
    print('\n(Run it without a search word for the full picture.)')
    sys.exit(0)

fehlen = [z for z in alle if z[0] not in im_jahr]
print('\n=== The %d that are NOT in %d ===' % (len(fehlen), JAHR))
if not fehlen:
    print('  none - every post has a day in this year.')

zaehler = {}
for (kennung, titel, inhalt, status, veroeffentlicht, geplant, gesagt,
     thema, nur_oj) in fehlen:
    faellig, gesendet = puffer.get(kennung, ('', ''))
    tag_gesendet = _tag_aus_iso(gesendet)
    tag_faellig = _tag_aus_iso(faellig)

    # The same order the page uses: it happened > it is due > it is planned.
    tag = tag_gesendet or tag_faellig or (gesagt.date() if gesagt else None) or geplant

    if tag is None:
        grund = ('listed under the calendar as "without any date"'
                 if kennung in ohne_datum
                 else 'NO DAY AND NOT LISTED EITHER - this one is invisible')
    elif tag.year != JAHR:
        grund = 'has a day, but in %d (%s)' % (tag.year, tag.strftime('%d.%m.%Y'))
    else:
        grund = ('WOULD have a day in %d (%s) but the page does not draw it'
                 % (JAHR, tag.strftime('%d.%m.%Y')))

    zaehler[grund.split(' (')[0].split(' - ')[0]] = \
        zaehler.get(grund.split(' (')[0].split(' - ')[0], 0) + 1

    auffaellig = 'NO DAY' in grund or 'does not draw' in grund
    print('  %s#%-5s %-44s %-10s %s' % ('>> ' if auffaellig else '   ',
                                        kennung, kurz(titel, inhalt), status, grund))
    if auffaellig:
        print('          planned_date=%s  post_scheduled_at=%s' % (geplant, gesagt))
        print('          buffer due_at=%r  sent_at=%r' % (faellig, gesendet))
        print('          linkedin_posted=%s' % veroeffentlicht)

print('\n=== In short ===')
for grund, wie_viele in sorted(zaehler.items(), key=lambda x: -x[1]):
    print('  %3d  %s' % (wie_viele, grund))

print('\nA post marked >> is one to look at: it either has no date anywhere,')
print('or it has one and the page still leaves it out - and those are two')
print('different faults.')
