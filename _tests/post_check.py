"""Why does the Studio open empty for this post?

Opening the Studio from a post loads, in this order: the design saved for the
file currently hanging on the post, then the design saved under the post id.
Only if one of them carries a canvas_json does the artboard fill. A post with a
video and no design therefore opens on an empty board - and nothing on screen
says why.

This walks the same search studio_view does, one step at a time, and says which
step would have won. It only reads.

    python _tests/post_check.py 60
"""
import os
import sys

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HIER))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dashboard.settings')

import django                                  # noqa: E402

django.setup()

from django.db import connection               # noqa: E402

if len(sys.argv) < 2 or not sys.argv[1].isdigit():
    print(__doc__)
    sys.exit(2)
POST = int(sys.argv[1])


def q(sql, params=()):
    with connection.cursor() as c:
        c.execute(sql, params)
        return c.fetchall()


zeilen = q("""SELECT id, COALESCE(title,''), COALESCE(image,''),
                     COALESCE(gif_nc_path,''), COALESCE(video_nc_path,''),
                     COALESCE(status,'')
              FROM planner_posts WHERE id=%s""", [POST])
if not zeilen:
    print('There is no post #%d.' % POST)
    sys.exit(1)

_id, titel, bild, gif, video, status = zeilen[0]
print('Post #%d  %s' % (_id, titel[:70]))
print('  status : %s' % (status or '(empty)'))
print('  image  : %s' % (bild or '-'))
print('  gif    : %s' % (gif or '-'))
print('  video  : %s' % (video or '-'))
print()

# Same order as studio_view: the file on the post decides which design is looked
# for first. image beats video beats gif.
medium = bild or video or gif
if not medium:
    print('No medium hangs on this post at all. The Studio opens empty because')
    print('there is nothing to open - that is correct, not a fault.')
    sys.exit(0)

dateiname = medium.rsplit('/', 1)[-1]
stamm = dateiname.rsplit('.', 1)[0]
print('The Studio looks for the design of: %s' % dateiname)
print()

gefunden = None


def schritt(nummer, was, sql, params):
    global gefunden
    treffer = q(sql, params)
    mit_entwurf = [t for t in treffer if t[1]]
    print('%d. %s' % (nummer, was))
    if not treffer:
        print('   nothing found')
    for kennung, hat_json, pfad, t_titel in treffer:
        print('   studio_images #%-6s canvas_json: %-4s  %s'
              % (kennung, 'yes' if hat_json else 'NO', (pfad or '')[:64]))
    if mit_entwurf and gefunden is None:
        gefunden = (nummer, mit_entwurf[0][0])
    print()


ABFRAGE = """SELECT id, CASE WHEN canvas_json IS NULL OR canvas_json='' THEN 0 ELSE 1 END,
                    COALESCE(nc_path,''), COALESCE(title,'')
             FROM studio_images WHERE %s ORDER BY id DESC LIMIT 5"""

schritt(1, 'by the exact path of the file on the post',
        ABFRAGE % 'nc_path=%s', [medium])
schritt(2, 'by its file name (the file may have been moved)',
        ABFRAGE % 'nc_path LIKE %s', ['%/' + dateiname])
schritt(3, 'by the post id',
        ABFRAGE % 'post_id=%s', [POST])
schritt(4, 'by name - image, GIF and video of one design share it',
        ABFRAGE % 'title=%s', [stamm])

if gefunden:
    nummer, kennung = gefunden
    print('=> Step %d wins: studio_images #%s.' % (nummer, kennung))
    print()
    # A row is not a drawing. The design can be there and still hold nothing -
    # and an empty artboard looks exactly the same either way.
    roh = q("SELECT canvas_json FROM studio_images WHERE id=%s", [kennung])[0][0] or ''
    print('   stored design : %d characters' % len(roh))
    try:
        import json
        daten = json.loads(roh)
        # The drawing lives under "fabric". The flat "objects" list next to it is
        # a helper for the backend - one entry per image, deliberately without a
        # type - and counting THAT says nothing about what is on the artboard.
        zeichnung = daten.get('fabric') if isinstance(daten.get('fabric'), dict) else daten
        objekte = zeichnung.get('objects') or []
        print('   elements      : %d  (under "fabric" - what the Studio rebuilds)' % len(objekte))
        hilfsliste = daten.get('objects') if daten.get('fabric') else []
        if hilfsliste:
            print('   image helper  : %d entr%s (for moving images to Nextcloud, not drawn)'
                  % (len(hilfsliste), 'y' if len(hilfsliste) == 1 else 'ies'))
        if zeichnung.get('backgroundImage'):
            print('   background    : an image is set')
        if not objekte:
            print('   -> The drawing is EMPTY: no elements were saved. The Studio')
            print('      has nothing to put on the artboard. The search is fine -')
            print('      the save that produced this row is the place to look.')
        else:
            arten = {}
            for o in objekte:
                arten[o.get('type', '?')] = arten.get(o.get('type', '?'), 0) + 1
            print('   kinds         : %s' % ', '.join('%s x%d' % kv for kv in sorted(arten.items())))
            # An element without a type is one the browser cannot rebuild: it is
            # skipped without a word, and the artboard stays empty although a
            # design is there. So show what the thing actually looks like.
            print('   top-level keys: %s' % ', '.join(sorted(daten.keys())))
            for nr, o in enumerate(objekte[:3], 1):
                if not isinstance(o, dict):
                    print('   element %d     : not an object at all: %r' % (nr, str(o)[:80]))
                    continue
                print('   element %d keys: %s' % (nr, ', '.join(sorted(o.keys()))[:300]))
                for schluessel in ('type', 'shapeKind', 'src', 'text', 'clItems'):
                    if schluessel in o:
                        wert = str(o[schluessel])
                        if len(wert) > 70:
                            wert = wert[:70] + ' … (%d characters)' % len(str(o[schluessel]))
                        print('      %-10s = %s' % (schluessel, wert))
                if 'type' not in o:
                    print('      -> no "type": the Studio skips this element without a word.')
    except Exception as fehler:
        print('   -> The stored design is NOT readable as JSON: %s' % fehler)
        print('      That is why the artboard stays empty - the browser gives up')
        print('      on it exactly as this does.')
        daten = None

    # The server rewrites Nextcloud references before handing the design to the
    # browser. If that step empties it, the browser never sees anything either.
    try:
        from media_library.views import _resolve_nc_refs_in_json
        fertig = _resolve_nc_refs_in_json(roh)
        print('   after the server prepares it: %d characters' % len(fertig or ''))
        if not fertig:
            print('   -> The preparation step empties it. That is the fault.')
    except Exception as fehler:
        print('   the preparation step raises: %s' % fehler)
        print('   -> That is the fault: the design never reaches the browser.')
else:
    print('=> No step finds a design with a canvas_json.')
    print('   The Studio has nothing to put on the artboard, and the empty board')
    print('   is the honest answer. Either the file was never built in the Studio')
    print('   (uploaded from a PC), or its design was saved under a name and path')
    print('   that no longer match. Steps 1 to 4 above show what IS stored.')
