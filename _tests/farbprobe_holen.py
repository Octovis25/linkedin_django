"""Fetch one post's video and the template it was built on, for a colour check.

The template background comes out darker in exported videos. Where exactly -
in the browser's recording, in Cloudinary's conversion, or at LinkedIn - decides
the fix, so it has to be measured, not guessed. This only collects the two
files to compare; it changes nothing, and uses the app's own Nextcloud access.

    python _tests/farbprobe_holen.py          # post #53
    python _tests/farbprobe_holen.py 77 117 52   # several posts at once

The files land in _farbprobe/ - not meant for git.
"""
import json
import os
import sys
import urllib.parse

HIER = os.path.dirname(os.path.abspath(__file__))
WURZEL = os.path.dirname(HIER)
sys.path.insert(0, WURZEL)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dashboard.settings')

import django                                   # noqa: E402

django.setup()

from django.db import connection                # noqa: E402

from media_library.views import _nc_download    # noqa: E402

MIT_VORLAGE = '--mit-vorlage' in sys.argv
VORLAGEN = '--vorlagen' in sys.argv
POSTS = [int(a) for a in sys.argv[1:] if a.isdigit()] or ([] if (MIT_VORLAGE or VORLAGEN) else [53])
POST = None
ZIEL = os.path.join(WURZEL, '_farbprobe')
os.makedirs(ZIEL, exist_ok=True)


def nc_pfad(quelle):
    """A Nextcloud path out of whatever form the design stored it in."""
    if not quelle:
        return ''
    if quelle.startswith('nc://'):
        return quelle[5:]
    teile = urllib.parse.urlparse(quelle)
    p = urllib.parse.parse_qs(teile.query).get('p')
    if p:
        return p[0]
    return ''


def holen(pfad, name):
    if not pfad:
        print('  -  %-9s (no path)' % name)
        return
    daten, art = _nc_download(pfad)
    if not daten:
        print('  !! %-9s could not be downloaded: %s' % (name, pfad))
        return
    endung = os.path.splitext(pfad)[1] or '.bin'
    datei = os.path.join(ZIEL, 'post%d_%s%s' % (POST, name, endung))
    with open(datei, 'wb') as fh:
        fh.write(daten)
    print('  ok %-9s %7d KB  %s' % (name, len(daten) // 1024, pfad))


if VORLAGEN:
    # Every Studio template as a file, to be laid on a canvas and recorded the
    # way the Studio records - the one stage no downloaded post can show.
    print('\n=== downloading the Studio templates into _farbprobe/ ===')
    with connection.cursor() as c:
        c.execute('SELECT id, title, nc_path FROM studio_templates ORDER BY id')
        vorlagen = c.fetchall()
    for tid, titel, pfad in vorlagen:
        daten, _art = _nc_download(pfad)
        if not daten:
            print('  !! #%s %s could not be downloaded' % (tid, titel))
            continue
        with open(os.path.join(ZIEL, 'vorlage_%s%s' % (tid, os.path.splitext(pfad)[1] or '.png')),
                  'wb') as fh:
            fh.write(daten)
        print('  ok #%-3s %-28s %6d KB' % (tid, (titel or '')[:28], len(daten) // 1024))

if MIT_VORLAGE:
    # Which moving posts were built on a Studio template? A template can be
    # recorded three ways: template_id, the canvas background image, or an
    # ordinary layer whose file lies in the Templates folder.
    print('\n=== posts with a video or GIF that were built on a template ===')
    with connection.cursor() as c:
        c.execute("""SELECT p.id, p.title, p.status, COALESCE(p.video_nc_path,''),
                            COALESCE(p.gif_nc_path,''), s.id, s.template_id, s.canvas_json
                     FROM planner_posts p
                     JOIN studio_images s ON s.post_id = p.id
                     WHERE COALESCE(p.video_nc_path,'') <> '' OR COALESCE(p.gif_nc_path,'') <> ''
                     ORDER BY p.id DESC, s.id DESC""")
        gesehen = set()
        for pid, titel, status, video, gif, sid, tid, roh in c.fetchall():
            if pid in gesehen:
                continue
            gesehen.add(pid)
            try:
                fab = (json.loads(roh or '{}') or {}).get('fabric') or {}
            except ValueError:
                fab = {}
            bgi = ((fab.get('backgroundImage') or {}).get('src') or '')
            ebenen = [o.get('src', '') for o in (fab.get('objects') or [])
                      if (o or {}).get('type') == 'image' and '/Templates/' in (o.get('src') or '')]
            wie = []
            if tid:
                wie.append('template_id=%s' % tid)
            if bgi:
                wie.append('background image')
            if ebenen:
                wie.append('template as layer')
            if not wie:
                continue
            datei = (video or gif).rsplit('/', 1)[-1]
            print('  #%-4s %-9s %-26s %-40s %s' % (pid, status, ', '.join(wie),
                                                   (titel or '')[:40], datei[-40:]))
    print('\nPick one and run:  python _tests/farbprobe_holen.py <id>')

for POST in POSTS:
    with connection.cursor() as c:
        c.execute("""SELECT title, COALESCE(video_nc_path,''), COALESCE(gif_nc_path,''),
                            COALESCE(image,'')
                     FROM planner_posts WHERE id=%s""", [POST])
        zeile = c.fetchone()
        if not zeile:
            print('\n#%d not found' % POST)
            continue
        titel, video, gif, bild = zeile
        print('\n#%d  %s' % (POST, (titel or '')[:60]))

        c.execute("""SELECT id, canvas_json, template_id FROM studio_images
                     WHERE post_id=%s ORDER BY id DESC LIMIT 1""", [POST])
        entwurf = c.fetchone()

        vorlage = hintergrund = ''
        ebenen = []
        if entwurf:
            eid, roh, tid = entwurf
            print('  design: studio_images #%s, template_id=%s' % (eid, tid))
            try:
                fab = (json.loads(roh or '{}') or {}).get('fabric') or {}
                # A template can also sit on the canvas as an ordinary image
                # layer rather than as the background - #53 has it that way.
                for nr, obj in enumerate(fab.get('objects') or [], start=1):
                    if (obj or {}).get('type') == 'image':
                        quelle = obj.get('src', '')
                        print('  layer %d: image %sx%s  %s' % (
                            nr, obj.get('width'), obj.get('height'), quelle[:110]))
                        ebenen.append((nr, nc_pfad(quelle)))
                bgi = fab.get('backgroundImage') or {}
                if fab.get('background'):
                    print('  canvas background colour: %s' % fab.get('background'))
                hintergrund = nc_pfad(bgi.get('src', ''))
                if not hintergrund and bgi.get('src'):
                    print('  background src not a Nextcloud path: %s' % bgi.get('src')[:100])
            except ValueError:
                print('  canvas_json is not readable')
            if tid:
                c.execute('SELECT nc_path FROM studio_templates WHERE id=%s', [tid])
                t = c.fetchone()
                vorlage = t[0] if t else ''
        else:
            print('  no studio design for this post')

    print('\n=== downloading into _farbprobe/ ===')
    holen(video, 'video')
    holen(gif, 'gif')
    holen(bild, 'bild')
    for nr, pfad in ebenen:
        holen(pfad, 'ebene%d' % nr)
    holen(vorlage, 'vorlage')
    if hintergrund and hintergrund != vorlage:
        holen(hintergrund, 'hintergrund')


    def cloudinary_holen():
        """The MP4 that Buffer got - Cloudinary's conversion of the same video.

        Its address is not stored anywhere, and the name carries an upload
        timestamp, so it is looked up: every upload for this post starts with
        linkedin_post_<id>_. The app's own Cloudinary keys are used and never
        printed. Nothing is uploaded or deleted.
        """
        import requests
        wolke = os.environ.get('CLOUDINARY_CLOUD_NAME', '').strip()
        schluessel = os.environ.get('CLOUDINARY_API_KEY', '').strip()
        geheim = os.environ.get('CLOUDINARY_API_SECRET', '').strip()
        if not (wolke and schluessel and geheim):
            print('  -  cloudinary (not configured on this machine)')
            return
        funde = []
        # A Studio video goes up as a video; an animated GIF as an image.
        for art in ('video', 'image'):
            antwort = requests.get(
                'https://api.cloudinary.com/v1_1/%s/resources/%s/upload' % (wolke, art),
                params={'prefix': 'linkedin_post_%d_' % POST, 'max_results': 50},
                auth=(schluessel, geheim), timeout=30)
            if antwort.status_code != 200:
                print('  !! cloudinary %s listing: HTTP %s' % (art, antwort.status_code))
                continue
            funde += antwort.json().get('resources', [])
        if not funde:
            print('  -  cloudinary (no upload for this post)')
            return
        funde.sort(key=lambda r: r.get('created_at', ''))
        neuestes = funde[-1]
        print('  %d upload(s) for this post, taking the newest: %s (%s)'
              % (len(funde), neuestes.get('public_id'), neuestes.get('created_at')))
        url = neuestes.get('secure_url', '')
        mp4 = url.rsplit('.', 1)[0] + '.mp4'
        datei = requests.get(mp4, timeout=120)
        if datei.status_code != 200 or not datei.content:
            print('  !! cloudinary mp4: HTTP %s' % datei.status_code)
            return
        with open(os.path.join(ZIEL, 'post%d_cloudinary.mp4' % POST), 'wb') as fh:
            fh.write(datei.content)
        print('  ok %-9s %7d KB  %s' % ('cloudinary', len(datei.content) // 1024, mp4))


    try:
        cloudinary_holen()
    except Exception as fehler:
        print('  !! cloudinary: %s' % fehler)

print('\n=== templates in the Studio ===')
with connection.cursor() as c:
    try:
        c.execute('SELECT id, title, nc_path FROM studio_templates ORDER BY id')
        for tid, titel, pfad in c.fetchall():
            print('  #%-3s %-28s %s' % (tid, (titel or '')[:28], pfad))
    except Exception as fehler:
        print('  (could not list: %s)' % fehler)

print('\nDone. Nothing was changed.')
