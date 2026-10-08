"""Tutorials: short how-to films for our portals, made from screenshots.

A film is a row of steps. Each step is one screenshot with a click point, an
optional frame around what matters, a caption and a recorded voice. The film
is put together in the browser (WebCodecs, like the Studio's post videos), so
the server only stores files - Render's 512 MB stay untouched (08.10.2026).

Files live in Nextcloud under Octotrial_Assets/Tutorials/<portal>/<film id>/.
Nothing is ever deleted here: a removed step only leaves the film, its files
stay; a new video gets a new name and the old one remains.
"""
import hashlib
import json
import os
import re
import time
from urllib.parse import quote

from django.contrib.auth.decorators import login_required
from django.db import connection
from django.http import Http404, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie

from media_library.views import _nc_upload, einmal_pro_prozess

PORTALS = [
    ('sop', 'SOP Portal'),
    ('dev', 'Developer Portal'),
    ('val', 'Validation Portal'),
    ('hub', 'Octovis Hub'),
]
PORTAL_NAMES = dict(PORTALS)
STATUSES = ['Draft', 'Video ready', 'In portal']
LANGS = ['en', 'de']

NC_ROOT = 'Marketing & Design/Octotrial_Assets/Tutorials'

IMAGE_TYPES = {'image/png': 'png', 'image/jpeg': 'jpg', 'image/webp': 'webp'}
AUDIO_TYPES = {'audio/webm': 'webm', 'audio/ogg': 'ogg', 'audio/mp4': 'm4a',
               'audio/mpeg': 'mp3', 'audio/wav': 'wav', 'video/webm': 'webm'}
MAX_IMAGE = 15 * 1024 * 1024
MAX_AUDIO = 20 * 1024 * 1024
MAX_VIDEO = 200 * 1024 * 1024

# What a step may change through the API, and how each value is read.
STEP_FIELDS = {
    'click_x': 'ratio', 'click_y': 'ratio',
    'frame_x': 'ratio', 'frame_y': 'ratio', 'frame_w': 'ratio', 'frame_h': 'ratio',
    'highlight': 'highlight', 'caption': 'caption', 'script': 'script',
    'image_nc_path': 'path', 'audio_nc_path': 'path', 'audio_ms': 'ms', 'min_ms': 'ms',
}


# ── Schema ──────────────────────────────────────────────────────────────────
@einmal_pro_prozess
def ensure_tables():
    with connection.cursor() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS tutorial_films (
            id            INT AUTO_INCREMENT PRIMARY KEY,
            portal        VARCHAR(10)  NOT NULL DEFAULT 'sop',
            title         VARCHAR(200) NOT NULL DEFAULT '',
            page          VARCHAR(200) NOT NULL DEFAULT '',
            lang          VARCHAR(5)   NOT NULL DEFAULT 'en',
            status        VARCHAR(20)  NOT NULL DEFAULT 'Draft',
            video_nc_path VARCHAR(512) NULL,
            video_seconds DOUBLE       NULL,
            created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at    DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci""")
        c.execute("""CREATE TABLE IF NOT EXISTS tutorial_steps (
            id            INT AUTO_INCREMENT PRIMARY KEY,
            film_id       INT NOT NULL,
            pos           INT NOT NULL DEFAULT 0,
            image_nc_path VARCHAR(512) NULL,
            click_x       DOUBLE NULL,
            click_y       DOUBLE NULL,
            highlight     VARCHAR(10) NOT NULL DEFAULT 'frame',
            frame_x       DOUBLE NULL,
            frame_y       DOUBLE NULL,
            frame_w       DOUBLE NULL,
            frame_h       DOUBLE NULL,
            caption       VARCHAR(300) NOT NULL DEFAULT '',
            script        TEXT NULL,
            audio_nc_path VARCHAR(512) NULL,
            audio_ms      INT NULL,
            min_ms        INT NOT NULL DEFAULT 3000,
            INDEX (film_id)
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci""")


# ── Helpers ─────────────────────────────────────────────────────────────────
def file_url(nc_path):
    """The same-origin address of a stored file (the Studio's proxy)."""
    if not nc_path:
        return ''
    return '/library/studio/nc-image/?p=' + quote(nc_path, safe='/')


def film_folder(portal, film_id):
    return f'{NC_ROOT}/{portal}/{film_id}'


def path_of_film(nc_path, film):
    """True when a path lies in this film's own folder - and nowhere else."""
    if not nc_path:
        return True
    if any(seg == '..' for seg in nc_path.split('/')):
        return False
    ordner = film_folder(film['portal'], film['id']) + '/'
    lokal = '__local__/tutorials/' + film['portal'] + '/' + str(film['id']) + '/'
    return nc_path.startswith(ordner) or nc_path.startswith(lokal)


def store(content, nc_path, content_type):
    """Into Nextcloud; when that is out of reach, onto the server's disk.

    The disk copy is what the Studio does as well: the work is not lost, and
    the proxy serves __local__ paths the same way."""
    stored = _nc_upload(content, nc_path, content_type)
    if stored:
        return stored
    from django.conf import settings
    relativ = 'tutorials/' + nc_path[len(NC_ROOT) + 1:]
    ziel = os.path.join(settings.BASE_DIR, 'media', *relativ.split('/'))
    os.makedirs(os.path.dirname(ziel), exist_ok=True)
    with open(ziel, 'wb') as fh:
        fh.write(content)
    return '__local__/' + relativ


def slug(text, fallback='film'):
    s = re.sub(r'[^A-Za-z0-9]+', '_', text or '').strip('_')[:60]
    return s or fallback


def load_film(film_id):
    ensure_tables()
    with connection.cursor() as c:
        c.execute("""SELECT id, portal, title, page, lang, status, video_nc_path,
                            video_seconds, updated_at
                     FROM tutorial_films WHERE id=%s""", [film_id])
        r = c.fetchone()
    if not r:
        return None
    return {
        'id': r[0], 'portal': r[1], 'title': r[2], 'page': r[3], 'lang': r[4],
        'status': r[5], 'video_nc_path': r[6] or '', 'video_url': file_url(r[6]),
        'video_seconds': r[7],
        'updated_at': r[8].strftime('%d.%m.%Y %H:%M') if r[8] else '',
    }


STEP_COLUMNS = ('id, pos, image_nc_path, click_x, click_y, highlight, frame_x, frame_y, '
                'frame_w, frame_h, caption, script, audio_nc_path, audio_ms, min_ms')


def load_steps(film_id):
    with connection.cursor() as c:
        c.execute(f"SELECT {STEP_COLUMNS} FROM tutorial_steps WHERE film_id=%s ORDER BY pos, id",
                  [film_id])
        rows = c.fetchall()
    steps = []
    for r in rows:
        steps.append({
            'id': r[0], 'pos': r[1],
            'image_nc_path': r[2] or '', 'image_url': file_url(r[2]),
            'click_x': r[3], 'click_y': r[4], 'highlight': r[5] or 'frame',
            'frame_x': r[6], 'frame_y': r[7], 'frame_w': r[8], 'frame_h': r[9],
            'caption': r[10] or '', 'script': r[11] or '',
            'audio_nc_path': r[12] or '', 'audio_url': file_url(r[12]),
            'audio_ms': r[13], 'min_ms': r[14] or 3000,
        })
    return steps


def film_list(portal):
    ensure_tables()
    with connection.cursor() as c:
        c.execute("""SELECT f.id, f.title, f.status, f.video_seconds,
                            (SELECT COUNT(*) FROM tutorial_steps s WHERE s.film_id = f.id)
                     FROM tutorial_films f WHERE f.portal=%s
                     ORDER BY f.updated_at DESC, f.id DESC""", [portal])
        return [{'id': r[0], 'title': r[1], 'status': r[2],
                 'length': _laenge(r[3]),
                 'steps': r[4]} for r in c.fetchall()]


def _laenge(sekunden):
    if not sekunden:
        return ''
    s = int(round(sekunden))
    return '%d:%02d' % (s // 60, s % 60)


def _json_body(request):
    try:
        return json.loads(request.body or b'{}')
    except ValueError:
        return None


def _read_value(art, wert):
    """A step field as the database wants it; ValueError when it is not one."""
    if art == 'ratio':
        if wert is None or wert == '':
            return None
        v = float(wert)
        if not 0.0 <= v <= 1.0:
            raise ValueError('outside 0..1')
        return v
    if art == 'ms':
        if wert is None or wert == '':
            return None
        v = int(wert)
        if not 0 <= v <= 10 * 60 * 1000:
            raise ValueError('out of range')
        return v
    if art == 'highlight':
        if wert not in ('frame', 'none'):
            raise ValueError('frame or none')
        return wert
    if art == 'caption':
        return str(wert or '')[:300]
    if art == 'script':
        return str(wert or '')[:5000]
    if art == 'path':
        return str(wert or '') or None
    raise ValueError(art)


# ── Page ────────────────────────────────────────────────────────────────────
@login_required
@ensure_csrf_cookie
def tutorials_view(request):
    portal = request.GET.get('portal') or 'sop'
    if portal not in PORTAL_NAMES:
        portal = 'sop'
    films = film_list(portal)
    try:
        film_id = int(request.GET.get('film') or 0)
    except ValueError:
        film_id = 0
    if not film_id and films:
        film_id = films[0]['id']
    film = load_film(film_id) if film_id else None
    if film and film['portal'] != portal:
        film = None
    return render(request, 'tutorials/tutorials.html', {
        'portals': PORTALS, 'portal': portal, 'portal_name': PORTAL_NAMES[portal],
        'films': films, 'film': film, 'statuses': STATUSES, 'langs': LANGS,
    })


# ── API ─────────────────────────────────────────────────────────────────────
@login_required
def api_film_get(request, film_id):
    film = load_film(film_id)
    if not film:
        raise Http404
    return JsonResponse({'ok': True, 'film': film, 'steps': load_steps(film_id)})


@login_required
def api_film(request):
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'POST required'}, status=405)
    daten = _json_body(request)
    if daten is None:
        return JsonResponse({'ok': False, 'error': 'Invalid JSON'}, status=400)
    ensure_tables()
    aktion = daten.get('action')
    if aktion == 'create':
        portal = daten.get('portal')
        titel = str(daten.get('title') or '').strip()[:200]
        if portal not in PORTAL_NAMES or not titel:
            return JsonResponse({'ok': False, 'error': 'Portal and title are needed.'}, status=400)
        with connection.cursor() as c:
            c.execute("INSERT INTO tutorial_films (portal, title) VALUES (%s, %s)", [portal, titel])
            neu = c.lastrowid
        return JsonResponse({'ok': True, 'id': neu})
    if aktion == 'update':
        film = load_film(daten.get('id') or 0)
        if not film:
            return JsonResponse({'ok': False, 'error': 'Film not found'}, status=404)
        werte = {}
        if 'title' in daten:
            titel = str(daten.get('title') or '').strip()[:200]
            if not titel:
                return JsonResponse({'ok': False, 'error': 'The title cannot be empty.'}, status=400)
            werte['title'] = titel
        if 'page' in daten:
            werte['page'] = str(daten.get('page') or '').strip()[:200]
        if 'lang' in daten:
            if daten['lang'] not in LANGS:
                return JsonResponse({'ok': False, 'error': 'Unknown language'}, status=400)
            werte['lang'] = daten['lang']
        if 'status' in daten:
            if daten['status'] not in STATUSES:
                return JsonResponse({'ok': False, 'error': 'Unknown status'}, status=400)
            werte['status'] = daten['status']
        if werte:
            spalten = ', '.join(f'{k}=%s' for k in werte)
            with connection.cursor() as c:
                c.execute(f"UPDATE tutorial_films SET {spalten} WHERE id=%s",
                          list(werte.values()) + [film['id']])
        return JsonResponse({'ok': True, 'film': load_film(film['id'])})
    return JsonResponse({'ok': False, 'error': 'Unknown action'}, status=400)


@login_required
def api_step(request):
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'POST required'}, status=405)
    daten = _json_body(request)
    if daten is None:
        return JsonResponse({'ok': False, 'error': 'Invalid JSON'}, status=400)
    ensure_tables()
    aktion = daten.get('action')

    if aktion == 'create':
        film = load_film(daten.get('film_id') or 0)
        if not film:
            return JsonResponse({'ok': False, 'error': 'Film not found'}, status=404)
        bild = daten.get('image_nc_path') or None
        if not path_of_film(bild, film):
            return JsonResponse({'ok': False, 'error': 'File is not in this film'}, status=400)
        with connection.cursor() as c:
            c.execute("SELECT COALESCE(MAX(pos), 0) FROM tutorial_steps WHERE film_id=%s", [film['id']])
            pos = c.fetchone()[0] + 1
            c.execute("""INSERT INTO tutorial_steps (film_id, pos, image_nc_path, caption)
                         VALUES (%s, %s, %s, %s)""",
                      [film['id'], pos, bild, str(daten.get('caption') or '')[:300]])
            neu = c.lastrowid
            c.execute("UPDATE tutorial_films SET status='Draft' WHERE id=%s", [film['id']])
        return JsonResponse({'ok': True, 'id': neu, 'steps': load_steps(film['id'])})

    # Every other action works on an existing step - and through it, its film.
    with connection.cursor() as c:
        c.execute("SELECT film_id, pos FROM tutorial_steps WHERE id=%s", [daten.get('id') or 0])
        zeile = c.fetchone()
    if not zeile:
        return JsonResponse({'ok': False, 'error': 'Step not found'}, status=404)
    film = load_film(zeile[0])
    schritt_id, pos = daten['id'], zeile[1]

    if aktion == 'update':
        werte = {}
        try:
            for feld, art in STEP_FIELDS.items():
                if feld in daten:
                    werte[feld] = _read_value(art, daten[feld])
        except (TypeError, ValueError) as fehler:
            return JsonResponse({'ok': False, 'error': f'Invalid value: {fehler}'}, status=400)
        for feld in ('image_nc_path', 'audio_nc_path'):
            if feld in werte and not path_of_film(werte[feld], film):
                return JsonResponse({'ok': False, 'error': 'File is not in this film'}, status=400)
        if werte:
            spalten = ', '.join(f'{k}=%s' for k in werte)
            with connection.cursor() as c:
                c.execute(f"UPDATE tutorial_steps SET {spalten} WHERE id=%s",
                          list(werte.values()) + [schritt_id])
                # The saved video no longer shows this film.
                c.execute("UPDATE tutorial_films SET status='Draft' WHERE id=%s AND status='Video ready'",
                          [film['id']])
        return JsonResponse({'ok': True})

    if aktion == 'delete':
        # The row goes; its screenshot and voice stay in Nextcloud.
        with connection.cursor() as c:
            c.execute("DELETE FROM tutorial_steps WHERE id=%s", [schritt_id])
            c.execute("UPDATE tutorial_films SET status='Draft' WHERE id=%s AND status='Video ready'",
                      [film['id']])
        return JsonResponse({'ok': True, 'steps': load_steps(film['id'])})

    if aktion == 'move':
        richtung = -1 if daten.get('dir') == -1 else 1
        schritte = load_steps(film['id'])
        ids = [s['id'] for s in schritte]
        i = ids.index(schritt_id)
        j = i + richtung
        if 0 <= j < len(ids):
            ids[i], ids[j] = ids[j], ids[i]
            with connection.cursor() as c:
                for n, sid in enumerate(ids, start=1):
                    c.execute("UPDATE tutorial_steps SET pos=%s WHERE id=%s", [n, sid])
                c.execute("UPDATE tutorial_films SET status='Draft' WHERE id=%s AND status='Video ready'",
                          [film['id']])
        return JsonResponse({'ok': True, 'steps': load_steps(film['id'])})

    return JsonResponse({'ok': False, 'error': 'Unknown action'}, status=400)


@login_required
def api_upload(request):
    """A screenshot or a voice recording for one film."""
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'POST required'}, status=405)
    film = load_film(request.POST.get('film_id') or 0)
    if not film:
        return JsonResponse({'ok': False, 'error': 'Film not found'}, status=404)
    art = request.POST.get('kind')
    datei = request.FILES.get('file')
    if art not in ('image', 'audio') or not datei:
        return JsonResponse({'ok': False, 'error': 'An image or a recording is needed.'}, status=400)
    typ = (datei.content_type or '').split(';')[0].strip().lower()
    erlaubt, grenze = (IMAGE_TYPES, MAX_IMAGE) if art == 'image' else (AUDIO_TYPES, MAX_AUDIO)
    if typ not in erlaubt:
        return JsonResponse({'ok': False, 'error': f'This file type is not accepted: {typ or "unknown"}'},
                            status=400)
    if datei.size > grenze:
        return JsonResponse({'ok': False, 'error': 'The file is too large.'}, status=400)
    inhalt = datei.read()
    kurz = hashlib.sha1(inhalt).hexdigest()[:8]
    stamm = slug(os.path.splitext(datei.name or '')[0], art)[:40]
    ordner = 'screens' if art == 'image' else 'voice'
    nc_path = f"{film_folder(film['portal'], film['id'])}/{ordner}/{stamm}_{kurz}.{erlaubt[typ]}"
    gespeichert = store(inhalt, nc_path, typ)
    return JsonResponse({'ok': True, 'nc_path': gespeichert, 'url': file_url(gespeichert)})


@login_required
def api_video(request):
    """The finished film from the browser. A new name each time - older
    versions stay where they are."""
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'POST required'}, status=405)
    film = load_film(request.POST.get('film_id') or 0)
    if not film:
        return JsonResponse({'ok': False, 'error': 'Film not found'}, status=404)
    datei = request.FILES.get('video')
    if not datei:
        return JsonResponse({'ok': False, 'error': 'No video'}, status=400)
    if datei.size > MAX_VIDEO:
        return JsonResponse({'ok': False, 'error': 'The video is too large.'}, status=400)
    try:
        sekunden = float(request.POST.get('seconds') or 0) or None
    except ValueError:
        sekunden = None
    stempel = time.strftime('%Y%m%d-%H%M')
    nc_path = f"{film_folder(film['portal'], film['id'])}/{slug(film['title'])}_{stempel}.webm"
    gespeichert = store(datei.read(), nc_path, 'video/webm')
    with connection.cursor() as c:
        c.execute("""UPDATE tutorial_films SET video_nc_path=%s, video_seconds=%s,
                            status=CASE WHEN status='In portal' THEN status ELSE 'Video ready' END
                     WHERE id=%s""", [gespeichert, sekunden, film['id']])
    return JsonResponse({'ok': True, 'film': load_film(film['id'])})
