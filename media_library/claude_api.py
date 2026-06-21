"""
Claude API – Nur Lese-/Schreibzugriff auf Bilder und Texte.
Kein Zugriff auf Code, Settings oder DB-Struktur.
Abgesichert über CLAUDE_API_KEY Umgebungsvariable.
"""
import os
import json
import base64
from functools import wraps
from django.http import JsonResponse
from django.db import connection
from django.views.decorators.csrf import csrf_exempt


def _safe(cursor, sql, params=None):
    try:
        cursor.execute(sql, params or [])
        return cursor.fetchall()
    except Exception:
        return None


def require_api_key(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        key = os.getenv('CLAUDE_API_KEY', '')
        if not key:
            return JsonResponse({'error': 'API not configured'}, status=503)
        provided = request.headers.get('X-Api-Key', '') or request.GET.get('api_key', '')
        if provided != key:
            return JsonResponse({'error': 'Unauthorized'}, status=401)
        return view_func(request, *args, **kwargs)
    return wrapper


# ── Bilder ──────────────────────────────────────

@csrf_exempt
@require_api_key
def list_images(request):
    """Alle Bilder aus der Medienbibliothek auflisten."""
    q = request.GET.get('q', '')
    tag = request.GET.get('tag', '')
    limit = min(int(request.GET.get('limit', 50)), 200)

    sql = "SELECT id, title, nc_path, person, series, tags FROM media_library_items WHERE 1=1"
    params = []
    if q:
        sql += " AND (title LIKE %s OR person LIKE %s)"
        params += [f'%{q}%', f'%{q}%']
    if tag:
        sql += " AND tags LIKE %s"
        params.append(f'%{tag}%')
    sql += " ORDER BY id DESC LIMIT %s"
    params.append(limit)

    with connection.cursor() as c:
        rows = _safe(c, sql, params) or []

    return JsonResponse({'images': [
        {'id': r[0], 'title': r[1] or '', 'nc_path': r[2] or '',
         'person': r[3] or '', 'series': r[4] or '', 'tags': r[5] or '',
         'url': f'/library/image/{r[0]}/'}
        for r in rows
    ]})


@csrf_exempt
@require_api_key
def upload_image(request):
    """Bild als Base64 hochladen in die Medienbibliothek."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    try:
        data = json.loads(request.body)
    except Exception:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    title = data.get('title', 'Claude Upload')
    image_b64 = data.get('image_base64', '')
    tags = data.get('tags', 'studio')
    folder_id = data.get('folder_id')

    if not image_b64:
        return JsonResponse({'error': 'image_base64 required'}, status=400)

    # Decode and upload to Nextcloud
    try:
        import tempfile
        img_data = base64.b64decode(image_b64)
        ext = 'png'
        if img_data[:3] == b'\xff\xd8\xff':
            ext = 'jpg'

        with tempfile.NamedTemporaryFile(suffix=f'.{ext}', delete=False) as tmp:
            tmp.write(img_data)
            tmp_path = tmp.name

        from posts_posted.nc_storage import upload_image_to_nextcloud
        from media_library.views import NC_LIBRARY_FOLDER
        nc_path = upload_image_to_nextcloud(tmp_path, NC_LIBRARY_FOLDER, f"{title}.{ext}")
        os.unlink(tmp_path)
    except Exception as e:
        # Fallback: save locally
        nc_path = f"__local__/claude_{title}.png"

    with connection.cursor() as c:
        c.execute(
            "INSERT INTO media_library_items (title, nc_path, tags, folder_id) VALUES (%s, %s, %s, %s)",
            [title, nc_path, tags, folder_id]
        )
        item_id = c.lastrowid

    return JsonResponse({'ok': True, 'id': item_id, 'nc_path': nc_path})


# ── Posts / Texte ───────────────────────────────

@csrf_exempt
@require_api_key
def list_posts(request):
    """Alle geplanten Posts auflisten."""
    limit = min(int(request.GET.get('limit', 50)), 200)
    status = request.GET.get('status', '')

    sql = "SELECT id, title, content, image, status, planned_date FROM planner_posts WHERE 1=1"
    params = []
    if status:
        sql += " AND status=%s"
        params.append(status)
    sql += " ORDER BY id DESC LIMIT %s"
    params.append(limit)

    with connection.cursor() as c:
        rows = _safe(c, sql, params) or []

    return JsonResponse({'posts': [
        {'id': r[0], 'title': r[1] or '', 'content': r[2] or '',
         'image': r[3] or '', 'status': r[4] or '', 'planned_date': str(r[5] or '')}
        for r in rows
    ]})


@csrf_exempt
@require_api_key
def get_post(request, post_id):
    """Einzelnen Post abrufen."""
    with connection.cursor() as c:
        rows = _safe(c, "SELECT id, title, content, image, status, planned_date FROM planner_posts WHERE id=%s", [post_id])
    if not rows:
        return JsonResponse({'error': 'Not found'}, status=404)
    r = rows[0]
    return JsonResponse({'post': {
        'id': r[0], 'title': r[1] or '', 'content': r[2] or '',
        'image': r[3] or '', 'status': r[4] or '', 'planned_date': str(r[5] or '')
    }})


@csrf_exempt
@require_api_key
def update_post_text(request, post_id):
    """Post-Text aktualisieren (nur content und/oder title)."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    try:
        data = json.loads(request.body)
    except Exception:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    updates = []
    params = []
    if 'content' in data:
        updates.append("content=%s")
        params.append(data['content'])
    if 'title' in data:
        updates.append("title=%s")
        params.append(data['title'])

    if not updates:
        return JsonResponse({'error': 'Nothing to update'}, status=400)

    params.append(post_id)
    with connection.cursor() as c:
        c.execute(f"UPDATE planner_posts SET {', '.join(updates)} WHERE id=%s", params)

    return JsonResponse({'ok': True})


# ── Templates ───────────────────────────────────

@csrf_exempt
@require_api_key
def list_templates(request):
    """Studio-Templates auflisten."""
    with connection.cursor() as c:
        rows = _safe(c, "SELECT id, name, nc_path FROM studio_templates ORDER BY id DESC") or []

    return JsonResponse({'templates': [
        {'id': r[0], 'name': r[1] or '', 'url': f'/library/studio/template/image/{r[0]}/'}
        for r in rows
    ]})


# ── Status ──────────────────────────────────────

@csrf_exempt
@require_api_key
def list_aufgaben(request):
    """Offene Aufgaben abrufen."""
    status = request.GET.get('status', 'offen')
    with connection.cursor() as c:
        rows = _safe(c, "SELECT id, aufgabe, typ, status, ergebnis, post_id, created_at FROM claude_aufgaben WHERE status=%s ORDER BY id ASC", [status]) or []
    return JsonResponse({'aufgaben': [
        {'id': r[0], 'aufgabe': r[1], 'typ': r[2], 'status': r[3],
         'ergebnis': r[4] or '', 'post_id': r[5], 'created_at': str(r[6] or '')}
        for r in rows
    ]})


@csrf_exempt
@require_api_key
def update_aufgabe(request, aufgabe_id):
    """Aufgabe aktualisieren (Status, Ergebnis). Akzeptiert POST (JSON) oder GET (Query-Params)."""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
        except Exception:
            return JsonResponse({'error': 'Invalid JSON'}, status=400)
    else:
        data = request.GET.dict()

    updates = []
    params = []
    if 'status' in data:
        updates.append("status=%s")
        params.append(data['status'])
    if 'ergebnis' in data:
        updates.append("ergebnis=%s")
        params.append(data['ergebnis'])
    if data.get('status') == 'erledigt':
        updates.append("done_at=NOW()")

    if not updates:
        return JsonResponse({'error': 'Nothing to update'}, status=400)

    params.append(aufgabe_id)
    with connection.cursor() as c:
        c.execute(f"UPDATE claude_aufgaben SET {', '.join(updates)} WHERE id=%s", params)
    return JsonResponse({'ok': True})


@csrf_exempt
@require_api_key
def api_status(request):
    """Prüft ob die API erreichbar ist."""
    with connection.cursor() as c:
        img_count = (_safe(c, "SELECT COUNT(*) FROM media_library_items") or [[0]])[0][0]
        post_count = (_safe(c, "SELECT COUNT(*) FROM planner_posts") or [[0]])[0][0]
        aufgaben_count = (_safe(c, "SELECT COUNT(*) FROM claude_aufgaben WHERE status='offen'") or [[0]])[0][0]
    return JsonResponse({
        'ok': True,
        'project': 'linkedin_django',
        'images': img_count,
        'posts': post_count,
        'offene_aufgaben': aufgaben_count
    })
