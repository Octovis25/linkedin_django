"""Does replacing a medium still cost you the old one?

It used to. Hanging a picture on a post that already carried a video deleted
the video in Nextcloud, without asking - from the post editor and from the
Studio alike. Now the file that comes off travels back to the Studio outputs
and turns up under "My outputs" again, so swapping one for the other is a move
and not a loss.

The rule holds without exception: a video uploaded from a PC was never in the
Output folder, and still goes there. A rule with a special case is one nobody
can remember.

This test needs neither Nextcloud nor the database nor Django. It cuts the
three functions out of planner/views.py - the file that ships, so nothing here
can drift from it - and runs them against a stand-in that only remembers which
names are taken. What is checked is the decision, not the plumbing.

    python _tests/ersetzen_test.py
"""
import os
import re
import sys

HIER = os.path.dirname(os.path.abspath(__file__))
QUELLE = os.path.join(os.path.dirname(HIER), 'planner', 'views.py')
QUELLE_MEDIA = os.path.join(os.path.dirname(HIER), 'media_library', 'views.py')

with open(QUELLE, encoding='utf-8') as fh:
    SRC = fh.read()

_treffer = re.search(r'STUDIO_OUTPUT_PREFIX\s*=\s*"([^"]+)"', SRC)
if not _treffer:
    print('STUDIO_OUTPUT_PREFIX not found in planner/views.py')
    sys.exit(2)
OUT = _treffer.group(1)


def herausschneiden(name):
    """Take a function out of the shipping file. A top-level function ends at
    the next line that starts in column one - that is enough here and needs no
    parser."""
    marke = '\ndef %s(' % name
    if marke not in SRC:
        raise SystemExit('not found in planner/views.py: ' + name)
    zeilen = SRC[SRC.index(marke) + 1:].split('\n')
    raus = [zeilen[0]]
    for zeile in zeilen[1:]:
        if zeile and not zeile[0].isspace():
            break
        raus.append(zeile)
    return '\n'.join(raus)


class FakeNc:
    """Nextcloud, reduced to the one thing that matters here: a name is either
    free or taken, and MOVE says which."""

    def __init__(self, belegt=(), kaputt=False):
        self.belegt = set(belegt)
        self.kaputt = kaputt
        self.versuche = []      # every attempt, taken ones included
        self.moves = []         # only what really moved

    def move(self, src, dst, overwrite=True):
        self.versuche.append(dst)
        if self.kaputt:
            return None                       # no credentials, no network
        if not overwrite and dst in self.belegt:
            return False                      # the name is taken
        self.moves.append((src, dst))
        self.belegt.discard(src)
        self.belegt.add(dst)
        return dst


class FakeCursor:
    def __init__(self, row=None):
        self.row = row
        self.sql = []

    def execute(self, sql, params=None):
        self.sql.append((' '.join(sql.split()), params))

    def fetchone(self):
        return self.row

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeConnection:
    def __init__(self, cursor):
        self._c = cursor

    def cursor(self):
        return self._c


def baue(nc, cursor=None):
    """The functions under test, with everything outside them stubbed."""
    raum = {
        'STUDIO_OUTPUT_PREFIX': OUT,
        '_nc_move': nc.move,
        '_ensure_media_columns': lambda: None,
        'connection': FakeConnection(cursor or FakeCursor()),
        'print': lambda *a, **k: None,
    }
    code = '\n\n'.join(herausschneiden(n) for n in (
        '_carry_path_over', '_move_replaced_media_to_outputs', '_release_post_media'))
    exec(compile(code, 'planner/views.py (cut out)', 'exec'), raum)
    return raum


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


VIDEO = 'Marketing & Design/LinkedIn/Planner/Videos/Trust_series.webm'
BILD = 'Marketing & Design/LinkedIn/Planner/Images/Trust_series.png'

print('\n=== A replaced medium goes back to the outputs ===')
nc = FakeNc()
raum = baue(nc)
neu = raum['_move_replaced_media_to_outputs'](VIDEO)
pruefe('the video lands in the Output folder', neu == OUT + 'Trust_series.webm', neu)
pruefe('and exactly one move was needed', len(nc.moves) == 1, nc.moves)
pruefe('nothing was deleted - there is no delete here at all',
       '_nc_delete' not in herausschneiden('_move_replaced_media_to_outputs'))

print('\n=== A file uploaded from a PC is no special case ===')
nc = FakeNc()
raum = baue(nc)
pc = 'Marketing & Design/LinkedIn/Planner/Videos/WhatsApp_2026_09_18.mp4'
neu = raum['_move_replaced_media_to_outputs'](pc)
pruefe('it goes to the outputs like everything else',
       neu == OUT + 'WhatsApp_2026_09_18.mp4', neu)

print('\n=== A name already taken does not overwrite anything ===')
nc = FakeNc(belegt=[OUT + 'Trust_series.webm'])
raum = baue(nc)
neu = raum['_move_replaced_media_to_outputs'](VIDEO)
pruefe('the second one is called _2', neu == OUT + 'Trust_series_2.webm', neu)
pruefe('the taken name was tried first, then given up on',
       nc.versuche == [OUT + 'Trust_series.webm', OUT + 'Trust_series_2.webm'], nc.versuche)
pruefe('and the file that was there is untouched',
       nc.moves == [(VIDEO, OUT + 'Trust_series_2.webm')], nc.moves)

print('\n=== What is already in the outputs stays put ===')
nc = FakeNc()
raum = baue(nc)
drin = OUT + 'Header.png'
pruefe('no move at all', raum['_move_replaced_media_to_outputs'](drin) == drin and not nc.versuche,
       nc.versuche)

print('\n=== When Nextcloud says no ===')
nc = FakeNc(kaputt=True)
raum = baue(nc)
neu = raum['_move_replaced_media_to_outputs'](VIDEO)
pruefe('the old path comes back, never an empty value', neu == VIDEO, neu)
pruefe('and it gives up after one try instead of hammering twenty times',
       len(nc.versuche) == 1, len(nc.versuche))

print('\n=== The entries travel with the file ===')
nc = FakeNc()
zeiger = FakeCursor()
raum = baue(nc, zeiger)
neu = raum['_move_replaced_media_to_outputs'](VIDEO, zeiger)
tabellen = [s for s, _ in zeiger.sql]
pruefe('the library row is carried over',
       any('media_library_items' in s and 'UPDATE' in s for s in tabellen), tabellen)
pruefe('the Studio design is carried over',
       any('studio_images' in s and 'UPDATE' in s for s in tabellen), tabellen)
pruefe('both point at the new path',
       all(p == [neu, VIDEO] for _, p in zeiger.sql), zeiger.sql)

print('\n=== Taking the media off a post ===')
# (image, gif, video, status)
nc = FakeNc()
zeiger = FakeCursor(row=(BILD, '', VIDEO, 'Draft'))
raum = baue(nc, zeiger)
raum['_release_post_media'](zeiger, 42, keep=VIDEO)
bewegt = [s for s, _ in nc.moves]
pruefe('the picture goes back to the outputs', bewegt == [BILD], bewegt)
pruefe('the video that stays is not moved', VIDEO not in bewegt, bewegt)

print('\n=== A published post is left alone ===')
nc = FakeNc()
zeiger = FakeCursor(row=(BILD, '', VIDEO, 'Posted'))
raum = baue(nc, zeiger)
raum['_release_post_media'](zeiger, 42, keep=None)
pruefe('nothing is moved at all', not nc.moves, nc.moves)

print('\n=== The destructive version is really gone ===')
pruefe('planner/views.py no longer has _delete_post_media',
       '\ndef _delete_post_media(' not in SRC)
pruefe('nothing calls it any more', '_delete_post_media(' not in SRC)
with open(QUELLE_MEDIA, encoding='utf-8') as fh:
    SRC_MEDIA = fh.read()
_speichern = SRC_MEDIA[SRC_MEDIA.index('\ndef studio_save('):]
_speichern = _speichern[:_speichern.index('\ndef ', 1)]
pruefe('saving from the Studio no longer deletes the old media',
       '_cleanup_old_media' not in _speichern)
pruefe('it releases them instead', '_release_old_media' in _speichern)

print('\n%d ok, %d failed' % (gut, schlecht))
sys.exit(1 if schlecht else 0)
