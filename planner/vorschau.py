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
PLANNER_BILDER = 'Marketing_and_Design/LinkedIn/Planner/Images/'


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


def _dateistand(pfad):
    """The file's own version: Nextcloud's ETag (or last change), the mtime
    for a local file, '' when it cannot be asked.

    The post's updated_at alone is not enough. When the Studio saves a video
    again it writes the same file name, the row's values stay the same, and
    MySQL leaves updated_at alone - the card kept the old picture (#130,
    14.10.2026). The file itself always knows it has changed.
    """
    if pfad.startswith('__local__/'):
        datei = os.path.join(settings.BASE_DIR, 'media', pfad[len('__local__/'):])
        try:
            return str(int(os.path.getmtime(datei)))
        except OSError:
            return ''
    try:
        import re
        import requests
        from requests.auth import HTTPBasicAuth
        from urllib.parse import quote
        from posts_posted.nc_storage import _get_nc_credentials
        nc_url, user, pw = _get_nc_credentials()
        if not all([nc_url, user, pw]):
            return ''
        url = '%s/remote.php/dav/files/%s/%s' % (nc_url.rstrip('/'), user, quote(pfad, safe='/'))
        r = requests.request('PROPFIND', url, auth=HTTPBasicAuth(user, pw),
                             headers={'Depth': '0', 'Content-Type': 'application/xml'},
                             data='<?xml version="1.0"?><d:propfind xmlns:d="DAV:"><d:prop>'
                                  '<d:getetag/><d:getlastmodified/></d:prop></d:propfind>',
                             timeout=10)
        if r.status_code not in (200, 207):
            return ''
        for tag in ('getetag', 'getlastmodified'):
            m = re.search(r'<d:%s>([^<]*)</d:%s>' % (tag, tag), r.text)
            if m and m.group(1).strip():
                return m.group(1).strip().strip('"')
    except Exception as fehler:
        print('post preview: file version unknown (%s)' % fehler)
    return ''


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
    # does. But a medium can change without the post (same file name saved
    # again), so the browser keeps it only ten minutes and then asks - the
    # answer is "not modified" unless the file really changed, so no picture
    # travels twice. Without ?v= it asks every time.
    resp['Cache-Control'] = ('private, max-age=600' if request.GET.get('v')
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

    etag = schluessel(pfad, '%s|%s' % (zeile[2], _dateistand(pfad)), breite)
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
