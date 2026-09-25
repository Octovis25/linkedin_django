"""One view instead of two under Data (25.09.2026).

'Posts Posted' showed what LinkedIn reports (the Excel upload), 'Buffer Posts
Posted' what Buffer sent. Ortrud: "one view is enough". The two lists are now
put together row by row by zusammenfuehren() in posts_posted/views.py.

There is no shared ID - LinkedIn and Buffer number the same post differently -
so the text decides, with the key from linkedin_statistics/post_text.py, and
within one text the dates do. The cases below are real ones from the lists of
25.09.2026.

No database, no Django: the two functions are cut out of the files that ship.

    python _tests/posts_posted_test.py
"""
import os
import sys
from datetime import date

HIER = os.path.dirname(os.path.abspath(__file__))
WURZEL = os.path.dirname(HIER)


def lies(*teile):
    with open(os.path.join(WURZEL, *teile), encoding='utf-8') as fh:
        return fh.read()


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


VIEWS = lies('posts_posted', 'views.py')
POST_TEXT = lies('linkedin_statistics', 'post_text.py')
RAUM = {'__builtins__': __builtins__, 'ZEICHEN': 45}
exec(compile(herausschneiden(POST_TEXT, '_inhalts_schluessel'), 'post_text.py (cut out)', 'exec'), RAUM)
exec(compile(herausschneiden(VIEWS, 'zusammenfuehren'), 'views.py (cut out)', 'exec'), RAUM)
schluessel = RAUM['_inhalts_schluessel']


def zf(li, bu):
    return RAUM['zusammenfuehren'](li, bu, schluessel)


ok = fehl = 0


def pruefe(name, bedingung, detail=''):
    global ok, fehl
    if bedingung:
        ok += 1
        print('  ok   ' + name)
    else:
        fehl += 1
        print('  FAIL ' + name + (('   [%s]' % detail) if detail else ''))


def L(text, tag, pid='li'):
    return {'text': text, 'datum': tag, 'post_id': pid}


def B(text, tag, status='sent', bid='bu'):
    return {'text': text, 'datum': tag, 'status': status, 'buffer_post_id': bid}


T = 'Transparency in clinical trials starts with the data. Traceable. Auditable.'
WORK = 'We work as if we were part of your in-house team. No generic solutions.'
OVER = "Oversight should not depend on chasing updates. Because you can't improve"
EVERY = 'Every data point in a clinical trial represents a patient. Making that data'
SOP = 'SOP management should do more than store documents. It should connect'
DIREKT = 'Behind the Scenes of Data Management - Change Requests. A change request'

print('\n=== One post, both sources ===')
z = zf([L(T, date(2026, 9, 21))], [B(T, date(2026, 9, 21))])
pruefe('one row', len(z) == 1, len(z))
pruefe('it is in both', z and z[0]['art'] == 'both')
pruefe('nothing to check', z and z[0]['hinweise'] == [], z and z[0]['hinweise'])
z = zf([L('Clean data stays quiet.Messy  data could get expensive.', date(2026, 7, 31))],
       [B('Clean data stays quiet.Messy data could get\nexpensive.', date(2026, 7, 31))])
pruefe('spaces and line breaks do not keep them apart', len(z) == 1 and z[0]['art'] == 'both')
z = zf([L(T, date(2026, 9, 20))], [B(T, date(2026, 9, 21))])
pruefe('a day apart is not a disagreement (time zones)', z and z[0]['hinweise'] == [], z and z[0]['hinweise'])

print('\n=== Only one side ===')
z = zf([], [B(SOP, date(2026, 9, 28), 'scheduled')])
pruefe('a queued post is a row of its own', len(z) == 1 and z[0]['art'] == 'bu')
pruefe('and is not flagged', z and z[0]['hinweise'] == [])
z = zf([L(DIREKT, date(2026, 2, 23))], [])
pruefe('a post that went out directly is LinkedIn only', len(z) == 1 and z[0]['art'] == 'li')
pruefe('and keeps its LinkedIn date', z and z[0]['datum'] == date(2026, 2, 23))

print('\n=== The same text more than once ===')
# Posted on 08.06. and again on 14.09. The export dates BOTH 08.06.
z = zf([L(WORK, date(2026, 6, 8), 'li-juni'), L(WORK, date(2026, 6, 8), 'li-sept')],
       [B(WORK, date(2026, 6, 8), bid='b-juni'), B(WORK, date(2026, 9, 14), bid='b-sept')])
pruefe('a text posted twice is two rows', len(z) == 2, len(z))
pruefe('both in both sources', all(r['art'] == 'both' for r in z))
pruefe('the Buffer date wins: one row is on 14.09.',
       sorted(r['datum'] for r in z) == [date(2026, 6, 8), date(2026, 9, 14)])
spaet = [r for r in z if r['datum'] == date(2026, 9, 14)]
pruefe('and says the Excel has another day for it',
       spaet and 'Excel says 08.06.' in spaet[0]['hinweise'], spaet and spaet[0]['hinweise'])
pruefe('both say the text is twice in the Excel data',
       all('2× in the Excel data' in r['hinweise'] for r in z))
pruefe('each Buffer entry is used once',
       sorted(r['bu']['buffer_post_id'] for r in z) == ['b-juni', 'b-sept'])

# One LinkedIn post, three Buffer entries.
z = zf([L(OVER, date(2026, 7, 21))],
       [B(OVER, date(2026, 7, 20), bid='a'), B(OVER, date(2026, 7, 20), bid='b'),
        B(OVER, date(2026, 7, 21), bid='c')])
pruefe('three Buffer copies of one post stay one row', len(z) == 1, len(z))
pruefe('paired with the Buffer entry of its own day', z and z[0]['bu']['buffer_post_id'] == 'c')
pruefe('the other two are named as repeats',
       z and '3× in Buffer (20.07., 20.07., 21.07.)' in z[0]['hinweise'], z and z[0]['hinweise'])

# Twice in the export, once in Buffer.
z = zf([L(EVERY, date(2026, 6, 5), 'x'), L(EVERY, date(2026, 6, 5), 'y')], [B(EVERY, date(2026, 6, 5))])
pruefe('two export entries, one Buffer entry: two rows', len(z) == 2)
pruefe('one of them in both, one LinkedIn only',
       sorted(r['art'] for r in z) == ['both', 'li'])
pruefe('both flagged', all(r['hinweise'] for r in z))

print('\n=== Order and odd rows ===')
z = zf([L(T, date(2026, 9, 21)), L('', None, 'leer1'), L('', None, 'leer2')],
       [B(SOP, date(2026, 9, 28), 'scheduled'), B(OVER, date(2026, 7, 21))])
pruefe('newest first', [r['datum'] for r in z][:3] ==
       [date(2026, 9, 28), date(2026, 9, 21), date(2026, 7, 21)])
pruefe('rows without a date at the end', [r['datum'] for r in z][3:] == [None, None])
pruefe('two posts without text are not taken for one', sum(1 for r in z if r['datum'] is None) == 2)
pruefe('and are not called the same text twice',
       all(r['hinweise'] == [] for r in z if r['datum'] is None), [r['hinweise'] for r in z if r['datum'] is None])

print('\n=== The page ===')
BASIS = lies('core', 'templates', 'core', 'base.html')
URLS = lies('posts_posted', 'urls.py')
VORLAGE = lies('posts_posted', 'templates', 'posts_posted', 'list.html')
LISTE = herausschneiden(VIEWS, 'post_list')
ALT = herausschneiden(VIEWS, 'buffer_post_list')
pruefe('Data has no tab "Buffer Posts Posted" any more', 'Buffer Posts Posted' not in BASIS)
pruefe('Posts Posted and Upload are still there',
       '>Posts Posted</a>' in BASIS and '/data/upload/' in BASIS)
pruefe('the old address still exists', 'path("buffer/", views.buffer_post_list' in URLS)
pruefe('and sends you to Posts Posted', "redirect('posts_posted:list')" in ALT)
pruefe('the page uses the same content key as the statistics',
       'from linkedin_statistics.post_text import' in LISTE and '_inhalts_schluessel' in LISTE)
pruefe('it shows the first ten', '"zuerst": 10' in LISTE and 'var ZUERST = {{ zuerst }}' in VORLAGE)
pruefe('the five filters are on the page',
       all('data-f="%s"' % f in VORLAGE for f in ('all', 'both', 'li', 'bu', 'check')))
pruefe('Edit, Auto-fill images and the Excel upload are still reachable',
       "posts_posted:edit" in VORLAGE and 'fillImagesFromBuffer' in VORLAGE and '/data/upload/' in VORLAGE)
pruefe('the date of the last Buffer fetch is shown', 'last_fetch' in VORLAGE and '"last_fetch": last_fetch' in LISTE)

print('\n%d ok, %d failed' % (ok, fehl))
sys.exit(1 if fehl else 0)
