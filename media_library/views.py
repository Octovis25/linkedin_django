import os
import json
import tempfile
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.http import JsonResponse, HttpResponse, Http404
from django.db import connection
from django.contrib import messages

NC_LIBRARY_FOLDER = "Marketing & Design/LinkedIn/Medienbibliothek"


def _safe(cur, sql, params=None):
    try:
        cur.execute(sql, params or [])
        return cur.fetchall()
    except Exception as e:
        print("Library SQL:", e)
        return []


def _ensure_table():
    with connection.cursor() as c:
        try:
            c.execute("""
                CREATE TABLE IF NOT EXISTS media_library_folders (
                    id         INT AUTO_INCREMENT PRIMARY KEY,
                    name       VARCHAR(255) NOT NULL,
                    color      VARCHAR(20) DEFAULT '#008591',
                    sort_order INT DEFAULT 0,
                    parent_id  INT DEFAULT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
        except Exception:
            pass
        try:
            c.execute("""
                CREATE TABLE IF NOT EXISTS media_library_items (
                    id         INT AUTO_INCREMENT PRIMARY KEY,
                    nc_path    VARCHAR(512) NOT NULL,
                    title      VARCHAR(255) DEFAULT '',
                    person     VARCHAR(100) DEFAULT '',
                    series     VARCHAR(100) DEFAULT '',
                    tags       VARCHAR(255) DEFAULT '',
                    note       TEXT,
                    folder_id  INT DEFAULT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
        except Exception:
            pass
        # Add folder_id if missing (existing tables)
        try:
            c.execute("ALTER TABLE media_library_items ADD COLUMN folder_id INT DEFAULT NULL")
        except Exception:
            pass
        # Add parent_id to folders if missing
        try:
            c.execute("ALTER TABLE media_library_folders ADD COLUMN parent_id INT DEFAULT NULL")
        except Exception:
            pass


def _all_folders():
    with connection.cursor() as c:
        rows = _safe(c, "SELECT id, name, color, sort_order, parent_id FROM media_library_folders ORDER BY sort_order, name")
    return [{'id': r[0], 'name': r[1], 'color': r[2] or '#008591', 'sort_order': r[3] or 0, 'parent_id': r[4]} for r in (rows or [])]


def _all_items(filters=None):
    filters = filters or {}
    sql = "SELECT id, nc_path, title, person, series, tags, note, created_at, folder_id FROM media_library_items WHERE 1=1"
    params = []
    if filters.get('folder_id') and filters['folder_id'] not in ('none', 'all', ''):
        # Include items in this folder AND all subfolders
        fid = filters['folder_id']
        with connection.cursor() as fc:
            sub_rows = _safe(fc, "SELECT id FROM media_library_folders WHERE parent_id=%s", [fid])
        sub_ids = [r[0] for r in (sub_rows or [])]
        all_ids = [int(fid)] + sub_ids
        placeholders = ','.join(['%s'] * len(all_ids))
        sql += f" AND folder_id IN ({placeholders})"
        params += all_ids
    elif filters.get('folder') == 'none':
        sql += " AND (folder_id IS NULL OR folder_id=0)"
    if filters.get('person'):
        sql += " AND person=%s"
        params.append(filters['person'])
    if filters.get('series'):
        sql += " AND series=%s"
        params.append(filters['series'])
    if filters.get('tag'):
        sql += " AND FIND_IN_SET(%s, REPLACE(tags,' ',''))"
        params.append(filters['tag'].strip())
    if filters.get('q'):
        sql += " AND (title LIKE %s OR person LIKE %s OR series LIKE %s OR tags LIKE %s OR note LIKE %s)"
        like = f"%{filters['q']}%"
        params += [like, like, like, like, like]
    sql += " ORDER BY created_at DESC"
    with connection.cursor() as c:
        rows = _safe(c, sql, params)
    return [
        {'id': r[0], 'nc_path': r[1], 'title': r[2] or '',
         'person': r[3] or '', 'series': r[4] or '',
         'tags': r[5] or '', 'tags_list': [t.strip() for t in (r[5] or '').split(',') if t.strip()],
         'note': r[6] or '', 'created_at': r[7], 'folder_id': r[8],
         'is_video': (r[1] or '').lower().endswith(('.webm', '.mp4'))}
        for r in (rows or [])
    ]


def _meta_options():
    with connection.cursor() as c:
        persons = [r[0] for r in (_safe(c, "SELECT DISTINCT person FROM media_library_items WHERE person != '' ORDER BY person") or [])]
        series  = [r[0] for r in (_safe(c, "SELECT DISTINCT series  FROM media_library_items WHERE series  != '' ORDER BY series")  or [])]
        tag_rows = _safe(c, "SELECT tags FROM media_library_items WHERE tags != ''") or []
    all_tags = set()
    for (t,) in tag_rows:
        for tag in t.split(','):
            tag = tag.strip()
            if tag:
                all_tags.add(tag)
    return persons, series, sorted(all_tags)


@login_required
def library_view(request):
    _ensure_table()
    f = {
        'person': request.GET.get('person', ''),
        'series':  request.GET.get('series', ''),
        'tag':     request.GET.get('tag', ''),
        'q':       request.GET.get('q', ''),
        'folder_id': request.GET.get('folder', ''),
        'folder': request.GET.get('folder', ''),
    }
    items   = _all_items(f)
    persons, series, tags = _meta_options()
    folders = _all_folders()
    # Count templates
    _ensure_studio_tables()
    try:
        with connection.cursor() as c:
            rows = _safe(c, "SELECT COUNT(*) FROM studio_templates", [])
            templates_count = rows[0][0] if rows else 0
    except Exception:
        templates_count = 0
    import json as _json
    folders_json = _json.dumps([{'id': fo['id'], 'name': fo['name'], 'color': fo['color'], 'parent_id': fo['parent_id']} for fo in folders])
    return render(request, 'media_library/library.html', {
        'items': items, 'persons': persons, 'series_list': series, 'tags': tags,
        'folders': folders, 'folders_json': folders_json, 'filter_folder': f['folder_id'],
        'filter_person': f['person'], 'filter_series': f['series'],
        'filter_tag': f['tag'], 'filter_q': f['q'],
        'templates_count': templates_count,
        'tab': 'library',
    })


@login_required
def library_upload(request):
    _ensure_table()
    if request.method != 'POST':
        return redirect('media_library:library')
    image = request.FILES.get('image')
    if not image:
        messages.error(request, 'Kein Bild ausgewählt.')
        return redirect('media_library:library')
    title  = request.POST.get('title', '').strip()
    person = request.POST.get('person', '').strip()
    series = request.POST.get('series', '').strip()
    tags   = request.POST.get('tags', '').strip()
    note   = request.POST.get('note', '').strip()

    suffix   = os.path.splitext(image.name)[1] or '.jpg'
    import time
    filename = f"lib_{int(time.time())}{suffix}"

    # Save file locally first
    from django.conf import settings as _settings
    local_lib_dir = os.path.join(_settings.MEDIA_ROOT, 'library_uploads')
    os.makedirs(local_lib_dir, exist_ok=True)
    local_path = os.path.join(local_lib_dir, filename)
    with open(local_path, 'wb') as f_out:
        for chunk in image.chunks():
            f_out.write(chunk)

    # Try Nextcloud upload, fall back to local
    nc_path = None
    try:
        from posts_posted.nc_storage import _get_nc_credentials
        from urllib.parse import quote
        from requests.auth import HTTPBasicAuth
        import requests as _req
        nc_url, username, password = _get_nc_credentials()
        if nc_url and username and password:
            nc_path_base = NC_LIBRARY_FOLDER + "/" + filename
            with open(local_path, 'rb') as f_obj:
                content = f_obj.read()
            upload_url = f"{nc_url}/remote.php/dav/files/{username}/{quote(nc_path_base, safe='/')}"
            r = _req.put(upload_url, data=content,
                auth=HTTPBasicAuth(username, password),
                headers={"Content-Type": image.content_type or "image/jpeg"},
                timeout=30)
            if r.status_code in [200, 201, 204]:
                nc_path = nc_path_base
    except Exception as e:
        print(f"NC upload failed, using local: {e}")

    if not nc_path:
        nc_path = '__local__/' + filename

    folder_id = request.POST.get('folder_id') or None
    with connection.cursor() as c:
        c.execute("""INSERT INTO media_library_items (nc_path, title, person, series, tags, note, folder_id)
                     VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                  [nc_path, title, person, series, tags, note or None, folder_id])
    # AJAX: return JSON instead of redirect
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'ok': True, 'title': title})
    messages.success(request, 'Bild gespeichert!')
    return redirect('media_library:library')


@login_required
def library_image(request, item_id):
    with connection.cursor() as c:
        rows = _safe(c, "SELECT nc_path FROM media_library_items WHERE id=%s", [item_id])
    if not rows:
        raise Http404
    nc_path = rows[0][0]
    # Local fallback for studio-saved images
    if nc_path.startswith('__local__/'):
        from django.conf import settings as _settings
        rel = nc_path[len('__local__/'):]
        # Check both possible locations
        local_path = os.path.join(_settings.MEDIA_ROOT, 'library_uploads', rel)
        if not os.path.exists(local_path):
            local_path = os.path.join(_settings.BASE_DIR, 'media', rel)
        if not os.path.exists(local_path):
            raise Http404
        with open(local_path, 'rb') as f:
            content = f.read()
        ext = os.path.splitext(local_path)[1].lower()
        ct_map = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
                  '.webm': 'video/webm', '.mp4': 'video/mp4', '.gif': 'image/gif'}
        ct = ct_map.get(ext, 'image/jpeg')
        resp = HttpResponse(content, content_type=ct)
        resp['Cache-Control'] = 'public, max-age=86400'
        return resp
    from posts_posted.nc_storage import download_image_from_nextcloud
    content, ct = download_image_from_nextcloud(nc_path)
    if not content:
        raise Http404
    resp = HttpResponse(content, content_type=ct or 'image/jpeg')
    resp['Cache-Control'] = 'public, max-age=86400'
    return resp


@login_required
def library_edit(request, item_id):
    if request.method != 'POST':
        return redirect('media_library:library')
    with connection.cursor() as c:
        c.execute("""UPDATE media_library_items
                     SET title=%s, person=%s, series=%s, tags=%s, note=%s
                     WHERE id=%s""",
                  [request.POST.get('title','').strip(),
                   request.POST.get('person','').strip(),
                   request.POST.get('series','').strip(),
                   request.POST.get('tags','').strip(),
                   request.POST.get('note','').strip() or None,
                   item_id])
    messages.success(request, 'Gespeichert!')
    return redirect('media_library:library')


@login_required
def library_delete(request, item_id):
    if request.method != 'POST':
        return redirect('media_library:library')
    with connection.cursor() as c:
        rows = _safe(c, "SELECT nc_path FROM media_library_items WHERE id=%s", [item_id])
    if rows:
        nc_path = rows[0][0]
        from posts_posted.nc_storage import delete_image_from_nextcloud
        delete_image_from_nextcloud(nc_path)
        with connection.cursor() as c:
            c.execute("DELETE FROM media_library_items WHERE id=%s", [item_id])
            # Clean up linked studio data
            try: c.execute("DELETE FROM studio_images WHERE nc_path=%s", [nc_path])
            except Exception: pass
            try: c.execute("DELETE FROM studio_video_templates WHERE preview_nc_path=%s", [nc_path])
            except Exception: pass
    # AJAX request → JSON response
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or 'fetch' in request.headers.get('Sec-Fetch-Mode', ''):
        return JsonResponse({'ok': True})
    messages.success(request, 'Bild gelöscht.')
    return redirect('media_library:library')


@login_required
def library_api(request):
    """JSON API für das Modal-Picker im Edit-Post-Modal."""
    _ensure_table()
    f = {
        'person': request.GET.get('person', ''),
        'series':  request.GET.get('series', ''),
        'tag':     request.GET.get('tag', ''),
        'q':       request.GET.get('q', ''),
    }
    items = _all_items(f)
    return JsonResponse({'items': [
        {'id': i['id'], 'title': i['title'], 'person': i['person'],
         'series': i['series'], 'url': f"/library/image/{i['id']}/"}
        for i in items
    ]})


# ─────────────────────────────────────────────
#  FOLDER MANAGEMENT
# ─────────────────────────────────────────────

@login_required
def folder_create(request):
    """Create a new folder."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    _ensure_table()
    data = json.loads(request.body)
    name = data.get('name', '').strip()
    color = data.get('color', '#008591').strip()
    parent_id = data.get('parent_id') or None
    if not name:
        return JsonResponse({'error': 'Name required'}, status=400)
    with connection.cursor() as c:
        c.execute("INSERT INTO media_library_folders (name, color, parent_id) VALUES (%s, %s, %s)", [name, color, parent_id])
        folder_id = c.lastrowid
    # Create matching Nextcloud subfolder
    try:
        from posts_posted.nc_storage import _get_nc_credentials
        from requests.auth import HTTPBasicAuth
        from urllib.parse import quote
        import requests as _req
        nc_url, username, password = _get_nc_credentials()
        if nc_url and username:
            mkcol_url = f"{nc_url}/remote.php/dav/files/{username}/{quote(NC_LIBRARY_FOLDER + '/' + name, safe='/')}"
            _req.request('MKCOL', mkcol_url, auth=HTTPBasicAuth(username, password), timeout=15)
    except Exception as e:
        print("NC folder create:", e)
    return JsonResponse({'ok': True, 'id': folder_id, 'name': name, 'color': color})


@login_required
def folder_rename(request, folder_id):
    """Rename a folder."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    data = json.loads(request.body)
    name = data.get('name', '').strip()
    if not name:
        return JsonResponse({'error': 'Name required'}, status=400)
    with connection.cursor() as c:
        c.execute("UPDATE media_library_folders SET name=%s WHERE id=%s", [name, folder_id])
    return JsonResponse({'ok': True})


@login_required
def folder_delete(request, folder_id):
    """Delete a folder (items become unassigned)."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    with connection.cursor() as c:
        # Also handle child folders
        child_rows = _safe(c, "SELECT id FROM media_library_folders WHERE parent_id=%s", [folder_id])
        child_ids = [r[0] for r in (child_rows or [])]
        for cid in child_ids:
            c.execute("UPDATE media_library_items SET folder_id=NULL WHERE folder_id=%s", [cid])
            c.execute("DELETE FROM media_library_folders WHERE id=%s", [cid])
        c.execute("UPDATE media_library_items SET folder_id=NULL WHERE folder_id=%s", [folder_id])
        c.execute("DELETE FROM media_library_folders WHERE id=%s", [folder_id])
    return JsonResponse({'ok': True})


@login_required
def item_move(request):
    """Move one or more items to a folder (or to no folder)."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    data = json.loads(request.body)
    item_ids = data.get('item_ids', [])
    folder_id = data.get('folder_id')  # None = remove from folder
    if not item_ids:
        return JsonResponse({'error': 'No items'}, status=400)
    placeholders = ','.join(['%s'] * len(item_ids))
    with connection.cursor() as c:
        c.execute(f"UPDATE media_library_items SET folder_id=%s WHERE id IN ({placeholders})",
                  [folder_id] + list(item_ids))
    return JsonResponse({'ok': True})


@login_required
def item_studio_info(request, item_id):
    """Check if a library item has a saved canvas_json in studio_images."""
    _ensure_studio_tables()
    with connection.cursor() as c:
        rows = _safe(c, "SELECT nc_path FROM media_library_items WHERE id=%s", [item_id])
        if not rows:
            return JsonResponse({'has_canvas': False})
        nc_path = rows[0][0] or ''
        is_video = nc_path.lower().endswith(('.mp4', '.webm', '.mov', '.avi', '.mkv'))
        studio_rows = _safe(c, """SELECT id, canvas_json, template_id, post_id
                                  FROM studio_images WHERE nc_path=%s
                                  ORDER BY created_at DESC LIMIT 1""", [nc_path])
        if studio_rows and studio_rows[0][1]:
            r = studio_rows[0]
            cj = _resolve_nc_refs_in_json(r[1])
            return JsonResponse({'has_canvas': True, 'studio_id': r[0], 'post_id': r[3],
                                 'template_id': r[2], 'canvas_json': cj, 'is_video': is_video})
    return JsonResponse({'has_canvas': False, 'is_video': is_video})


# ─────────────────────────────────────────────
#  NEXTCLOUD FOLDERS FOR STUDIO
# ─────────────────────────────────────────────
NC_STUDIO_TEMPLATES_FOLDER = "Marketing & Design/LinkedIn/Studio/Templates"
NC_STUDIO_LIBRARY_FOLDER   = "Marketing & Design/LinkedIn/Studio/Bibliothek"
NC_STUDIO_VIDEOS_FOLDER    = "Marketing & Design/LinkedIn/Studio/Videos"


def _optimize_canvas_json(canvas_json_str, nc_folder, title_prefix):
    """Extract base64 images from canvas_json, upload to NC, replace with nc:// refs.
    Returns optimized JSON string."""
    import json as _json, base64, re as _re, time
    if not canvas_json_str:
        return canvas_json_str
    try:
        state = _json.loads(canvas_json_str)
        safe = _re.sub(r'[^a-zA-Z0-9_-]', '_', title_prefix)
        ts = int(time.time())

        snap = state.get('snapshotDataUrl', '')
        if snap and snap.startswith('data:image'):
            b64 = snap.split(',', 1)[1]
            img_bytes = base64.b64decode(b64)
            nc = _nc_upload(img_bytes, f"{nc_folder}/{safe}_{ts}_snap.png", 'image/png')
            if nc:
                state['snapshotDataUrl'] = f"nc://{nc}"

        # Preview (with all objects) for sidebar thumbnail
        preview = state.get('previewDataUrl', '')
        if preview and preview.startswith('data:image'):
            b64 = preview.split(',', 1)[1]
            img_bytes = base64.b64decode(b64)
            nc = _nc_upload(img_bytes, f"{nc_folder}/{safe}_{ts}_preview.png", 'image/png')
            if nc:
                state['previewDataUrl'] = f"nc://{nc}"

        for i, obj in enumerate(state.get('objects', [])):
            src = obj.get('imgSrc', '')
            if src and src.startswith('data:image'):
                try:
                    ext = 'png' if 'png' in src.split(';')[0] else 'jpg'
                    b64 = src.split(',', 1)[1]
                    img_bytes = base64.b64decode(b64)
                    nc = _nc_upload(img_bytes, f"{nc_folder}/{safe}_{ts}_obj{i}.{ext}", f"image/{ext}")
                    if nc:
                        obj['imgSrc'] = f"nc://{nc}"
                except Exception:
                    pass

        return _json.dumps(state)
    except Exception:
        return canvas_json_str


def _resolve_nc_refs_in_json(canvas_json_str):
    """Replace nc:// references and direct Nextcloud URLs in canvas_json
    with same-origin proxy URLs to avoid CORS tainting."""
    import json as _json
    if not canvas_json_str:
        return canvas_json_str
    try:
        from posts_posted.nc_storage import _get_nc_credentials
        nc_url, _, _ = _get_nc_credentials()
        nc_host = nc_url.rstrip('/') if nc_url else ''

        from urllib.parse import quote

        def _proxy(src):
            if not src:
                return src
            if src.startswith('nc://'):
                return f"/library/studio/nc-image/?p={quote(src[5:], safe='/')}"
            # Direct Nextcloud URLs → proxy
            if nc_host and src.startswith(nc_host):
                # Extract NC path from full URL
                import re
                m = re.search(r'/remote\.php/dav/files/[^/]+/(.+)', src)
                if m:
                    from urllib.parse import unquote
                    return f"/library/studio/nc-image/?p={unquote(m.group(1))}"
            return src

        state = _json.loads(canvas_json_str)
        state['snapshotDataUrl'] = _proxy(state.get('snapshotDataUrl', ''))
        if 'previewDataUrl' in state:
            state['previewDataUrl'] = _proxy(state.get('previewDataUrl', ''))
        for obj in state.get('objects', []):
            obj['imgSrc'] = _proxy(obj.get('imgSrc', ''))
        return _json.dumps(state)
    except Exception:
        return canvas_json_str


def _nc_ensure_folder(nc_url, username, password, folder_path):
    """Create Nextcloud folder (and parents) via MKCOL if it doesn't exist."""
    from urllib.parse import quote
    import requests as _req
    from requests.auth import HTTPBasicAuth
    parts = folder_path.strip('/').split('/')
    current = ''
    for part in parts:
        current = f"{current}/{part}" if current else part
        url = f"{nc_url.rstrip('/')}/remote.php/dav/files/{username}/{quote(current, safe='/')}"
        try:
            _req.request('MKCOL', url, auth=HTTPBasicAuth(username, password), timeout=15)
        except Exception:
            pass


def _nc_upload(content_bytes, nc_path, content_type='image/png'):
    """Upload raw bytes to Nextcloud. Returns nc_path on success, None on failure."""
    from posts_posted.nc_storage import _get_nc_credentials
    from urllib.parse import quote
    import requests as _req
    from requests.auth import HTTPBasicAuth
    nc_url, username, password = _get_nc_credentials()
    if not all([nc_url, username, password]):
        return None
    try:
        # Ensure parent folder exists
        folder = '/'.join(nc_path.split('/')[:-1])
        if folder:
            _nc_ensure_folder(nc_url, username, password, folder)
        upload_url = f"{nc_url.rstrip('/')}/remote.php/dav/files/{username}/{quote(nc_path, safe='/')}"
        r = _req.put(upload_url, data=content_bytes,
                     auth=HTTPBasicAuth(username, password),
                     headers={'Content-Type': content_type}, timeout=60)
        if r.status_code in [200, 201, 204]:
            return nc_path
        print(f"NC upload failed {r.status_code}: {nc_path}")
        return None
    except Exception as e:
        print("NC upload error:", e)
        return None


def _nc_download(nc_path):
    """Download from Nextcloud. Returns (bytes, content_type) or (None, None)."""
    from posts_posted.nc_storage import download_image_from_nextcloud
    return download_image_from_nextcloud(nc_path)


def _nc_delete(nc_path):
    from posts_posted.nc_storage import delete_image_from_nextcloud
    delete_image_from_nextcloud(nc_path)


def _ensure_brand_colors_table():
    with connection.cursor() as c:
        try:
            c.execute("""CREATE TABLE IF NOT EXISTS brand_colors (
                id   INT AUTO_INCREMENT PRIMARY KEY,
                c1   VARCHAR(20) DEFAULT '#ffffff',
                c2   VARCHAR(20) DEFAULT '#F56E28',
                c3   VARCHAR(20) DEFAULT '#008591',
                c4   VARCHAR(20) DEFAULT '#61CEBC',
                c5   VARCHAR(20) DEFAULT '#005F68',
                c6   VARCHAR(20) DEFAULT '#161616',
                extra_colors TEXT DEFAULT NULL
            )""")
        except Exception: pass
        # extra_colors Spalte nachrüsten falls Tabelle schon existiert
        try:
            c.execute("SHOW COLUMNS FROM brand_colors LIKE 'extra_colors'")
            if not c.fetchone():
                c.execute("ALTER TABLE brand_colors ADD COLUMN extra_colors TEXT DEFAULT NULL")
        except Exception: pass
        # Sicherstellen dass immer genau eine Zeile existiert
        try:
            c.execute("SELECT COUNT(*) FROM brand_colors")
            if c.fetchone()[0] == 0:
                c.execute("INSERT INTO brand_colors (c1,c2,c3,c4,c5,c6) VALUES ('#ffffff','#F56E28','#008591','#61CEBC','#005F68','#161616')")
        except Exception: pass


def get_brand_colors():
    """Gibt die aktuellen Brand-Farben als Dict zurück (inkl. extra_colors Liste)."""
    _ensure_brand_colors_table()
    defaults = {'c1':'#ffffff','c2':'#F56E28','c3':'#008591','c4':'#61CEBC','c5':'#005F68','c6':'#161616','extra_colors':[]}
    try:
        with connection.cursor() as c:
            c.execute("SELECT c1,c2,c3,c4,c5,c6,extra_colors FROM brand_colors LIMIT 1")
            row = c.fetchone()
            if row:
                d = dict(zip(['c1','c2','c3','c4','c5','c6','extra_colors'], row))
                try: d['extra_colors'] = json.loads(d['extra_colors']) if d['extra_colors'] else []
                except: d['extra_colors'] = []
                return d
    except Exception: pass
    return defaults


def _ensure_studio_tables():
    with connection.cursor() as c:
        try:
            c.execute("""CREATE TABLE IF NOT EXISTS studio_templates (
                id         INT AUTO_INCREMENT PRIMARY KEY,
                nc_path    VARCHAR(512) NOT NULL,
                title      VARCHAR(255) DEFAULT '',
                width      INT DEFAULT 1080,
                height     INT DEFAULT 1080,
                colors     VARCHAR(512) DEFAULT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""")
        except Exception: pass
        # Migration: add colors column if missing
        try:
            c.execute("ALTER TABLE studio_templates ADD COLUMN colors VARCHAR(512) DEFAULT NULL")
        except Exception: pass
        try:
            c.execute("""CREATE TABLE IF NOT EXISTS studio_images (
                id          INT AUTO_INCREMENT PRIMARY KEY,
                nc_path     VARCHAR(512) NOT NULL,
                title       VARCHAR(255) DEFAULT '',
                canvas_json LONGTEXT,
                template_id INT DEFAULT NULL,
                post_id     INT DEFAULT NULL,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""")
        except Exception: pass
        # Add post_id column if missing (existing tables)
        try:
            c.execute("ALTER TABLE studio_images ADD COLUMN post_id INT DEFAULT NULL")
        except Exception: pass
        # Upgrade canvas_json to LONGTEXT for large data-URL payloads
        try:
            c.execute("ALTER TABLE studio_images MODIFY COLUMN canvas_json LONGTEXT")
        except Exception: pass


# ─────────────────────────────────────────────
#  STUDIO VIEWS
# ─────────────────────────────────────────────

@login_required
@login_required
def studio_flowcharts_view(request):
    return render(request, 'media_library/flowcharts.html')


def studio_view(request):
    _ensure_studio_tables()
    post_id = request.GET.get('post_id', '')
    post_data = None
    if post_id:
        try:
            with connection.cursor() as c:
                rows = _safe(c, "SELECT id, title, image, content FROM planner_posts WHERE id=%s", [post_id])
                if rows:
                    r = rows[0]
                    post_data = {'id': r[0], 'title': r[1] or '', 'image': r[2] or '', 'content': (r[3] or '')[:120]}
                # Look up saved canvas_json for this post
                canvas_rows = _safe(c, "SELECT canvas_json, template_id FROM studio_images WHERE post_id=%s ORDER BY created_at DESC LIMIT 1", [post_id])
                if canvas_rows and canvas_rows[0][0] and post_data:
                    post_data['canvas_json'] = canvas_rows[0][0]
                    post_data['template_id'] = canvas_rows[0][1]
        except Exception as e:
            print("Studio post lookup error:", e)
    # Also support loading from a library item (studio_image_id)
    lib_item_id = request.GET.get('lib_item', '')
    lib_data = None
    if lib_item_id and not post_id:
        try:
            with connection.cursor() as c:
                rows = _safe(c, "SELECT nc_path FROM media_library_items WHERE id=%s", [lib_item_id])
                if rows:
                    nc_path = rows[0][0]
                    studio_rows = _safe(c, """SELECT canvas_json, template_id FROM studio_images
                                             WHERE nc_path=%s ORDER BY created_at DESC LIMIT 1""", [nc_path])
                    lib_data = {'item_id': lib_item_id, 'image_url': f"/library/image/{lib_item_id}/"}
                    if studio_rows and studio_rows[0][0]:
                        lib_data['canvas_json'] = studio_rows[0][0]
                        lib_data['template_id'] = studio_rows[0][1]
        except Exception as e:
            print("Studio lib lookup:", e)
    folders = _all_folders()
    # Pass Nextcloud base URL for draw.io embed
    try:
        from posts_posted.nc_storage import _get_nc_credentials
        nc_url_val, _, _ = _get_nc_credentials()
    except Exception:
        nc_url_val = ''
    brand = get_brand_colors()
    return render(request, 'media_library/studio.html', {
        'post_id': post_id, 'post_data': post_data, 'lib_data': lib_data,
        'folders': folders, 'nc_url': (nc_url_val or '').rstrip('/'),
        'brand_extra_colors_json': json.dumps(brand.get('extra_colors', []))})


@login_required
def studio_link_video(request):
    """
    Bridge: given a Nextcloud video path (Planner/Videos), find or create a
    media_library item for it and return its id, so the Planner post editor can
    open Studio for that video via /library/studio/?lib_item=<id>.
    """
    if request.method != 'POST':
        return JsonResponse({'ok': False}, status=405)

    try:
        data = json.loads(request.body or '{}')
    except Exception:
        data = {}
    nc_path = (data.get('video_nc_path') or '').strip()
    if not nc_path:
        return JsonResponse({'ok': False, 'error': 'video_nc_path fehlt'}, status=400)

    # Normalize bare filenames to the Planner/Videos folder.
    if not nc_path.startswith("Marketing"):
        filename = nc_path.split("/")[-1]
        nc_path = f"Marketing & Design/LinkedIn/Planner/Videos/{filename}"

    title = nc_path.split("/")[-1]
    with connection.cursor() as c:
        rows = _safe(c, "SELECT id FROM media_library_items WHERE nc_path=%s LIMIT 1", [nc_path])
        if rows:
            item_id = rows[0][0]
        else:
            c.execute(
                """INSERT INTO media_library_items (nc_path, title, person, series, tags, note, folder_id)
                   VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                [nc_path, title, '', '', '', None, None]
            )
            rows2 = _safe(c, "SELECT id FROM media_library_items WHERE nc_path=%s ORDER BY id DESC LIMIT 1", [nc_path])
            item_id = rows2[0][0] if rows2 else None

    if not item_id:
        return JsonResponse({'ok': False, 'error': 'Item konnte nicht angelegt werden'}, status=500)

    return JsonResponse({'ok': True, 'item_id': item_id,
                         'studio_url': f"/library/studio/?lib_item={item_id}"})


@login_required
def studio_templates_view(request):
    _ensure_studio_tables()
    with connection.cursor() as c:
        rows = _safe(c, "SELECT id, title, width, height, colors, created_at FROM studio_templates ORDER BY created_at DESC")
    templates = []
    for r in (rows or []):
        colors = []
        if r[4]:
            try: colors = json.loads(r[4])
            except: pass
        templates.append({'id': r[0], 'title': r[1], 'width': r[2], 'height': r[3], 'colors': colors,
                          'url': f"/library/studio/template/image/{r[0]}/"})
    brand = get_brand_colors()
    return render(request, 'media_library/studio_templates.html', {'templates': templates, 'brand': brand})


@login_required
def studio_brand_colors_save(request):
    """Speichert die 6 Brand-Farben in der DB."""
    if request.method != 'POST':
        return JsonResponse({'ok': False})
    _ensure_brand_colors_table()
    c1 = request.POST.get('c1', '#ffffff')
    c2 = request.POST.get('c2', '#F56E28')
    c3 = request.POST.get('c3', '#008591')
    c4 = request.POST.get('c4', '#61CEBC')
    c5 = request.POST.get('c5', '#005F68')
    c6 = request.POST.get('c6', '#161616')
    # Extra-Farben aus dem Formular sammeln
    extra = [v for k, v in request.POST.items() if k.startswith('extra_') and v.startswith('#')]
    extra_json = json.dumps(extra) if extra else None
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM brand_colors")
            if cur.fetchone()[0] > 0:
                cur.execute("UPDATE brand_colors SET c1=%s,c2=%s,c3=%s,c4=%s,c5=%s,c6=%s,extra_colors=%s", [c1,c2,c3,c4,c5,c6,extra_json])
            else:
                cur.execute("INSERT INTO brand_colors (c1,c2,c3,c4,c5,c6,extra_colors) VALUES (%s,%s,%s,%s,%s,%s,%s)", [c1,c2,c3,c4,c5,c6,extra_json])
        messages.success(request, 'Brand-Farben gespeichert.')
    except Exception as e:
        messages.error(request, f'Fehler: {e}')
    return redirect('/library/studio/templates/')


@login_required
def studio_template_upload(request):
    _ensure_studio_tables()
    if request.method != 'POST':
        return redirect('media_library:studio_templates')
    f = request.FILES.get('template')
    if not f:
        messages.error(request, 'Kein Template ausgewählt.')
        return redirect('media_library:studio_templates')
    title  = request.POST.get('title', '').strip() or f.name
    width  = int(request.POST.get('width', 1080) or 1080)
    height = int(request.POST.get('height', 1080) or 1080)
    import time
    filename = f"tpl_{int(time.time())}.png"
    content  = f.read()
    nc_path  = _nc_upload(content, f"{NC_STUDIO_TEMPLATES_FOLDER}/{filename}", 'image/png')
    if not nc_path:
        # local fallback
        from django.conf import settings as _s
        local_dir = os.path.join(_s.BASE_DIR, 'media', 'studio', 'templates')
        os.makedirs(local_dir, exist_ok=True)
        with open(os.path.join(local_dir, filename), 'wb') as fh:
            fh.write(content)
        nc_path = f"__local__/studio/templates/{filename}"
    # Collect up to 6 colors
    import json as _j
    colors = [request.POST.get(f'color{i}', '').strip() for i in range(1, 7)]
    colors = [c for c in colors if c]  # remove empty
    colors_json = _j.dumps(colors) if colors else None
    with connection.cursor() as c:
        c.execute("INSERT INTO studio_templates (nc_path, title, width, height, colors) VALUES (%s,%s,%s,%s,%s)",
                  [nc_path, title, width, height, colors_json])
    messages.success(request, 'Template gespeichert!')
    return redirect('media_library:studio_templates')


@login_required
def studio_template_colors(request, tpl_id):
    """Update the color palette of a template."""
    if request.method != 'POST':
        return redirect('media_library:studio_templates')
    import json as _j
    colors = [request.POST.get(f'color{i}', '').strip() for i in range(1, 7)]
    colors = [c for c in colors if c]
    with connection.cursor() as c:
        c.execute("UPDATE studio_templates SET colors=%s WHERE id=%s", [_j.dumps(colors), tpl_id])
    messages.success(request, 'Farben gespeichert!')
    return redirect('media_library:studio_templates')


@login_required
def studio_template_delete(request, tpl_id):
    if request.method != 'POST':
        return redirect('media_library:studio_templates')
    with connection.cursor() as c:
        rows = _safe(c, "SELECT nc_path FROM studio_templates WHERE id=%s", [tpl_id])
    if rows:
        _nc_delete(rows[0][0])
        with connection.cursor() as c:
            c.execute("DELETE FROM studio_templates WHERE id=%s", [tpl_id])
    messages.success(request, 'Template gelöscht.')
    return redirect('media_library:studio_templates')


@login_required
def studio_template_image(request, tpl_id):
    with connection.cursor() as c:
        rows = _safe(c, "SELECT nc_path FROM studio_templates WHERE id=%s", [tpl_id])
    if not rows:
        raise Http404
    nc_path = rows[0][0]
    if nc_path.startswith('__local__/'):
        from django.conf import settings as _s
        local_path = os.path.join(_s.BASE_DIR, 'media', nc_path[len('__local__/'):])
        if not os.path.exists(local_path):
            raise Http404
        with open(local_path, 'rb') as fh:
            content = fh.read()
        ct = 'image/png'
    else:
        content, ct = _nc_download(nc_path)
        if not content:
            raise Http404
    resp = HttpResponse(content, content_type=ct or 'image/png')
    resp['Cache-Control'] = 'public, max-age=3600'
    return resp


@login_required
def studio_save(request):
    """Save finished studio canvas as PNG → Nextcloud Studio/Bibliothek."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    _ensure_studio_tables()
    try:
        data = json.loads(request.body)
    except Exception:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    import base64, time
    data_url    = data.get('dataUrl', '')
    title       = data.get('title', f'Studio_{int(time.time())}')
    post_id     = data.get('post_id', '')
    canvas_json = data.get('canvasJson', '')
    template_id = data.get('templateId') or None
    folder_id   = data.get('folderId') or None

    if ',' in data_url:
        _, b64 = data_url.split(',', 1)
    else:
        b64 = data_url
    try:
        content = base64.b64decode(b64)
    except Exception:
        return JsonResponse({'error': 'Invalid image data'}, status=400)

    filename = f"studio_{int(time.time())}.png"
    nc_path  = _nc_upload(content, f"{NC_STUDIO_LIBRARY_FOLDER}/{filename}", 'image/png')
    if not nc_path:
        # local fallback
        from django.conf import settings as _s
        local_dir = os.path.join(_s.BASE_DIR, 'media', 'studio', 'bibliothek')
        os.makedirs(local_dir, exist_ok=True)
        with open(os.path.join(local_dir, filename), 'wb') as fh:
            fh.write(content)
        nc_path = f"__local__/studio/bibliothek/{filename}"

    # Save to media_library_items so it appears in Bibliothek tab
    with connection.cursor() as c:
        c.execute("""INSERT INTO media_library_items (nc_path, title, series, tags, folder_id)
                     VALUES (%s, %s, 'Studio', 'studio', %s)""", [nc_path, title, folder_id])
        lib_id = c.lastrowid

    # Optimize canvas_json: upload base64 images to NC
    if canvas_json:
        canvas_json = _optimize_canvas_json(canvas_json, NC_STUDIO_LIBRARY_FOLDER, title)

    # Save studio metadata (upsert per post_id if given)
    studio_image_id = None
    with connection.cursor() as c:
        if post_id:
            rows = _safe(c, "SELECT id FROM studio_images WHERE post_id=%s ORDER BY created_at DESC LIMIT 1", [post_id])
            if rows:
                studio_image_id = rows[0][0]
                c.execute("""UPDATE studio_images SET nc_path=%s, title=%s, canvas_json=%s, template_id=%s
                             WHERE id=%s""", [nc_path, title, canvas_json or None, template_id, studio_image_id])
            else:
                c.execute("""INSERT INTO studio_images (nc_path, title, canvas_json, template_id, post_id)
                             VALUES (%s,%s,%s,%s,%s)""", [nc_path, title, canvas_json or None, template_id, post_id])
                studio_image_id = c.lastrowid
        else:
            c.execute("""INSERT INTO studio_images (nc_path, title, canvas_json, template_id)
                         VALUES (%s,%s,%s,%s)""", [nc_path, title, canvas_json or None, template_id])
            studio_image_id = c.lastrowid

    # Attach to planner post if post_id given
    if post_id:
        try:
            with connection.cursor() as c:
                c.execute("UPDATE planner_posts SET image=%s WHERE id=%s", [nc_path, post_id])
        except Exception as e:
            print("Post attach error:", e)

    image_url = f"/library/image/{lib_id}/"
    return JsonResponse({'ok': True, 'lib_id': lib_id, 'image_url': image_url, 'nc_path': nc_path})


@login_required
def studio_save_video(request):
    """Save recorded studio video (WebM) → Nextcloud Videos folder."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    import time
    _ensure_studio_tables()
    video_file = request.FILES.get('video')
    title = request.POST.get('title', f'Studio_Video_{int(time.time())}')
    folder_id = request.POST.get('folder_id') or None
    if folder_id:
        try: folder_id = int(folder_id)
        except: folder_id = None
    if not video_file:
        return JsonResponse({'error': 'No video file'}, status=400)
    content = video_file.read()
    filename = title.replace(' ', '_') + f"_{int(time.time())}.webm"
    import re
    filename = re.sub(r'[^a-zA-Z0-9_.-]', '', filename)
    nc_path = _nc_upload(content, f"{NC_STUDIO_VIDEOS_FOLDER}/{filename}", 'video/webm')
    if not nc_path:
        from django.conf import settings as _s
        local_dir = os.path.join(_s.BASE_DIR, 'media', 'studio', 'videos')
        os.makedirs(local_dir, exist_ok=True)
        with open(os.path.join(local_dir, filename), 'wb') as fh:
            fh.write(content)
        nc_path = f"__local__/studio/videos/{filename}"
    # Save to media_library_items so it appears in Bibliothek
    with connection.cursor() as c:
        c.execute("""INSERT INTO media_library_items (nc_path, title, series, tags, folder_id)
                     VALUES (%s, %s, 'Studio', 'video', %s)""", [nc_path, title, folder_id])
        lib_id = c.lastrowid
    # Save canvas state so video can be reopened for editing
    canvas_json = request.POST.get('canvas_json', '')
    if canvas_json:
        canvas_json = _optimize_canvas_json(canvas_json, NC_STUDIO_VIDEOS_FOLDER, title)
        with connection.cursor() as c:
            c.execute("""INSERT INTO studio_images (nc_path, title, canvas_json)
                         VALUES (%s, %s, %s)""", [nc_path, title, canvas_json])
    return JsonResponse({'ok': True, 'nc_path': nc_path, 'filename': filename, 'lib_id': lib_id})


@login_required
def studio_api_templates(request):
    _ensure_studio_tables()
    with connection.cursor() as c:
        rows = _safe(c, "SELECT id, title, width, height, colors FROM studio_templates ORDER BY created_at DESC")
    data = []
    for r in (rows or []):
        colors = []
        if r[4]:
            try:
                import json as _j; colors = _j.loads(r[4])
            except Exception: pass
        data.append({'id': r[0], 'title': r[1] or '', 'width': r[2], 'height': r[3],
                     'url': f"/library/studio/template/image/{r[0]}/", 'colors': colors})
    return JsonResponse({'templates': data})


NC_STUDIO_VIDEO_TEMPLATES_FOLDER = "Marketing & Design/LinkedIn/Studio/VideoVorlagen"


def _ensure_video_template_table():
    with connection.cursor() as c:
        try:
            c.execute("""CREATE TABLE IF NOT EXISTS studio_video_templates (
                id              INT AUTO_INCREMENT PRIMARY KEY,
                title           VARCHAR(255) DEFAULT '',
                canvas_json     LONGTEXT NOT NULL,
                preview_nc_path VARCHAR(512) DEFAULT NULL,
                preview_data    LONGTEXT DEFAULT NULL,
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""")
        except Exception: pass
        # Add preview_data column if it doesn't exist yet (migration)
        try:
            c.execute("ALTER TABLE studio_video_templates ADD COLUMN preview_data LONGTEXT DEFAULT NULL")
        except Exception: pass


@login_required
def studio_video_template_save(request):
    """Save current canvas state as a video template.
    Uses _optimize_canvas_json to upload base64 images to NC and replace with nc:// refs."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    _ensure_video_template_table()
    import time, json as _json
    title = request.POST.get('title', f'Video-Vorlage {int(time.time())}')
    canvas_json = request.POST.get('canvas_json', '')
    if not canvas_json:
        return JsonResponse({'error': 'Kein canvas_json'}, status=400)

    # Upload base64 images to NC, replace with nc:// references
    canvas_json = _optimize_canvas_json(canvas_json, NC_STUDIO_VIDEO_TEMPLATES_FOLDER, title)

    # Extract preview NC path from optimized JSON (prefer previewDataUrl over snapshotDataUrl)
    preview_nc_path = None
    preview_data = None
    try:
        state = _json.loads(canvas_json)
        prev = state.get('previewDataUrl', '') or state.get('snapshotDataUrl', '')
        if prev and prev.startswith('nc://'):
            preview_nc_path = prev[5:]
            preview_data = prev
    except Exception:
        pass

    with connection.cursor() as c:
        existing = _safe(c, "SELECT id FROM studio_video_templates WHERE title=%s LIMIT 1", [title])
        if existing:
            tpl_id = existing[0][0]
            c.execute("""UPDATE studio_video_templates
                         SET canvas_json=%s, preview_nc_path=%s, preview_data=%s
                         WHERE id=%s""", [canvas_json, preview_nc_path, preview_data, tpl_id])
        else:
            c.execute("""INSERT INTO studio_video_templates (title, canvas_json, preview_nc_path, preview_data)
                         VALUES (%s, %s, %s, %s)""", [title, canvas_json, preview_nc_path, preview_data])
            tpl_id = c.lastrowid
    return JsonResponse({'ok': True, 'id': tpl_id, 'preview_nc_path': preview_nc_path})


@login_required
def studio_video_template_list(request):
    _ensure_video_template_table()
    with connection.cursor() as c:
        # De-duplicate: keep only the latest entry per title
        try:
            c.execute("""DELETE FROM studio_video_templates
                         WHERE id NOT IN (
                           SELECT id FROM (
                             SELECT MAX(id) as id FROM studio_video_templates GROUP BY title
                           ) t
                         )""")
        except Exception: pass
        # Try with preview_data column; fall back to 4-col query if column missing
        try:
            c.execute("SELECT id, title, preview_nc_path, created_at, preview_data FROM studio_video_templates ORDER BY created_at DESC")
            rows = c.fetchall()
        except Exception:
            try:
                c.execute("SELECT id, title, preview_nc_path, created_at FROM studio_video_templates ORDER BY created_at DESC")
                rows = [list(r) + [None] for r in c.fetchall()]
            except Exception:
                rows = []
    data = []
    for r in (rows or []):
        preview_data = r[4] if len(r) > 4 else None
        if preview_data and preview_data.startswith('nc://'):
            from urllib.parse import quote as _q
            preview_url = f"/library/studio/nc-image/?p={_q(preview_data[5:], safe='/')}"
        elif preview_data and preview_data.startswith('data:image'):
            preview_url = preview_data
        else:
            preview_url = f"/library/studio/video-template/preview/{r[0]}/"
        data.append({'id': r[0], 'title': r[1] or '', 'preview_url': preview_url})
    return JsonResponse({'templates': data})


@login_required
def studio_video_template_load(request, tpl_id):
    _ensure_video_template_table()
    with connection.cursor() as c:
        rows = _safe(c, "SELECT title, canvas_json FROM studio_video_templates WHERE id=%s", [tpl_id])
    if not rows:
        raise Http404
    canvas_json = _resolve_nc_refs_in_json(rows[0][1])
    return JsonResponse({'ok': True, 'title': rows[0][0], 'canvas_json': canvas_json})


@login_required
def studio_nc_image_proxy(request):
    """Proxy Nextcloud images through Django so they're same-origin (no CORS tainting)."""
    nc_path = request.GET.get('p', '')
    if not nc_path:
        raise Http404
    from posts_posted.nc_storage import download_image_from_nextcloud
    content, ct = download_image_from_nextcloud(nc_path)
    if not content:
        raise Http404
    resp = HttpResponse(content, content_type=ct or 'image/png')
    resp['Cache-Control'] = 'public, max-age=3600'
    return resp


@login_required
def studio_video_template_delete(request, tpl_id):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    _ensure_video_template_table()
    with connection.cursor() as c:
        c.execute("DELETE FROM studio_video_templates WHERE id=%s", [tpl_id])
    return JsonResponse({'ok': True})


@login_required
def studio_video_template_preview(request, tpl_id):
    _ensure_video_template_table()
    with connection.cursor() as c:
        rows = _safe(c, "SELECT preview_nc_path FROM studio_video_templates WHERE id=%s", [tpl_id])
    if not rows or not rows[0][0]:
        raise Http404
    nc_path = rows[0][0]
    if nc_path.startswith('__local__/'):
        from django.conf import settings as _s
        rel = nc_path[len('__local__/'):]
        local_path = os.path.join(_s.BASE_DIR, 'media', rel)
        if not os.path.exists(local_path):
            raise Http404
        with open(local_path, 'rb') as f:
            content = f.read()
        return HttpResponse(content, content_type='image/png')
    from posts_posted.nc_storage import download_image_from_nextcloud
    content, ct = download_image_from_nextcloud(nc_path)
    if not content:
        raise Http404
    return HttpResponse(content, content_type='image/png')


@login_required
def studio_api_saved(request):
    """Return only items saved via Studio (images with tags='studio', videos with tags='video').
    Images with animations in their canvas_json are excluded (they live in studio_video_templates).
    """
    import json as _json
    _ensure_table()
    _ensure_studio_tables()
    with connection.cursor() as c:
        # Load studio images together with their canvas_json to check for animations
        img_rows = _safe(c, """SELECT m.id, m.title, m.nc_path,
                                      si.canvas_json
                               FROM media_library_items m
                               LEFT JOIN studio_images si
                                 ON si.nc_path = m.nc_path
                                 AND si.id = (SELECT MAX(s2.id) FROM studio_images s2 WHERE s2.nc_path = m.nc_path)
                               WHERE m.tags='studio' ORDER BY m.id DESC""")
        vid_rows = _safe(c, """SELECT m.id, m.title, m.nc_path,
                                      (SELECT COUNT(*) FROM studio_images s WHERE s.nc_path=m.nc_path AND s.canvas_json IS NOT NULL) as has_canvas
                               FROM media_library_items m
                               WHERE m.tags='video' ORDER BY m.id DESC""")

    def _has_anim(canvas_json_str):
        """Return True if any object in canvas_json has an animation set."""
        if not canvas_json_str:
            return False
        try:
            state = _json.loads(canvas_json_str)
            return any(o.get('animType') and o.get('animType') != 'none'
                       for o in (state.get('objects') or []))
        except Exception:
            return False

    # Nicht-animierte Studio-Bilder → Bilder-Sektion
    images = [{'id': r[0], 'title': r[1] or '', 'url': f"/library/image/{r[0]}/"}
              for r in (img_rows or []) if not _has_anim(r[3])]
    # Animierte Studio-Bilder → Video-Bilder-Sektion (legacy, vor neuem System)
    anim_images = [{'id': r[0], 'title': r[1] or '', 'url': f"/library/image/{r[0]}/",
                    'lib_item_id': r[0]}
                   for r in (img_rows or []) if _has_anim(r[3])]
    videos = [{'id': r[0], 'title': r[1] or '', 'url': f"/library/image/{r[0]}/", 'has_canvas': bool(r[3])}
              for r in (vid_rows or [])]
    return JsonResponse({'images': images, 'videos': videos, 'anim_images': anim_images})


@login_required
def studio_api_library(request):
    """Return library images + folders for studio sidebar."""
    _ensure_table()
    filters = {'q': request.GET.get('q', '')}
    folder_param = request.GET.get('folder', '')
    if folder_param and folder_param != 'all':
        if folder_param == 'none':
            filters['folder'] = 'none'
        else:
            filters['folder_id'] = folder_param
    items = _all_items(filters)
    folders = _all_folders()
    # Studio-generierte Bilder/Videos aus Bibliotheks-Seitenleiste ausblenden
    STUDIO_TAGS = {'studio', 'video', 'video-bild'}
    def _is_studio(item):
        tags = {t.strip().lower() for t in (item.get('tags') or '').split(',') if t.strip()}
        return bool(tags & STUDIO_TAGS)
    items = [i for i in items if not _is_studio(i)]

    data = [{'id': i['id'], 'title': i['title'], 'url': f"/library/image/{i['id']}/"} for i in items]
    return JsonResponse({'items': data, 'folders': [{'id': f['id'], 'name': f['name']} for f in folders]})


@login_required
def studio_api_post_image(request, post_id):
    """Return post image as proxy (same as planner_image but within studio URL namespace)."""
    from django.http import Http404
    from posts_posted.nc_storage import download_image_from_nextcloud
    with connection.cursor() as c:
        rows = _safe(c, "SELECT image FROM planner_posts WHERE id=%s", [post_id])
    if not rows or not rows[0][0]:
        raise Http404
    nc_path = rows[0][0]
    if not nc_path.startswith('Marketing') and not nc_path.startswith('__local__'):
        filename = nc_path.split('/')[-1]
        nc_path = f"Marketing & Design/LinkedIn/Planner/Images/{filename}"
    content, ct = download_image_from_nextcloud(nc_path)
    if not content:
        raise Http404
    resp = HttpResponse(content, content_type=ct or 'image/jpeg')
    resp['Cache-Control'] = 'no-cache'
    return resp


NC_STUDIO_DIAGRAMS_FOLDER = "Marketing & Design/LinkedIn/Studio/Diagramme"


@login_required
def studio_drawio_save(request):
    """Receive a draw.io PNG export (base64 or file) and save to Nextcloud Studio/Diagramme."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    import time, base64 as _b64, re as _re
    _ensure_table()

    title = request.POST.get('title', f'Diagramm_{int(time.time())}')
    folder_id = request.POST.get('folder_id') or None
    if folder_id:
        try: folder_id = int(folder_id)
        except: folder_id = None

    # Accept either uploaded file or base64 data URL
    img_bytes = None
    if request.FILES.get('file'):
        img_bytes = request.FILES['file'].read()
    else:
        data_url = request.POST.get('data_url', '')
        if data_url and 'base64,' in data_url:
            img_bytes = _b64.b64decode(data_url.split('base64,', 1)[1])

    if not img_bytes:
        return JsonResponse({'error': 'Kein Bild erhalten'}, status=400)

    safe_title = _re.sub(r'[^a-zA-Z0-9_-]', '_', title)
    filename = f"{safe_title}_{int(time.time())}.png"
    nc_path = _nc_upload(img_bytes, f"{NC_STUDIO_DIAGRAMS_FOLDER}/{filename}", 'image/png')

    if not nc_path:
        # Local fallback
        from django.conf import settings as _s
        local_dir = os.path.join(_s.BASE_DIR, 'media', 'studio', 'diagramme')
        os.makedirs(local_dir, exist_ok=True)
        with open(os.path.join(local_dir, filename), 'wb') as fh:
            fh.write(img_bytes)
        nc_path = f"__local__/studio/diagramme/{filename}"

    with connection.cursor() as c:
        c.execute("""INSERT INTO media_library_items (nc_path, title, series, tags, folder_id)
                     VALUES (%s, %s, 'Studio', 'diagramm', %s)""", [nc_path, title, folder_id])
        lib_id = c.lastrowid

    return JsonResponse({'ok': True, 'nc_path': nc_path, 'lib_id': lib_id,
                         'url': f"/library/image/{lib_id}/"})


# ── Shared Assets (geteilter NC-Ordner für Bilderpool) ──

NC_SHARED_ASSETS_FOLDER = "Marketing & Design/Bilder_Bibliothek"


@login_required
def studio_shared_assets_list(request):
    """List images from the shared NC folder via WebDAV PROPFIND (recursive)."""
    from posts_posted.nc_storage import _get_nc_credentials
    from urllib.parse import quote, unquote
    import xml.etree.ElementTree as ET

    nc_url, username, password = _get_nc_credentials()
    if not all([nc_url, username, password]):
        return JsonResponse({'error': 'Nextcloud nicht konfiguriert'}, status=500)

    # Ensure folder exists
    _nc_ensure_folder(nc_url, username, password, NC_SHARED_ASSETS_FOLDER)

    q = (request.GET.get('q') or '').strip().lower()

    propfind_url = "{}/remote.php/dav/files/{}/{}".format(
        nc_url.rstrip('/'), username, quote(NC_SHARED_ASSETS_FOLDER, safe='/')
    )
    # Depth: infinity to include subfolders
    try:
        import requests as _req
        from requests.auth import HTTPBasicAuth
        r = _req.request('PROPFIND', propfind_url,
                         auth=HTTPBasicAuth(username, password),
                         headers={'Depth': 'infinity', 'Content-Type': 'application/xml'},
                         timeout=30)
        if r.status_code == 507:
            # Some NC servers reject infinity, fall back to Depth:1
            r = _req.request('PROPFIND', propfind_url,
                             auth=HTTPBasicAuth(username, password),
                             headers={'Depth': '1', 'Content-Type': 'application/xml'},
                             timeout=30)
        if r.status_code not in [200, 207]:
            return JsonResponse({'items': [], 'error': f'NC {r.status_code}'})
    except Exception as e:
        return JsonResponse({'items': [], 'error': str(e)})

    items = []
    IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg'}
    # Build the base path prefix to strip from hrefs
    base_prefix = f"/remote.php/dav/files/{username}/"
    try:
        root = ET.fromstring(r.text)
        ns = {'d': 'DAV:'}
        for resp_el in root.findall('.//d:response', ns):
            href = resp_el.findtext('d:href', '', ns)
            decoded = unquote(href)
            # Skip folders (end with /)
            if decoded.endswith('/'):
                continue
            filename = decoded.split('/')[-1]
            ext = os.path.splitext(filename)[1].lower()
            if ext not in IMAGE_EXTS:
                continue
            # Search filter
            if q and q not in filename.lower():
                continue
            # Extract full NC path from href
            bp = decoded.find(base_prefix)
            if bp >= 0:
                nc_path = decoded[bp + len(base_prefix):]
            else:
                nc_path = f"{NC_SHARED_ASSETS_FOLDER}/{filename}"
            proxy_url = f"/library/studio/nc-image/?p={quote(nc_path, safe='/')}"
            # Subfolder label
            rel = nc_path[len(NC_SHARED_ASSETS_FOLDER):].lstrip('/')
            items.append({'name': filename, 'url': proxy_url, 'nc_path': nc_path, 'path': rel})
    except Exception as e:
        return JsonResponse({'items': [], 'error': f'XML parse: {e}'})

    return JsonResponse({'items': items})


@login_required
def studio_shared_assets_upload(request):
    """Upload an image to the shared NC assets folder."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    from posts_posted.nc_storage import _get_nc_credentials
    from urllib.parse import quote
    import requests as _req
    from requests.auth import HTTPBasicAuth

    nc_url, username, password = _get_nc_credentials()
    if not all([nc_url, username, password]):
        return JsonResponse({'error': 'Nextcloud nicht konfiguriert'}, status=500)

    f = request.FILES.get('file')
    if not f:
        return JsonResponse({'error': 'Keine Datei'}, status=400)

    filename = f.name.replace(' ', '_')
    _nc_ensure_folder(nc_url, username, password, NC_SHARED_ASSETS_FOLDER)

    nc_path = f"{NC_SHARED_ASSETS_FOLDER}/{filename}"
    upload_url = "{}/remote.php/dav/files/{}/{}".format(
        nc_url.rstrip('/'), username, quote(nc_path, safe='/')
    )
    try:
        content = f.read()
        r = _req.put(upload_url, data=content,
                     auth=HTTPBasicAuth(username, password),
                     headers={'Content-Type': f.content_type or 'image/png'},
                     timeout=60)
        if r.status_code not in [200, 201, 204]:
            return JsonResponse({'error': f'Upload fehlgeschlagen: {r.status_code}'}, status=500)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

    proxy_url = f"/library/studio/nc-image/?p={quote(nc_path, safe='/')}"
    return JsonResponse({'ok': True, 'name': filename, 'url': proxy_url, 'nc_path': nc_path})


@login_required
def studio_shared_assets_delete(request):
    """Delete an image from the shared NC assets folder."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    nc_path = request.POST.get('nc_path', '')
    if not nc_path or not nc_path.startswith(NC_SHARED_ASSETS_FOLDER):
        return JsonResponse({'error': 'Ungültiger Pfad'}, status=400)
    from posts_posted.nc_storage import delete_image_from_nextcloud
    ok = delete_image_from_nextcloud(nc_path)
    return JsonResponse({'ok': ok})
