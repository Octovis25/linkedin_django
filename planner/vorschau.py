"""Small preview pictures for the post lists.

Why it exists (Render, 13.10.2026): one visit to Create Posts -> All moved
about 25 MB. Every card loaded its picture in full size (a 1080 px PNG for a
56 px square), with a new address on each visit so the browser could never
keep it, and some videos were downloaded completely just to show their first
frame. Render's Hobby plan includes 5 GB a month.

Here every card gets one small JPEG: a picture scaled down, the first frame of
a GIF, or the first frame of a video - the frame Buffer and LinkedIn show as
the preview. It is made once, kept on disk, and the browser may keep it too.
"""
import hashlib
import io
import os
import subprocess
import tempfile

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import connection
from django.http import Http404, HttpResponse, HttpResponseNotModified

BREITEN = (112, 240)          # 56 px card at 2x, larger tiles
VIDEO_ENDUNGEN = ('.webm', '.mp4', '.mov', '.m4v')
PLANNER_BILDER = 'Marketing & Design/LinkedIn/Planner/Images/'


def schluessel(quelle, stand, breite):
    """Cache key and ETag in one: the source, its last change, the width."""
    roh = '%s|%s|%s' % (quelle, stand, breite)
    return hashlib.sha1(roh.encode('utf-8')).hexdigest()[:24]


def quelle_des_posts(bild, video):
    """(path, kind) of what the card shows: the picture first, else the video
    or GIF. kind is 'image', 'gif', 'video' or None."""
    if bild:
        pfad = bild
        if not pfad.startswith('Marketing') and not pfad.startswith('__local__/'):
            # Older rows keep a local name; the file lives in the planner folder.
            pfad = PLANNER_BILDER + pfad.split('/')[-1]
        return pfad, 'image'
    if video:
        endung = os.path.splitext(video)[1].lower()
        if endung == '.gif':
            return video, 'gif'
        if endung in VIDEO_ENDUNGEN:
            return video, 'video'
        return video, 'image'
    return None, None


def bild_verkleinern(rohdaten, breite):
    """Any picture (also the first frame of a GIF) -> a small JPEG."""
    from PIL import Image
    with Image.open(io.BytesIO(rohdaten)) as bild:
        bild.seek(0)
        bild = bild.convert('RGBA')
        grund = Image.new('RGB', bild.size, (255, 255, 255))
        grund.paste(bild, mask=bild.split()[3])
        grund.thumbnail((breite, breite * 4))
        aus = io.BytesIO()
        grund.save(aus, 'JPEG', quality=82, optimize=True)
        return aus.getvalue()


def erstes_videobild(rohdaten, endung, breite):
    """The first frame of a video as a small JPEG, made with ffmpeg.

    0.05 s rather than 0: some encoders put nothing visible at exactly 0.
    One thread, like the LinkedIn copy - Render has 512 MB.
    """
    import imageio_ffmpeg
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    with tempfile.TemporaryDirectory() as ordner:
        quelle = os.path.join(ordner, 'quelle' + (endung or '.webm'))
        ziel = os.path.join(ordner, 'bild.jpg')
        with open(quelle, 'wb') as f:
            f.write(rohdaten)
        befehl = [ffmpeg, '-hide_banner', '-loglevel', 'error', '-threads', '1',
                  '-ss', '0.05', '-i', quelle, '-frames:v', '1',
                  '-vf', 'scale=%d:-2' % breite, '-q:v', '4', '-y', ziel]
        lauf = subprocess.run(befehl, capture_output=True, timeout=60)
        if lauf.returncode != 0 or not os.path.isfile(ziel):
            # A video shorter than 0.05 s, or a start without a frame: try 0.
            befehl[befehl.index('-ss') + 1] = '0'
            subprocess.run(befehl, capture_output=True, timeout=60)
        if not os.path.isfile(ziel):
            return None
        with open(ziel, 'rb') as f:
            return f.read()


def _ordner():
    pfad = os.path.join(settings.BASE_DIR, 'media', '_thumbs', 'planner')
    os.makedirs(pfad, exist_ok=True)
    return pfad


def _rohdaten(pfad):
    if pfad.startswith('__local__/'):
        datei = os.path.join(settings.BASE_DIR, 'media', pfad[len('__local__/'):])
        if not os.path.isfile(datei):
            return None
        with open(datei, 'rb') as f:
            return f.read()
    from posts_posted.nc_storage import download_image_from_nextcloud
    inhalt, _typ = download_image_from_nextcloud(pfad)
    return inhalt


def _antwort(daten, etag, request):
    resp = HttpResponse(daten, content_type='image/jpeg')
    resp['ETag'] = '"%s"' % etag
    # With ?v= (the post's last change) the address changes whenever the post
    # does, so a day in the browser is safe. Without it the browser asks again
    # each time and gets "not modified" - no picture travels twice.
    resp['Cache-Control'] = ('private, max-age=86400' if request.GET.get('v')
                             else 'private, no-cache')
    return resp


@login_required
def post_vorschau(request, post_id):
    try:
        breite = int(request.GET.get('w') or BREITEN[0])
    except ValueError:
        breite = BREITEN[0]
    if breite not in BREITEN:
        breite = BREITEN[0]

    with connection.cursor() as c:
        c.execute("""SELECT COALESCE(image,''), COALESCE(video_nc_path,''), updated_at
                     FROM planner_posts WHERE id=%s""", [post_id])
        zeile = c.fetchone()
    if not zeile:
        raise Http404
    pfad, art = quelle_des_posts(zeile[0], zeile[1])
    if not pfad:
        raise Http404

    etag = schluessel(pfad, zeile[2], breite)
    if request.headers.get('If-None-Match', '').strip('"') == etag:
        resp = HttpResponseNotModified()
        resp['ETag'] = '"%s"' % etag
        return resp

    datei = os.path.join(_ordner(), etag + '.jpg')
    if os.path.isfile(datei):
        with open(datei, 'rb') as f:
            return _antwort(f.read(), etag, request)

    rohdaten = _rohdaten(pfad)
    if not rohdaten:
        raise Http404
    try:
        if art == 'video':
            daten = erstes_videobild(rohdaten, os.path.splitext(pfad)[1].lower(), breite)
        else:
            daten = bild_verkleinern(rohdaten, breite)
    except Exception as fehler:
        print('post preview %s: %s' % (post_id, fehler))
        daten = None
    if not daten:
        raise Http404
    try:
        with open(datei, 'wb') as f:
            f.write(daten)
    except OSError:
        pass
    return _antwort(daten, etag, request)
