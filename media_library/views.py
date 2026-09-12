import functools
import os
import json
import tempfile
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.http import (JsonResponse, HttpResponse, Http404,
                         StreamingHttpResponse, FileResponse)
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


# ── Schema upkeep: once per process, not on every call ──────────────────────
_SCHEMA_GEPRUEFT = set()


def einmal_pro_prozess(f):
    """Lets a schema-upkeep function do its work on the first call only.

    These functions create missing tables and columns. Until now they ran on
    EVERY page load - the four of them called from 29 places across this file -
    each time with CREATE TABLE IF NOT EXISTS and a row of ALTER attempts that
    MySQL answers with an error which an except swallows. That costs time on
    every call and lets real schema problems disappear into the noise.
    im Rauschen untergehen.

    Once per worker process is enough: after a deploy the processes restart, so
    a new column is still added on the first call.

    If the function throws (database out of reach just now), NOTHING is
    remembered - the next call tries again.
    """
    @functools.wraps(f)
    def huelle(*args, **kwargs):
        if f.__name__ in _SCHEMA_GEPRUEFT:
            return None
        ergebnis = f(*args, **kwargs)
        _SCHEMA_GEPRUEFT.add(f.__name__)
        return ergebnis
    huelle.ungepuffert = f       # fuer Tests und den Notfall
    return huelle


@einmal_pro_prozess
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
    """The old database media library is gone (images live in Nextcloud under
    Studio_Work). This route stays only as a redirect, so internal
    redirect('media_library:library') calls keep working."""
    return redirect('media_library:studio')


@login_required
def library_upload(request):
    _ensure_table()
    if request.method != 'POST':
        return redirect('media_library:library')
    image = request.FILES.get('image')
    if not image:
        messages.error(request, 'No image selected.')
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
    messages.success(request, 'Image saved!')
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
        resp['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        return resp
    from posts_posted.nc_storage import download_image_from_nextcloud
    content, ct = download_image_from_nextcloud(nc_path)
    if not content:
        raise Http404
    resp = HttpResponse(content, content_type=ct or 'image/jpeg')
    resp['Cache-Control'] = 'no-cache, no-store, must-revalidate'
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
    messages.success(request, 'Saved!')
    return redirect('media_library:library')


@login_required
def library_delete(request, item_id):
    if request.method != 'POST':
        return redirect('media_library:library')
    with connection.cursor() as c:
        rows = _safe(c, "SELECT nc_path FROM media_library_items WHERE id=%s", [item_id])
    ajax = (request.headers.get('X-Requested-With') == 'XMLHttpRequest'
            or 'fetch' in request.headers.get('Sec-Fetch-Mode', ''))
    if rows:
        nc_path = rows[0][0]
        # The file first, then the database row - and only carry on once the file
        # really is gone. This used to delete without looking and then report
        # "Image deleted." unconditionally: the entry vanished from the library,
        # the file stayed in Nextcloud, and nobody could reach it through the app
        # any more.
        ok, grund = _nc_delete_detail(nc_path)
        if not ok:
            if ajax:
                return JsonResponse({'ok': False, 'error': grund or 'Deletion failed'}, status=502)
            messages.error(request, grund or 'The image could not be deleted.')
            return redirect('media_library:library')
        with connection.cursor() as c:
            c.execute("DELETE FROM media_library_items WHERE id=%s", [item_id])
            # Clean up linked studio data
            try: c.execute("DELETE FROM studio_images WHERE nc_path=%s", [nc_path])
            except Exception: pass
            try: c.execute("DELETE FROM studio_video_templates WHERE preview_nc_path=%s", [nc_path])
            except Exception: pass
    # AJAX request → JSON response
    if ajax:
        return JsonResponse({'ok': True})
    messages.success(request, 'Image deleted.')
    return redirect('media_library:library')


@login_required
def library_api(request):
    """JSON API for the picker in the edit-post modal."""
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
        is_gif = nc_path.lower().endswith('.gif')
        studio_rows = _safe(c, """SELECT id, canvas_json, template_id, post_id
                                  FROM studio_images WHERE nc_path=%s
                                  ORDER BY created_at DESC LIMIT 1""", [nc_path])
        if studio_rows and studio_rows[0][1]:
            r = studio_rows[0]
            cj = _resolve_nc_refs_in_json(r[1])
            return JsonResponse({'has_canvas': True, 'studio_id': r[0], 'post_id': r[3],
                                 'template_id': r[2], 'canvas_json': cj, 'is_video': is_video, 'is_gif': is_gif})
    return JsonResponse({'has_canvas': False, 'is_video': is_video, 'is_gif': is_gif})


# ─────────────────────────────────────────────
#  NEXTCLOUD FOLDERS FOR STUDIO
# ─────────────────────────────────────────────
NC_STUDIO_TEMPLATES_FOLDER = "Marketing & Design/LinkedIn/Studio/Templates"
NC_STUDIO_LIBRARY_FOLDER   = "Marketing & Design/Octotrial_Assets/Studio_Work/Output/Images"
NC_STUDIO_VIDEOS_FOLDER    = "Marketing & Design/Octotrial_Assets/Studio_Work/Output/Videos"
NC_STUDIO_GIFS_FOLDER      = "Marketing & Design/Octotrial_Assets/Studio_Work/Output/GIFs"

# One central definition of the app's own storage roots. Deleting is allowed
# only inside these (protection against path traversal and deleting other
# people's files). One source of truth instead of folder lists scattered through
# individual views. "Marketing & Design" is the brand folder that holds ALL the
# app's media (Octotrial_Assets, LinkedIn/Planner, Bilder_Bibliothek …).
NC_APP_ROOTS = (
    "Marketing & Design/",   # gesamter Marken-Ordner (alle App-Medien)
    "__local__/",            # lokaler Fallback (kein Nextcloud)
)


def _within_app_folders(nc_path):
    """True when the path belongs to one of the app's own folders (deletable).

    Traversal is checked segment by segment: only a path part that is exactly
    ".." is forbidden. A file name such as "foo..png" (two dots) is harmless and
    must NOT be mistaken for traversal.
    """
    if not nc_path:
        return False
    if any(seg == '..' for seg in nc_path.split('/')):
        return False
    return any(nc_path.startswith(r) for r in NC_APP_ROOTS)


def _post_media_to_cleanup(post_id):
    """Remember a post's current media paths (image/GIF/video) so they can be
    deleted later when replaced. Published posts are spared (empty list)."""
    try:
        with connection.cursor() as c:
            try:
                c.execute("""SELECT COALESCE(image,''), COALESCE(gif_nc_path,''),
                                    COALESCE(video_nc_path,''), COALESCE(status,'')
                             FROM planner_posts WHERE id=%s""", [post_id])
            except Exception:
                c.execute("SELECT COALESCE(image,''),'',COALESCE(video_nc_path,''),COALESCE(status,'') FROM planner_posts WHERE id=%s", [post_id])
            row = c.fetchone()
        if not row or (row[3] or '').lower() == 'posted':
            return []
        return [p for p in (row[0], row[1], row[2]) if p]
    except Exception as e:
        print("post media cleanup read:", e)
        return []


def _cleanup_old_media(paths, keep=None):
    """Delete old media files in Nextcloud (best effort), except `keep`."""
    if not paths:
        return
    for p in paths:
        if p and p != keep:
            _nc_delete_aufraeumen(p, 'ersetzte Post-Medien')


def _nc_delete_old_files(nc_folder, safe_prefix):
    """Delete old timestamp-based files for this title prefix from NC.
    Removes files matching pattern: {safe_prefix}_\d+_(preview|snap|obj).* """
    import re as _re
    try:
        from posts_posted.nc_storage import _get_nc_credentials
        nc_url, username, password = _get_nc_credentials()
        if not all([nc_url, username, password]):
            return
        from requests.auth import HTTPBasicAuth
        from urllib.parse import quote, unquote
        from xml.etree import ElementTree
        auth = HTTPBasicAuth(username, password)
        base = f"{nc_url.rstrip('/')}/remote.php/dav/files/{username}"
        # \d+ directly after the prefix also matched other titles: for "Header"
        # it matched "Header_2_preview.png" - the file of the output "Header 2".
        # Its preview was deleted along with every save of "Header". The
        # timestamp always has at least 10 digits, a title suffix never does.
        pattern = _re.compile(rf'^{_re.escape(safe_prefix)}_\d{{10,}}_(preview|snap|obj|fab)')
        for folder in [nc_folder, f"{nc_folder}/_data"]:
            url = f"{base}/{quote(folder, safe='/')}"
            try:
                r = requests.request("PROPFIND", url, auth=auth,
                    headers={"Depth": "1", "Content-Type": "application/xml"}, timeout=15)
                if r.status_code not in (207, 200):
                    continue
                ns = {"d": "DAV:"}
                tree = ElementTree.fromstring(r.content)
                base_href = f"/remote.php/dav/files/{username}/{quote(folder, safe='/')}"
                for resp in tree.findall("d:response", ns):
                    href = resp.findtext("d:href", "", ns)
                    if href.rstrip("/") == base_href.rstrip("/"):
                        continue
                    filename = unquote(href.rstrip("/").split("/")[-1])
                    if pattern.match(filename):
                        del_url = f"{base}/{quote(folder, safe='/')}/{quote(filename, safe='')}"
                        requests.delete(del_url, auth=auth, timeout=10)
            except Exception:
                pass
    except Exception:
        pass


def _optimize_canvas_json(canvas_json_str, nc_folder, title_prefix):
    """Extract base64 images from canvas_json, upload to NC, replace with nc:// refs.
    Internal images (snap, objects) go to _data/ subfolder to keep main folder clean.
    Only the preview stays in the main folder.
    Returns optimized JSON string."""
    import json as _json, base64, re as _re
    if not canvas_json_str:
        return canvas_json_str
    try:
        state = _json.loads(canvas_json_str)
        safe = _re.sub(r'[^a-zA-Z0-9_-]', '_', title_prefix)
        data_folder = f"{nc_folder}/_data"

        # Delete the old timestamped files for this title
        _nc_delete_old_files(nc_folder, safe)

        # Delete existing nc:// refs (they are replaced by new ones)
        old_refs = []
        for key in ('snapshotDataUrl', 'previewDataUrl'):
            v = state.get(key, '')
            if v and v.startswith('nc://'):
                old_refs.append(v[5:])
        for obj in state.get('objects', []):
            src = obj.get('imgSrc', '')
            if src and src.startswith('nc://'):
                old_refs.append(src[5:])
        # Delete the old nc:// files
        if old_refs:
            for ref in old_refs:
                _nc_delete_aufraeumen(ref, 'alte nc://-Objektbilder')

        snap = state.get('snapshotDataUrl', '')
        if snap and snap.startswith('data:image'):
            b64 = snap.split(',', 1)[1]
            img_bytes = base64.b64decode(b64)
            nc = _nc_upload(img_bytes, f"{data_folder}/{safe}_snap.png", 'image/png')
            if nc:
                state['snapshotDataUrl'] = f"nc://{nc}"

        # Preview — stays in main folder
        preview = state.get('previewDataUrl', '')
        if preview and preview.startswith('data:image'):
            b64 = preview.split(',', 1)[1]
            img_bytes = base64.b64decode(b64)
            nc = _nc_upload(img_bytes, f"{nc_folder}/{safe}_preview.png", 'image/png')
            if nc:
                state['previewDataUrl'] = f"nc://{nc}"

        for i, obj in enumerate(state.get('objects', [])):
            src = obj.get('imgSrc', '')
            if src and src.startswith('data:image'):
                try:
                    ext = 'png' if 'png' in src.split(';')[0] else 'jpg'
                    b64 = src.split(',', 1)[1]
                    img_bytes = base64.b64decode(b64)
                    nc = _nc_upload(img_bytes, f"{data_folder}/{safe}_obj{i}.{ext}", f"image/{ext}")
                    if nc:
                        obj['imgSrc'] = f"nc://{nc}"
                except Exception:
                    pass

        # In the v2 format the actual image data is NOT in state['objects']
        # (that is only a flat metadata list with proxy URLs) but in
        # state['fabric']['objects'][i]['src']. Without this loop the whole
        # offloading came to nothing: every cut-out or recoloured image stayed
        # in the canvas_json as several MB of base64. On larger designs that
        # burst the database's packet limit - and that is exactly when the
        # silent except branches around saving took over.
        import hashlib as _hl

        def _fab_auslagern(src, marke):
            """Uploads a data: image to Nextcloud and returns the nc:// reference.

            The file name carries a content hash rather than just title and
            position. With title plus index alone, two designs of the same name
            (or the same layout after a reorder) would have written to the same
            path by WebDAV PUT - and an older design would quietly have shown a
            stranger's image afterwards.

            Deliberately NO cleaning up here: deleting old files would only be
            safe if one knew every design still in existence. The client sends an
            unchanged image back as a proxy URL (not as data:) and so does not
            upload it again - a cleanup run would remove its file and leave the
            reference pointing at nothing. The same content gives the same hash,
            so saving the same image repeatedly creates no duplicates either.
            """
            try:
                ext = 'png' if 'png' in src.split(';')[0] else 'jpg'
                img_bytes = base64.b64decode(src.split(',', 1)[1])
                kurz = _hl.sha1(img_bytes).hexdigest()[:10]
                nc = _nc_upload(img_bytes, f"{data_folder}/{safe}_{marke}_{kurz}.{ext}", f"image/{ext}")
                return f"nc://{nc}" if nc else None
            except Exception:
                return None

        def _fab_durchlaufen(objekte, pfad='fab'):
            """Walks the object list recursively - into groups as well.

            Without going in, a cut-out image grouped with a text field stayed in
            the canvas_json as several MB of base64.
            """
            for i, obj in enumerate(objekte or []):
                if not isinstance(obj, dict):
                    continue
                src = obj.get('src', '')
                if isinstance(src, str) and src.startswith('data:image'):
                    # Only offload when the client really uses this src on load
                    # (see restoreCanvas in io.js: unedited images are loaded
                    # through srcUrl). Otherwise files would be created that
                    # nobody ever fetches.
                    if obj.get('edited') or obj.get('bgRemoved') or not obj.get('srcUrl'):
                        ref = _fab_auslagern(src, f'{pfad}{i}')
                        if ref:
                            obj['src'] = ref
                if obj.get('objects'):
                    _fab_durchlaufen(obj['objects'], f'{pfad}{i}g')

        fab = state.get('fabric') or {}
        _fab_durchlaufen(fab.get('objects'))
        bgi = fab.get('backgroundImage')
        if isinstance(bgi, dict):
            src = bgi.get('src', '')
            if isinstance(src, str) and src.startswith('data:image'):
                ref = _fab_auslagern(src, 'fabbg')
                if ref:
                    bgi['src'] = ref

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
        # The counterpart to the offloading in _optimize_canvas_json: the
        # offloaded nc:// references sit in the fabric branch. Without these
        # lines an unresolvable "nc://…" would arrive in the browser and the
        # image would be missing. Recursive, so images inside groups are covered.
        def _proxy_durchlaufen(objekte):
            for obj in (objekte or []):
                if not isinstance(obj, dict):
                    continue
                if isinstance(obj.get('src'), str):
                    obj['src'] = _proxy(obj['src'])
                if obj.get('objects'):
                    _proxy_durchlaufen(obj['objects'])

        fab = state.get('fabric') or {}
        _proxy_durchlaufen(fab.get('objects'))
        bgi = fab.get('backgroundImage')
        if isinstance(bgi, dict) and isinstance(bgi.get('src'), str):
            bgi['src'] = _proxy(bgi['src'])
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
    """True when the file is gone afterwards.

    The return value is not decoration: this function used to swallow it, which
    is why studio_output_delete reported success even when Nextcloud had refused
    the deletion. The tile vanished, the file stayed, and on the next load it
    was back.
    """
    ok, _grund = _nc_delete_detail(nc_path)
    return ok


def _nc_delete_detail(nc_path):
    """(ok, Grund) - fuer jede Stelle, die dem Nutzer sagt, ob es geklappt hat."""
    from posts_posted.nc_storage import delete_from_nextcloud_detail
    return delete_from_nextcloud_detail(nc_path)


def _nc_delete_aufraeumen(nc_path, zweck):
    """A deletion that MAY fail - old versions, previews, leftovers.

    The difference to a user-facing deletion: nobody is waiting for an answer
    here, and a failure must not bring down the actual operation. But it must
    not vanish without trace either - otherwise dead files pile up and nobody
    knows why. So: carry on, but write it to the log.
    """
    if not nc_path:
        return False
    try:
        ok, grund = _nc_delete_detail(nc_path)
    except Exception as e:
        print("Cleanup (%s) failed: %s -- %s" % (zweck, nc_path, e))
        return False
    if not ok:
        print("Cleanup (%s) failed: %s -- %s" % (zweck, nc_path, grund))
    return ok


@einmal_pro_prozess
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
        # Add the extra_colors column if the table already exists
        try:
            c.execute("SHOW COLUMNS FROM brand_colors LIKE 'extra_colors'")
            if not c.fetchone():
                c.execute("ALTER TABLE brand_colors ADD COLUMN extra_colors TEXT DEFAULT NULL")
        except Exception: pass
        # Make sure there is always exactly one row
        try:
            c.execute("SELECT COUNT(*) FROM brand_colors")
            if c.fetchone()[0] == 0:
                c.execute("INSERT INTO brand_colors (c1,c2,c3,c4,c5,c6) VALUES ('#ffffff','#F56E28','#008591','#61CEBC','#005F68','#161616')")
        except Exception: pass


def get_brand_colors():
    """Returns the current brand colours as a dict (including the extra_colors list).

    Robust against database outages: the whole access, table setup included, runs
    inside the try. On a database problem the default colours are returned, so a
    hiccup does not turn EVERY page into a 500 through this context processor.
    """
    defaults = {'c1':'#ffffff','c2':'#F56E28','c3':'#008591','c4':'#61CEBC','c5':'#005F68','c6':'#161616','extra_colors':[]}
    try:
        _ensure_brand_colors_table()
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


@einmal_pro_prozess
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
        # Migration: Layout der Vorlage (Hintergrund + Logo + Textfelder) speichern.
        try:
            c.execute("ALTER TABLE studio_templates ADD COLUMN canvas_json LONGTEXT DEFAULT NULL")
        except Exception: pass
        # Migration: active/inactive - inactive templates do not appear in the Studio picker.
        try:
            c.execute("ALTER TABLE studio_templates ADD COLUMN active TINYINT DEFAULT 1")
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
        # Post media: the image column already exists; GIF and video get their own
        # columns, so all three files can hang on a post and be fetched separately.
        try:
            c.execute("ALTER TABLE planner_posts ADD COLUMN gif_nc_path VARCHAR(512) DEFAULT NULL")
        except Exception: pass
        try:
            c.execute("ALTER TABLE planner_posts ADD COLUMN video_nc_path VARCHAR(512) DEFAULT NULL")
        except Exception: pass


# ─────────────────────────────────────────────
#  STUDIO VIEWS
# ─────────────────────────────────────────────

@login_required
def studio_flowcharts_view(request):
    return render(request, 'media_library/flowcharts.html')


# @login_required was on studio_flowcharts_view twice by accident and missing
# here entirely. studio_view renders post titles, library data and the complete
# canvas_json straight into the HTML - that was reachable without signing in.
@login_required
def studio_view(request):
    _ensure_studio_tables()
    post_id = request.GET.get('post_id', '')
    post_data = None
    if post_id:
        try:
            from urllib.parse import quote as _q
            with connection.cursor() as c:
                rows = _safe(c, """SELECT id, title, image, content,
                                          COALESCE(gif_nc_path,''), COALESCE(video_nc_path,'')
                                     FROM planner_posts WHERE id=%s""", [post_id])
                if rows:
                    r = rows[0]
                    post_data = {'id': r[0], 'title': r[1] or '', 'image': r[2] or '', 'content': (r[3] or '')[:120],
                                 'gif': r[4] or '', 'video': r[5] or ''}
                    # Fetch URLs for the three files on the post (picked in the banner).
                    post_data['image_url'] = f"/library/studio/api/post-image/{r[0]}/" if post_data['image'] else ''
                    post_data['gif_url']   = ('/library/studio/nc-image/?p=' + _q(post_data['gif']))   if post_data['gif']   else ''
                    post_data['video_url'] = ('/library/studio/nc-image/?p=' + _q(post_data['video'])) if post_data['video'] else ''
                # Load the design. Prefer the row belonging to the file CURRENTLY
                # attached to the post (image/GIF/video) - that is the last
                # complete version saved. Only then the post_id row. This stops an
                # old, empty version (background only) from being picked.
                cand_media = ''
                if post_data:
                    cand_media = post_data.get('image') or post_data.get('video') or post_data.get('gif') or ''
                canvas_rows = None
                if cand_media:
                    _fn = cand_media.rsplit('/', 1)[-1]
                    canvas_rows = _safe(c, """SELECT canvas_json, template_id FROM studio_images
                                              WHERE (nc_path=%s OR nc_path LIKE %s)
                                                AND canvas_json IS NOT NULL AND canvas_json <> ''
                                              ORDER BY id DESC LIMIT 1""", [cand_media, '%/' + _fn])
                if not (canvas_rows and canvas_rows[0][0]):
                    canvas_rows = _safe(c, """SELECT canvas_json, template_id FROM studio_images
                                              WHERE post_id=%s AND canvas_json IS NOT NULL AND canvas_json <> ''
                                              ORDER BY id DESC LIMIT 1""", [post_id])
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
                rows = _safe(c, "SELECT nc_path, title FROM media_library_items WHERE id=%s", [lib_item_id])
                if rows:
                    nc_path = rows[0][0]
                    studio_rows = _safe(c, """SELECT canvas_json, template_id FROM studio_images
                                             WHERE nc_path=%s ORDER BY created_at DESC LIMIT 1""", [nc_path])
                    # Fallback: the file may have been moved (from Studio_Work/Output
                    # to Planner/Videos, say). Then find the editable design by its
                    # file name, so "🎨 Studio" loads the layout.
                    if not (studio_rows and studio_rows[0][0]):
                        _fn = (nc_path or '').rsplit('/', 1)[-1]
                        if _fn:
                            studio_rows = _safe(c, """SELECT canvas_json, template_id FROM studio_images
                                                     WHERE nc_path LIKE %s ORDER BY id DESC LIMIT 1""", ['%/' + _fn])
                    # Last fallback: by NAME. One design can exist as an image, a
                    # GIF and a video - the design belongs to all three. Without
                    # this branch the PNG opened without its layers after a GIF
                    # export, because studio_images pointed at the GIF path. Names
                    # are unique (see namen.js), so the lookup is reliable.
                    # deshalb ist die Suche zuverlaessig.
                    if not (studio_rows and studio_rows[0][0]) and rows[0][1]:
                        studio_rows = _safe(c, """SELECT canvas_json, template_id FROM studio_images
                                                 WHERE title=%s AND canvas_json IS NOT NULL
                                                 AND (post_id IS NULL OR post_id=0)
                                                 ORDER BY id DESC LIMIT 1""", [rows[0][1]])
                    _low = (nc_path or '').lower()
                    lib_data = {'item_id': lib_item_id, 'image_url': f"/library/image/{lib_item_id}/",
                                'title': rows[0][1] or '', 'nc_path': nc_path,
                                'kind': 'gif' if _low.endswith('.gif') else ('video' if _low.endswith(('.webm', '.mp4', '.mov')) else 'image')}
                    if studio_rows and studio_rows[0][0]:
                        lib_data['canvas_json'] = studio_rows[0][0]
                        lib_data['template_id'] = studio_rows[0][1]
        except Exception as e:
            print("Studio lib lookup:", e)

    # Opening an output directly by its Nextcloud path (My outputs now shows the
    # NC folders directly). The canvas_json comes from studio_images, if present.
    nc_open = request.GET.get('nc_path', '')
    if nc_open and not lib_data and not post_id:
        try:
            from urllib.parse import quote as _q
            _fname = nc_open.rsplit('/', 1)[-1]
            with connection.cursor() as c:
                si = _safe(c, "SELECT canvas_json FROM studio_images WHERE nc_path=%s ORDER BY id DESC LIMIT 1", [nc_open])
                if not (si and si[0][0]):
                    # Fallback: search by file name (in case the path prefix differs slightly)
                    si = _safe(c, "SELECT canvas_json FROM studio_images WHERE nc_path LIKE %s ORDER BY id DESC LIMIT 1", ['%/' + _fname])
                if not (si and si[0][0]):
                    # Last fallback by NAME (the file name without its extension):
                    # the image, GIF and video of one design share the name and
                    # therefore the same design.
                    _name = _fname.rsplit('.', 1)[0]
                    if _name:
                        si = _safe(c, """SELECT canvas_json FROM studio_images
                                        WHERE title=%s AND canvas_json IS NOT NULL
                                        AND (post_id IS NULL OR post_id=0)
                                        ORDER BY id DESC LIMIT 1""", [_name])
                mi = _safe(c, "SELECT id FROM media_library_items WHERE nc_path=%s LIMIT 1", [nc_open])
            _low = _fname.lower()
            lib_data = {'item_id': (mi[0][0] if mi else None),
                        'title': _fname.rsplit('.', 1)[0], 'nc_path': nc_open,
                        'image_url': '/library/studio/nc-image/?p=' + _q(nc_open),
                        'kind': 'gif' if _low.endswith('.gif') else ('video' if _low.endswith(('.webm', '.mp4', '.mov')) else 'image')}
            if si and si[0][0]:
                lib_data['canvas_json'] = si[0][0]
        except Exception as e:
            print("Studio nc_path open:", e)

    # Open a template for editing (?template=<id>) → load the editable layout.
    tpl_data = None
    tpl_id_param = request.GET.get('template', '')
    if tpl_id_param and not post_id and not lib_data:
        try:
            with connection.cursor() as c:
                trows = _safe(c, "SELECT id, title, width, height, canvas_json FROM studio_templates WHERE id=%s", [tpl_id_param])
            if trows:
                tr = trows[0]
                tpl_data = {'id': tr[0], 'title': tr[1] or '', 'width': tr[2] or 1080,
                            'height': tr[3] or 1080, 'canvas_json': tr[4] or ''}
        except Exception as e:
            print("Studio template open:", e)

    folders = _all_folders()
    # Pass Nextcloud base URL for draw.io embed
    try:
        from posts_posted.nc_storage import _get_nc_credentials
        nc_url_val, _, _ = _get_nc_credentials()
    except Exception:
        nc_url_val = ''
    brand = get_brand_colors()

    # Resolve the canvas JSON for post/lib to same-origin proxy URLs (no CORS tainting)
    if post_data and post_data.get('canvas_json'):
        post_data['canvas_json'] = _resolve_nc_refs_in_json(post_data['canvas_json'])
    if lib_data and lib_data.get('canvas_json'):
        lib_data['canvas_json'] = _resolve_nc_refs_in_json(lib_data['canvas_json'])
    if tpl_data and tpl_data.get('canvas_json'):
        tpl_data['canvas_json'] = _resolve_nc_refs_in_json(tpl_data['canvas_json'])

    # Zentrale Konfiguration fuers Frontend (studio.js liest #studio-config)
    studio_config = {
        'postId': post_id or None,
        'postData': post_data,
        'libData': lib_data,
        'tplData': tpl_data,
        'ncUrl': (nc_url_val or '').rstrip('/'),
        'brandExtraColors': brand.get('extra_colors', []),
        'urls': {
            'save':          '/library/studio/save/',
            'upload':        '/library/studio/upload/',
            'uploadDelete':  '/library/studio/upload/delete/',
            'outputDelete':  '/library/studio/api/output/delete/',
            'saveVideo':     '/library/studio/video-template/save/',
            'saveVideoFile': '/library/studio/save-video/',
            'apiTemplates':  '/library/studio/api/templates/',
            'apiLibrary':    '/library/studio/api/library/',
            'apiSaved':      '/library/studio/api/saved/',
            'apiOutputs':    '/library/studio/api/outputs/',
            'ncFolders':     '/library/studio/api/nc-folders/',
            'ncBrowse':      '/library/studio/api/nc-browse/',
            'ncImage':       '/library/studio/nc-image/',
            'sharedAssets':  '/library/studio/api/shared-assets/',
            'dbToNc':        '/library/studio/api/db-to-nc/',
            'brandColors':   '/library/studio/brand-colors/save/',
            'postsWithImages': '/library/studio/api/posts-with-images/',
            'saveTemplate':  '/library/studio/template/save-canvas/',
        },
    }

    # The "back" target is the page we came from (the referrer). Do not jump back
    # into the Studio itself; fall back to the overview instead.
    back_url = request.META.get('HTTP_REFERER', '') or ''
    if not back_url or '/library/studio/' in back_url:
        back_url = '/planner/uebersicht/'

    return render(request, 'media_library/studio.html', {
        'post_id': post_id, 'post_data': post_data, 'lib_data': lib_data,
        'folders': folders, 'nc_url': (nc_url_val or '').rstrip('/'),
        'studio_config': studio_config, 'back_url': back_url,
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
        return JsonResponse({'ok': False, 'error': 'video_nc_path missing'}, status=400)

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
        return JsonResponse({'ok': False, 'error': 'Item could not be created'}, status=500)

    return JsonResponse({'ok': True, 'item_id': item_id,
                         'studio_url': f"/library/studio/?lib_item={item_id}"})


@login_required
def studio_templates_view(request):
    _ensure_studio_tables()
    with connection.cursor() as c:
        rows = _safe(c, "SELECT id, title, width, height, colors, created_at, COALESCE(active,1) FROM studio_templates ORDER BY created_at DESC") \
            or _safe(c, "SELECT id, title, width, height, colors, created_at FROM studio_templates ORDER BY created_at DESC")
    templates = []
    for r in (rows or []):
        colors = []
        if r[4]:
            try: colors = json.loads(r[4])
            except: pass
        templates.append({'id': r[0], 'title': r[1], 'width': r[2], 'height': r[3], 'colors': colors,
                          'active': bool(r[6]) if len(r) > 6 else True,
                          'url': f"/library/studio/template/image/{r[0]}/"})
    brand = get_brand_colors()
    return render(request, 'media_library/studio_templates.html', {'templates': templates, 'brand': brand})


@login_required
def studio_template_toggle_active(request, tpl_id):
    """Vorlage aktiv/passiv schalten. Passive erscheinen nicht in der Studio-Auswahl."""
    if request.method != 'POST':
        return redirect('media_library:studio_templates')
    _ensure_studio_tables()
    with connection.cursor() as c:
        try:
            c.execute("UPDATE studio_templates SET active = 1 - COALESCE(active,1) WHERE id=%s", [tpl_id])
        except Exception:
            pass
    return redirect('media_library:studio_templates')


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
    # Collect the extra colours from the form
    extra = [v for k, v in request.POST.items() if k.startswith('extra_') and v.startswith('#')]
    extra_json = json.dumps(extra) if extra else None
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM brand_colors")
            if cur.fetchone()[0] > 0:
                cur.execute("UPDATE brand_colors SET c1=%s,c2=%s,c3=%s,c4=%s,c5=%s,c6=%s,extra_colors=%s", [c1,c2,c3,c4,c5,c6,extra_json])
            else:
                cur.execute("INSERT INTO brand_colors (c1,c2,c3,c4,c5,c6,extra_colors) VALUES (%s,%s,%s,%s,%s,%s,%s)", [c1,c2,c3,c4,c5,c6,extra_json])
        messages.success(request, 'Brand colours saved.')
    except Exception as e:
        messages.error(request, f'Error: {e}')
    return redirect('/library/studio/templates/')


@login_required
def studio_template_upload(request):
    _ensure_studio_tables()
    if request.method != 'POST':
        return redirect('media_library:studio_templates')
    f = request.FILES.get('template')
    if not f:
        messages.error(request, 'No template selected.')
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
    messages.success(request, 'Template saved!')
    return redirect('media_library:studio_templates')


@login_required
def studio_template_save_from_canvas(request):
    """Save the current Studio artboard directly as a template (no file upload).
    Expects JSON: {dataUrl, title, width, height, colors?}."""
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'POST required'}, status=405)
    _ensure_studio_tables()
    import time, base64, json as _j
    try:
        data = _j.loads(request.body)
    except Exception:
        return JsonResponse({'ok': False, 'error': 'Bad JSON'}, status=400)
    data_url = data.get('dataUrl') or ''
    title = (data.get('title') or '').strip() or f'Vorlage {time.strftime("%d.%m.%Y %H:%M")}'
    try:
        width = int(data.get('width') or 1080)
        height = int(data.get('height') or 1080)
    except Exception:
        width, height = 1080, 1080
    if ',' not in data_url:
        return JsonResponse({'ok': False, 'error': 'No image submitted'}, status=400)
    try:
        content = base64.b64decode(data_url.split(',', 1)[1])
    except Exception:
        return JsonResponse({'ok': False, 'error': 'Image could not be read'}, status=400)
    filename = f"tpl_{int(time.time())}.png"
    nc_path = _nc_upload(content, f"{NC_STUDIO_TEMPLATES_FOLDER}/{filename}", 'image/png')
    if not nc_path:
        from django.conf import settings as _s
        local_dir = os.path.join(_s.BASE_DIR, 'media', 'studio', 'templates')
        os.makedirs(local_dir, exist_ok=True)
        with open(os.path.join(local_dir, filename), 'wb') as fh:
            fh.write(content)
        nc_path = f"__local__/studio/templates/{filename}"
    cols = data.get('colors') or []
    colors_json = _j.dumps([c for c in cols if c]) if cols else None
    canvas_json = data.get('canvasJson') or None   # Hintergrund + Logo + Textfelder
    # Offload embedded base64 images to Nextcloud. For templates this did not
    # happen at all until now - a layout with two cut-out images quickly reached
    # double-digit megabytes and failed on the database's packet limit.
    if canvas_json:
        try:
            canvas_json = _optimize_canvas_json(canvas_json, NC_STUDIO_TEMPLATES_FOLDER, title)
        except Exception:
            pass

    # Tells "the canvas_json column is still missing" (which the fallback was
    # gedacht) von allen anderen Fehlern.
    def _fehlende_spalte(exc):
        t = str(exc).lower()
        return 'canvas_json' in t and ('unknown column' in t or 'no such column' in t
                                       or 'does not exist' in t)

    tpl_id = data.get('tplId') or None              # gesetzt → bestehende Vorlage aktualisieren
    with connection.cursor() as c:
        if tpl_id:
            # Overwrite the existing template (layout, preview, size and title).
            try:
                c.execute("""UPDATE studio_templates
                             SET nc_path=%s, title=%s, width=%s, height=%s, canvas_json=%s
                             WHERE id=%s""",
                          [nc_path, title, width, height, canvas_json, tpl_id])
            except Exception as e:
                # This branch used to catch EVERY error and then report success
                # - although the layout had not been written at all. The
                # template then showed a new preview over the OLD layout, and
                # nobody could tell anything had gone wrong.
                if not _fehlende_spalte(e):
                    return JsonResponse(
                        {'ok': False, 'error': f'Template could not be saved: {e}'},
                        status=500)
                c.execute("UPDATE studio_templates SET nc_path=%s, title=%s, width=%s, height=%s WHERE id=%s",
                          [nc_path, title, width, height, tpl_id])
            return JsonResponse({'ok': True, 'id': tpl_id, 'title': title, 'updated': True})
        try:
            c.execute("""INSERT INTO studio_templates (nc_path, title, width, height, colors, canvas_json)
                         VALUES (%s,%s,%s,%s,%s,%s)""",
                      [nc_path, title, width, height, colors_json, canvas_json])
        except Exception as e:
            # Without the canvas_json the new template would be a flat image -
            # every text field and layer lost, despite a success message.
            if not _fehlende_spalte(e):
                return JsonResponse(
                    {'ok': False, 'error': f'Template could not be created: {e}'},
                    status=500)
            c.execute("INSERT INTO studio_templates (nc_path, title, width, height, colors) VALUES (%s,%s,%s,%s,%s)",
                      [nc_path, title, width, height, colors_json])
        new_id = c.lastrowid
    return JsonResponse({'ok': True, 'id': new_id, 'title': title})


@login_required
def studio_template_canvas(request, tpl_id):
    """Liefert das gespeicherte Layout (canvas_json) einer Vorlage zum Anwenden."""
    _ensure_studio_tables()
    with connection.cursor() as c:
        rows = _safe(c, "SELECT canvas_json FROM studio_templates WHERE id=%s", [tpl_id])
    cj = rows[0][0] if rows else None
    return JsonResponse({'ok': bool(cj), 'canvas_json': cj or ''})


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
    messages.success(request, 'Colours saved!')
    return redirect('media_library:studio_templates')


@login_required
def studio_template_delete(request, tpl_id):
    if request.method != 'POST':
        return redirect('media_library:studio_templates')
    with connection.cursor() as c:
        rows = _safe(c, "SELECT nc_path FROM studio_templates WHERE id=%s", [tpl_id])
    if rows:
        # As in library_delete: do not delete the row while the file is still
        # there - otherwise the template is gone from the list and the file is no
        # longer reachable through the app.
        ok, grund = _nc_delete_detail(rows[0][0])
        if not ok:
            messages.error(request, grund or 'The template file could not be deleted.')
            return redirect('media_library:studio_templates')
        with connection.cursor() as c:
            c.execute("DELETE FROM studio_templates WHERE id=%s", [tpl_id])
    messages.success(request, 'Template deleted.')
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
    resp['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return resp


def _extract_canvas_tags(canvas_json_str):
    """Extract searchable tags from canvas_json (texts, colors, shapes, object count)."""
    try:
        state = json.loads(canvas_json_str)
    except Exception:
        return ''
    tags = set()
    objects = state.get('objects', [])
    for obj in objects:
        otype = obj.get('type', '')
        # Texte extrahieren
        if otype == 'text':
            text = (obj.get('text') or '').strip()
            # Jedes Wort als Tag (>2 Zeichen)
            for word in text.split():
                w = word.strip('.,!?;:()[]{}"\'-–—').lower()
                if len(w) > 2:
                    tags.add(w)
        # Shape-Typ
        if otype == 'shape':
            shape = obj.get('shape', '')
            if shape:
                tags.add(shape)
            fill = obj.get('fill', '')
            if fill:
                tags.add(fill.lower())
        # Animation-Typ
        anim = obj.get('animType', '')
        if anim and anim != 'none':
            tags.add('animation')
            tags.add(anim)
        # Bild-Objekte
        if otype == 'img':
            tags.add('bild')
    # Canvas size / number of elements
    if len(objects) > 0:
        tags.add(f'{len(objects)}-elemente')
    # Hintergrund
    bg = state.get('bgColor', '')
    if bg:
        tags.add(bg.lower())
    return ','.join(sorted(tags)[:30])  # max 30 Tags


def _studio_bild_metadaten_schreiben(post_id, lib_item_id, old_nc_path, nc_path,
                                     title, canvas_json, template_id):
    """Creates or updates the studio_images entry. Returns its id.

    Pulled out so the caller can try the operation a second time without the
    canvas_json on failure - rather than throwing a 500 although the file and
    the library entry have already been written.
    """
    with connection.cursor() as c:
        if post_id:
            rows = _safe(c, "SELECT id FROM studio_images WHERE post_id=%s ORDER BY created_at DESC LIMIT 1", [post_id])
            if rows:
                c.execute("""UPDATE studio_images SET nc_path=%s, title=%s, canvas_json=%s, template_id=%s
                             WHERE id=%s""", [nc_path, title, canvas_json or None, template_id, rows[0][0]])
                return rows[0][0]
            c.execute("""INSERT INTO studio_images (nc_path, title, canvas_json, template_id, post_id)
                         VALUES (%s,%s,%s,%s,%s)""", [nc_path, title, canvas_json or None, template_id, post_id])
            return c.lastrowid
        # The design belongs to the DESIGN, not to a single file: the image, GIF
        # and video sharing one (unique) name share one row. Look it up by name
        # first, so a design saved earlier as a GIF is not created a second time
        # when it is saved as an image. Exclude post_id: otherwise a new design
        # of the same name could overwrite the design of a planner post (the post
        # branch above returns earlier, so a post is never meant here).
        # branch above returns earlier, so a post is never meant here).
        rows = _safe(c, """SELECT id FROM studio_images WHERE title=%s
                          AND (post_id IS NULL OR post_id=0)
                          ORDER BY id DESC LIMIT 1""", [title])
        if not rows and old_nc_path:
            rows = _safe(c, "SELECT id FROM studio_images WHERE nc_path=%s ORDER BY created_at DESC LIMIT 1", [old_nc_path])
        if rows:
            c.execute("""UPDATE studio_images SET nc_path=%s, title=%s, canvas_json=%s, template_id=%s
                         WHERE id=%s""", [nc_path, title, canvas_json or None, template_id, rows[0][0]])
            return rows[0][0]
        c.execute("""INSERT INTO studio_images (nc_path, title, canvas_json, template_id)
                     VALUES (%s,%s,%s,%s)""", [nc_path, title, canvas_json or None, template_id])
        return c.lastrowid


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
    lib_item_id = data.get('lib_item_id') or None   # gesetzt beim Weiterbearbeiten
    open_nc     = data.get('openNcPath') or None    # the output file currently open

    # An output is open → reuse exactly that entry (overwrite it).
    if not lib_item_id and not post_id and open_nc:
        with connection.cursor() as c:
            _r = _safe(c, "SELECT id FROM media_library_items WHERE nc_path=%s ORDER BY id DESC LIMIT 1", [open_nc])
            if _r:
                lib_item_id = _r[0][0]

    # "Always overwrite": if a Studio image with the same title already exists,
    # it is updated instead of creating a duplicate.
    if not lib_item_id and not post_id and title:
        with connection.cursor() as c:
            _dup = _safe(c, """SELECT id FROM media_library_items
                               WHERE title=%s AND FIND_IN_SET('studio', REPLACE(tags,' ',''))
                               ORDER BY id DESC LIMIT 1""", [title])
            if _dup:
                lib_item_id = _dup[0][0]

    # Fetch the old nc_path (for the update and to overwrite exactly that file).
    old_nc_path = None
    if lib_item_id and not post_id:
        with connection.cursor() as c:
            _r = _safe(c, "SELECT nc_path FROM media_library_items WHERE id=%s", [lib_item_id])
            if _r:
                old_nc_path = _r[0][0]
    if not old_nc_path and open_nc:
        old_nc_path = open_nc

    if ',' in data_url:
        _, b64 = data_url.split(',', 1)
    else:
        b64 = data_url
    try:
        content = base64.b64decode(b64)
    except Exception:
        return JsonResponse({'error': 'Invalid image data'}, status=400)

    # The file name follows the name. After a rename the file gets the new name
    # - before, it stubbornly kept the old one, so file and display name drifted
    # apart and the image and GIF of one design ended up called different things.
    import re as _re_fn
    _safe_name = _re_fn.sub(r'[^a-zA-Z0-9_.-]', '', (title or 'studio').replace(' ', '_')) or 'studio'
    filename = _safe_name + '.png'
    umbenannt_von = None
    if old_nc_path and old_nc_path.lower().endswith('.png') and '/Output/Images/' in old_nc_path:
        _alt = old_nc_path.rsplit('/', 1)[-1]
        if _alt == filename:
            filename = _alt                      # unveraendert: exakt dieselbe Datei
        else:
            umbenannt_von = old_nc_path          # Umbenennung: alte Datei danach weg
    nc_path  = _nc_upload(content, f"{NC_STUDIO_LIBRARY_FOLDER}/{filename}", 'image/png')
    if not nc_path:
        # local fallback
        from django.conf import settings as _s
        local_dir = os.path.join(_s.BASE_DIR, 'media', 'studio', 'bibliothek')
        os.makedirs(local_dir, exist_ok=True)
        with open(os.path.join(local_dir, filename), 'wb') as fh:
            fh.write(content)
        nc_path = f"__local__/studio/bibliothek/{filename}"

    # Auto-Tags aus Canvas extrahieren
    auto_tags = _extract_canvas_tags(canvas_json) if canvas_json else ''
    all_tags = ','.join(filter(None, ['studio', auto_tags]))

    # Carrying on editing: update the existing entry (the name stays or is
    # updated, no new image). Otherwise create a new one.
    with connection.cursor() as c:
        if lib_item_id and not post_id:
            c.execute("""UPDATE media_library_items SET nc_path=%s, title=%s, tags=%s WHERE id=%s""",
                      [nc_path, title, all_tags, lib_item_id])
            lib_id = lib_item_id
        else:
            c.execute("""INSERT INTO media_library_items (nc_path, title, series, tags, folder_id)
                         VALUES (%s, %s, 'Studio', %s, %s)""", [nc_path, title, all_tags, folder_id])
            lib_id = c.lastrowid

    # Optimize canvas_json: upload base64 images to NC
    if canvas_json:
        canvas_json = _optimize_canvas_json(canvas_json, NC_STUDIO_LIBRARY_FOLDER, title)

    # Save studio metadata (upsert per post_id if given)
    # These statements used to run unprotected. If something failed here (because
    # the canvas_json burst the packet limit, say), Django returned a 500 -
    # although the PNG and the library entry had already been written. The output
    # then turned up as a flat image without layers, and the user saw nothing but
    # an incomprehensible error. Now: a second attempt without the canvas_json,
    # plus a clear warning in the result.
    studio_image_id = None
    warnung = None
    try:
        studio_image_id = _studio_bild_metadaten_schreiben(
            post_id, lib_item_id, old_nc_path, nc_path, title, canvas_json, template_id)
    except Exception as e:
        try:
            studio_image_id = _studio_bild_metadaten_schreiben(
                post_id, lib_item_id, old_nc_path, nc_path, title, None, template_id)
            warnung = ('Das Bild wurde gespeichert, aber der bearbeitbare Entwurf nicht '
                       f'({e}). Beim erneuten Oeffnen sind die Ebenen nicht mehr einzeln '
                       'anpassbar.')
        except Exception as e2:
            return JsonResponse({'ok': False,
                                 'error': f'Bild gespeichert, Entwurf nicht: {e2}'}, status=500)

    # Attach to planner post if post_id given. IMPORTANT: attaching must ALWAYS
    # happen - moving and tidying up are nice to have and must never stop the
    # attaching.
    if post_id:
        old_media = _post_media_to_cleanup(post_id)   # vor dem Überschreiben merken
        new_path = nc_path
        try:
            from planner.views import _nc_move
            fname = nc_path.rsplit('/', 1)[-1]
            moved = _nc_move(nc_path, f"Marketing & Design/LinkedIn/Planner/Images/{fname}")
            if moved:
                new_path = moved
        except Exception as e:
            print("Post move (best effort) error:", e)
        # CRITICAL: attach it to the post.
        try:
            with connection.cursor() as c:
                try:
                    c.execute("UPDATE planner_posts SET image=%s, video_nc_path=NULL, gif_nc_path=NULL WHERE id=%s", [new_path, post_id])
                except Exception:
                    c.execute("UPDATE planner_posts SET image=%s WHERE id=%s", [new_path, post_id])
                if new_path != nc_path:
                    c.execute("UPDATE studio_images SET nc_path=%s WHERE nc_path=%s", [new_path, nc_path])
                    c.execute("UPDATE media_library_items SET nc_path=%s WHERE nc_path=%s", [new_path, nc_path])
            nc_path = new_path
        except Exception as e:
            print("Post attach error:", e)
        _cleanup_old_media(old_media, keep=nc_path)   # delete the old files (best effort)

    # Renamed? Then remove the file under the old name. Otherwise it would stay
    # there, block the old name as "taken" for good, and appear in "My outputs"
    # as a ghost tile without a design.
    if umbenannt_von and umbenannt_von != nc_path:
        _nc_delete_aufraeumen(umbenannt_von, 'Datei unter dem alten Namen')
        try:
            _alt_stamm = umbenannt_von.rsplit('/', 1)[-1].rsplit('.', 1)[0]
            _alt_ordner = umbenannt_von.rsplit('/', 1)[0]
            _nc_delete_aufraeumen(f"{_alt_ordner}/{_alt_stamm}_preview.png",
                                  'Vorschau unter dem alten Namen')
        except Exception as e:
            print("Umbenennen: alter Vorschaupfad nicht bestimmbar:", e)

    image_url = f"/library/image/{lib_id}/"
    antwort = {'ok': True, 'lib_id': lib_id, 'image_url': image_url, 'nc_path': nc_path}
    if warnung:
        antwort['warning'] = warnung
    return JsonResponse(antwort)


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
    lib_item_id = request.POST.get('lib_item_id') or None   # gesetzt beim „Speichern" einer vorhandenen Ausgabe
    post_id = request.POST.get('post_id') or None           # gesetzt, wenn aus einem Post gespeichert wird
    old_nc_path = None
    if lib_item_id:
        with connection.cursor() as c:
            _r = _safe(c, "SELECT nc_path FROM media_library_items WHERE id=%s", [lib_item_id])
            if _r:
                old_nc_path = _r[0][0]
    if not video_file:
        return JsonResponse({'error': 'No video file'}, status=400)
    content = video_file.read()
    import re
    # Detect file type from uploaded filename
    orig_name = video_file.name or ''
    if orig_name.lower().endswith('.gif'):
        ext, ct = '.gif', 'image/gif'
        target_folder = NC_STUDIO_GIFS_FOLDER
    else:
        ext, ct = '.webm', 'video/webm'
        target_folder = NC_STUDIO_VIDEOS_FOLDER
    filename = re.sub(r'[^a-zA-Z0-9_.-]', '', title.replace(' ', '_')) + ext
    nc_path = _nc_upload(content, f"{target_folder}/{filename}", ct)
    if not nc_path:
        from django.conf import settings as _s
        local_dir = os.path.join(_s.BASE_DIR, 'media', 'studio', 'videos')
        os.makedirs(local_dir, exist_ok=True)
        with open(os.path.join(local_dir, filename), 'wb') as fh:
            fh.write(content)
        nc_path = f"__local__/studio/videos/{filename}"
    # Save to media_library_items — update if same title exists, else insert
    with connection.cursor() as c:
        tag = 'gif' if ext == '.gif' else 'video'
        # When "saving" an existing output, overwrite that particular entry.
        # It is looked up by title AND matching format: "(tags='video' OR
        # tags='gif')" used to match the entry of the OTHER moving format and
        # repurpose it. Every format gets its own entry; they are held together
        # by the (unique) name.
        existing = ([[lib_item_id]] if lib_item_id else
                    _safe(c, "SELECT id FROM media_library_items WHERE title=%s AND tags=%s LIMIT 1", [title, tag]))
        if existing:
            lib_id = existing[0][0]
            c.execute("UPDATE media_library_items SET nc_path=%s, title=%s, folder_id=%s, tags=%s WHERE id=%s",
                      [nc_path, title, folder_id, tag, lib_id])
        else:
            c.execute("""INSERT INTO media_library_items (nc_path, title, series, tags, folder_id)
                         VALUES (%s, %s, 'Studio', %s, %s)""", [nc_path, title, tag, folder_id])
            lib_id = c.lastrowid
    # Save canvas state so video can be reopened for editing
    canvas_json = request.POST.get('canvas_json', '')
    if canvas_json:
        canvas_json = _optimize_canvas_json(canvas_json, target_folder, title)
        with connection.cursor() as c:
            # The design belongs to the DESIGN, not to a single file: the image,
            # GIF and video sharing one (unique) name share one studio_images
            # row. On a format change the row used to be moved to the new path -
            # the file of the old format was then reachable from no design at
            # all and opened flat.
            existing_si = _safe(c, """SELECT id FROM studio_images
                                     WHERE title=%s AND (post_id IS NULL OR post_id=0)
                                     ORDER BY id DESC LIMIT 1""", [title])
            if not existing_si and old_nc_path:
                existing_si = _safe(c, "SELECT id FROM studio_images WHERE nc_path=%s ORDER BY id DESC LIMIT 1", [old_nc_path])
            if existing_si:
                c.execute("UPDATE studio_images SET nc_path=%s, title=%s, canvas_json=%s WHERE id=%s",
                          [nc_path, title, canvas_json, existing_si[0][0]])
            else:
                c.execute("""INSERT INTO studio_images (nc_path, title, canvas_json)
                             VALUES (%s, %s, %s)""", [nc_path, title, canvas_json])
    # Attach to the post: a moving image (GIF/video) → video_nc_path. Attaching
    # ALWAYS happens; moving and tidying are best effort and must never stop it.
    if post_id:
        old_media = _post_media_to_cleanup(post_id)
        new_path = nc_path
        try:
            from planner.views import _nc_move
            fname = nc_path.rsplit('/', 1)[-1]
            moved = _nc_move(nc_path, f"Marketing & Design/LinkedIn/Planner/Videos/{fname}")
            if moved:
                new_path = moved
        except Exception as e:
            print("save-video move (best effort):", e)
        try:
            with connection.cursor() as c:
                try:
                    c.execute("UPDATE planner_posts SET video_nc_path=%s, image=NULL, gif_nc_path=NULL WHERE id=%s", [new_path, post_id])
                except Exception:
                    c.execute("UPDATE planner_posts SET video_nc_path=%s, image=NULL WHERE id=%s", [new_path, post_id])
                if new_path != nc_path:
                    c.execute("UPDATE studio_images SET nc_path=%s WHERE nc_path=%s", [new_path, nc_path])
                    c.execute("UPDATE media_library_items SET nc_path=%s WHERE nc_path=%s", [new_path, nc_path])
                # IMPORTANT: save the design under the post_id row, so "🎨 Image"
                # loads the LAST saved version on opening, not the old one.
                if canvas_json:
                    _pr = _safe(c, "SELECT id FROM studio_images WHERE post_id=%s ORDER BY id DESC LIMIT 1", [post_id])
                    if _pr:
                        c.execute("UPDATE studio_images SET canvas_json=%s, nc_path=%s, title=%s WHERE id=%s",
                                  [canvas_json, new_path, title, _pr[0][0]])
                    else:
                        c.execute("INSERT INTO studio_images (nc_path, title, canvas_json, post_id) VALUES (%s,%s,%s,%s)",
                                  [new_path, title, canvas_json, post_id])
            nc_path = new_path
        except Exception as e:
            print("save-video post attach:", e)
        _cleanup_old_media(old_media, keep=nc_path)
    return JsonResponse({'ok': True, 'nc_path': nc_path, 'filename': filename, 'lib_id': lib_id})


@login_required
def studio_api_templates(request):
    _ensure_studio_tables()
    with connection.cursor() as c:
        # Only active templates in the Studio picker.
        rows = _safe(c, "SELECT id, title, width, height, colors, canvas_json FROM studio_templates WHERE COALESCE(active,1)=1 ORDER BY created_at DESC") \
            or _safe(c, "SELECT id, title, width, height, colors FROM studio_templates ORDER BY created_at DESC")
    data = []
    for r in (rows or []):
        colors = []
        if r[4]:
            try:
                import json as _j; colors = _j.loads(r[4])
            except Exception: pass
        has_canvas = bool(len(r) > 5 and r[5])
        data.append({'id': r[0], 'title': r[1] or '', 'width': r[2], 'height': r[3],
                     'url': f"/library/studio/template/image/{r[0]}/", 'colors': colors,
                     'has_canvas': has_canvas})
    return JsonResponse({'templates': data})


NC_STUDIO_VIDEO_TEMPLATES_FOLDER = "Marketing & Design/Octotrial_Assets/Studio_Work/Bewegte_Bilder"


@einmal_pro_prozess
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
        return JsonResponse({'error': 'No canvas_json'}, status=400)

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


# Media type by file extension. The extension is the more reliable source:
# Nextcloud often reports application/octet-stream for .webm, and a <video>
# with octet-stream will not even start in Chrome.
MEDIENTYPEN = {
    '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
    '.gif': 'image/gif', '.webp': 'image/webp', '.avif': 'image/avif',
    '.svg': 'image/svg+xml',
    '.webm': 'video/webm', '.mp4': 'video/mp4', '.m4v': 'video/x-m4v',
    '.mov': 'video/quicktime', '.ogv': 'video/ogg',
}

BEWEGTBILD = {'.webm', '.mp4', '.m4v', '.mov', '.ogv'}


def medientyp(nc_path, vom_server=''):
    """A file's media type. The extension beats the server's word; octet-stream
    counts as "don't know" and is therefore never taken when the extension says
    something."""
    endung = os.path.splitext(str(nc_path or ''))[1].lower()
    if endung in MEDIENTYPEN:
        return MEDIENTYPEN[endung]
    vom_server = (vom_server or '').split(';')[0].strip()
    if vom_server and vom_server != 'application/octet-stream':
        return vom_server
    return 'application/octet-stream'


def bereich_lesen(kopfzeile, groesse):
    """'bytes=100-499' plus the file size -> (100, 499). None when there is
    nothing, or nothing usable; ('unerfuellbar', size) when the start lies past
    the end of the file (in which case a 416 is due).

    Only the simple form with ONE range - no browser asks for more for video,
    and doing more would mean building multipart responses.
    """
    if not kopfzeile or groesse is None or groesse <= 0:
        return None
    text = str(kopfzeile).strip()
    if '=' not in text or ',' in text:
        return None
    einheit, _, spanne = text.partition('=')
    # Spaces around the equals sign are allowed.
    if einheit.strip().lower() != 'bytes':
        return None
    spanne = spanne.strip()
    if '-' not in spanne:
        return None
    von, _, bis = spanne.partition('-')
    von, bis = von.strip(), bis.strip()
    try:
        if not von:
            # 'bytes=-500' = die letzten 500 Bytes
            if not bis:
                return None
            laenge = int(bis)
            if laenge <= 0:
                return None
            return (max(0, groesse - laenge), groesse - 1)
        anfang = int(von)
        if anfang < 0:
            return None
        if anfang >= groesse:
            return ('unerfuellbar', groesse)
        ende = int(bis) if bis else groesse - 1
        if ende < anfang:
            return None
        return (anfang, min(ende, groesse - 1))
    except ValueError:
        return None


# What can be scaled down. SVG stays out (Pillow does not read it, and it is
# small anyway), video likewise - a still from it would need ffmpeg.
VORSCHAU_FAEHIG = {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.avif'}

# Fixed steps. Arbitrary widths would flood the cache with near-duplicates.
VORSCHAU_BREITEN = (240, 480)


def _zeitstempel(getlastmodified):
    """A WebDAV date -> seconds since 1970. 0 when there is nothing readable.

    It becomes part of the thumbnail address, not part of a calculation - so a 0
    costs only the permanent caching, it breaks nothing.
    """
    if not getlastmodified:
        return 0
    try:
        from email.utils import parsedate_to_datetime
        return int(parsedate_to_datetime(getlastmodified).timestamp())
    except Exception:
        return 0


def vorschau_groesse(breite, hoehe, ziel):
    """(width, height) for scaling down to the target width, keeping the aspect
    ratio. Never scales up: stretching an 80-pixel image to 240 costs bandwidth
    and looks worse than the original. The height never falls below 1.
    """
    if not breite or not hoehe or breite <= 0 or hoehe <= 0:
        return None
    if breite <= ziel:
        return None
    return (ziel, max(1, round(hoehe * ziel / breite)))


def vorschau_schluessel(nc_path, stand, breite):
    """A unique, short file name for the cached thumbnail.

    The modification time belongs in the key: otherwise an image saved again
    under the same path would keep showing the old thumbnail - which is exactly
    why caching was switched off entirely when serving the originals.
    """
    import hashlib
    roh = '%s|%s|%s' % (nc_path, stand, breite)
    return hashlib.sha1(roh.encode('utf-8')).hexdigest()


def _vorschau_ordner():
    from django.conf import settings as _s
    pfad = os.path.join(_s.BASE_DIR, 'media', '_thumbs')
    os.makedirs(pfad, exist_ok=True)
    return pfad


def _vorschau_cache_stutzen(ordner, hoechstens=4000):
    """Throw away the oldest thumbnails when there get to be too many. The cache
    is expendable at any time - every image can be made again."""
    try:
        namen = os.listdir(ordner)
        if len(namen) <= hoechstens:
            return
        mit_alter = []
        for n in namen:
            p = os.path.join(ordner, n)
            try:
                mit_alter.append((os.path.getmtime(p), p))
            except OSError:
                pass
        mit_alter.sort()
        for _, p in mit_alter[:len(mit_alter) - hoechstens + 500]:
            try:
                os.remove(p)
            except OSError:
                pass
    except Exception as e:
        print("Trimming the thumbnail cache:", e)


NC_PLANNER_IMAGES_FOLDER = "Marketing & Design/LinkedIn/Planner/Images"
NC_PLANNER_VIDEOS_FOLDER = "Marketing & Design/LinkedIn/Planner/Videos"

# Where a finished output can live, and which extensions belong in which tab.
# Reiter gehoeren.
#
# Why two places: when an output is attached to a post, the file is MOVED out of
# the Studio folder into the Planner folder (not copied - that is deliberate,
# the file should sit with the post). But "My outputs" only ever read the Studio
# folder. The result: as soon as an output hung on a post it had vanished from
# the list, although it existed. So both places are read now.
# Orte gelesen.
#
# GIFs and videos end up in the same Planner folder - they are told apart by
# extension, or videos would stand in the GIF tab.
AUSGABE_ORTE = {
    'Images': ((NC_STUDIO_LIBRARY_FOLDER, NC_PLANNER_IMAGES_FOLDER),
               {'.png', '.jpg', '.jpeg', '.webp', '.svg', '.avif'}),
    'GIFs':   ((NC_STUDIO_GIFS_FOLDER, NC_PLANNER_VIDEOS_FOLDER),
               {'.gif'}),
    'Videos': ((NC_STUDIO_VIDEOS_FOLDER, NC_PLANNER_VIDEOS_FOLDER),
               {'.webm', '.mp4', '.m4v', '.mov', '.ogv'}),
}

# Preview, snapshot and offloaded object images are helper files.
import re as _re_hilfsdateien
HILFSDATEI = _re_hilfsdateien.compile(r'_preview\.|_snap\.|_obj\d+\.|_fab\.', _re_hilfsdateien.I)


def _nc_dateien(nc_folder, endungen=None):
    """The files of ONE Nextcloud folder, not recursive. A list of dicts with
    name, title, nc_path, url, thumb and mtime; an empty list on any problem.

    studio_nc_browse still has its own version of this - the '__all__' special
    case and the subfolder listing hang off it there, and it works. New readers
    please use this one.
    """
    from posts_posted.nc_storage import _get_nc_credentials
    from urllib.parse import quote, unquote
    import xml.etree.ElementTree as ET
    import requests as _req
    from requests.auth import HTTPBasicAuth

    nc_url, username, password = _get_nc_credentials()
    if not all([nc_url, username, password]) or '..' in nc_folder:
        return []
    url = "{}/remote.php/dav/files/{}/{}".format(
        nc_url.rstrip('/'), username, quote(nc_folder, safe='/'))
    try:
        r = _req.request('PROPFIND', url, auth=HTTPBasicAuth(username, password),
                         headers={'Depth': '1', 'Content-Type': 'application/xml'},
                         timeout=30)
        if r.status_code not in (200, 207):
            # A 404 is normal: the Planner folder exists only once something is in it.
            if r.status_code != 404:
                print("nc list %s: %s" % (nc_folder, r.status_code))
            return []
    except Exception as e:
        print("nc list %s: %s" % (nc_folder, e))
        return []

    ergebnis = []
    ns = {'d': 'DAV:'}
    basis = "/remote.php/dav/files/%s/" % username
    wurzel = (basis + quote(nc_folder, safe='/') + '/')
    try:
        baum = ET.fromstring(r.text)
    except Exception as e:
        print("nc list %s: XML %s" % (nc_folder, e))
        return []
    for el in baum.findall('.//d:response', ns):
        href = unquote(el.findtext('d:href', '', ns))
        if href.endswith('/') or href.rstrip('/') == unquote(wurzel).rstrip('/'):
            continue
        name = href.rstrip('/').split('/')[-1]
        if name.startswith('.') or HILFSDATEI.search(name):
            continue
        endung = os.path.splitext(name)[1].lower()
        if endungen is not None and endung not in endungen:
            continue
        stelle = href.find(basis)
        nc_path = href[stelle + len(basis):] if stelle >= 0 else "%s/%s" % (nc_folder, name)
        stand = _zeitstempel(el.findtext('.//d:getlastmodified', '', ns))
        eintrag = {
            'name': name,
            'title': os.path.splitext(name)[0].replace('_', ' '),
            'nc_path': nc_path,
            'url': "/library/studio/nc-image/?p=%s" % quote(nc_path, safe='/'),
            'mtime': stand,
        }
        if endung in VORSCHAU_FAEHIG:
            eintrag['thumb'] = "/library/studio/thumb/?p=%s&t=%d&w=%d" % (
                quote(nc_path, safe='/'), stand, VORSCHAU_BREITEN[0])
        ergebnis.append(eintrag)
    return ergebnis


def ausgaben_zusammenfuehren(aus_studio, aus_planner):
    """Both places into one list. The same file name means the same output - the
    file was moved, not copied. The Planner version is kept, because that is
    where it lives now.

    Sorted by modification time, newest first - before, whatever Nextcloud
    happened to return came out.
    """
    nach_name = {}
    for eintrag in aus_studio:
        nach_name[eintrag['name'].lower()] = dict(eintrag, am_post=False)
    for eintrag in aus_planner:
        nach_name[eintrag['name'].lower()] = dict(eintrag, am_post=True)
    zusammen = list(nach_name.values())
    zusammen.sort(key=lambda e: e.get('mtime') or 0, reverse=True)
    return zusammen


@login_required
def studio_output_list(request):
    """The finished outputs of one tab - from the Studio folder AND the Planner
    folder. See AUSGABE_ORTE for why there are two."""
    reiter = (request.GET.get('kind') or 'Images').strip()
    if reiter not in AUSGABE_ORTE:
        return JsonResponse({'ok': False, 'error': 'Unknown kind', 'items': []}, status=400)
    (studio_ordner, planner_ordner), endungen = AUSGABE_ORTE[reiter]
    items = ausgaben_zusammenfuehren(
        _nc_dateien(studio_ordner, endungen),
        _nc_dateien(planner_ordner, endungen),
    )
    return JsonResponse({'ok': True, 'items': items})


@login_required
def studio_thumb(request):
    """A scaled-down thumbnail for the tiles in the media panel.

    Why it exists: a tile used to show the full file. A saved output is a
    1080x1080 PNG, an asset often larger. With forty tiles the browser loaded
    forty full images and held forty full-size bitmaps in memory - for tiles 240
    pixels wide. Here that comes to about 15 KB.

    The source file's modification time is in the address (?t=). So the answer
    may be cached forever without a stale image ever appearing: change the file
    and the address changes.
    """
    nc_path = (request.GET.get('p') or '').strip()
    if not nc_path or not _within_app_folders(nc_path):
        raise Http404

    endung = os.path.splitext(nc_path)[1].lower()
    if endung not in VORSCHAU_FAEHIG:
        # SVG, video and anything unknown go the normal way, unchanged.
        return studio_nc_image_proxy(request)

    try:
        breite = int(request.GET.get('w') or VORSCHAU_BREITEN[0])
    except ValueError:
        breite = VORSCHAU_BREITEN[0]
    if breite not in VORSCHAU_BREITEN:
        breite = VORSCHAU_BREITEN[0]
    stand = (request.GET.get('t') or '0').strip()[:20]

    ordner = _vorschau_ordner()
    ziel = os.path.join(ordner, vorschau_schluessel(nc_path, stand, breite))

    def _ausliefern(pfad):
        typ = 'image/png' if pfad.endswith('.png') else 'image/jpeg'
        resp = FileResponse(open(pfad, 'rb'), content_type=typ)
        resp['Content-Length'] = str(os.path.getsize(pfad))
        # The address carries the modification time - the same address always
        # means the same image. So it may be cached permanently.
        resp['Cache-Control'] = 'private, max-age=31536000, immutable'
        return resp

    for endung_cache in ('.png', '.jpg'):
        if os.path.isfile(ziel + endung_cache):
            return _ausliefern(ziel + endung_cache)

    # Not in the cache yet: fetch the original and scale it down.
    if nc_path.startswith('__local__/'):
        from django.conf import settings as _s
        quelle = os.path.join(_s.BASE_DIR, 'media', nc_path[len('__local__/'):])
        if not os.path.isfile(quelle):
            raise Http404
        with open(quelle, 'rb') as f:
            rohdaten = f.read()
    else:
        from posts_posted.nc_storage import download_image_from_nextcloud
        rohdaten, _ct = download_image_from_nextcloud(nc_path)
        if not rohdaten:
            raise Http404

    try:
        from PIL import Image
        import io as _io
        bild = Image.open(_io.BytesIO(rohdaten))
        # For a GIF only the first frame - a moving thumbnail would be as big as
        # the original again.
        if getattr(bild, 'is_animated', False):
            bild.seek(0)
        masse = vorschau_groesse(bild.width, bild.height, breite)
        if masse:
            bild = bild.convert('RGBA' if 'A' in bild.getbands() else 'RGB')
            bild = bild.resize(masse, Image.LANCZOS)
        else:
            bild = bild.convert('RGBA' if 'A' in bild.getbands() else 'RGB')
        # PNG when there is transparency, JPEG otherwise. A logo on a transparent
        # ground would get a black backing as a JPEG.
        if bild.mode == 'RGBA':
            pfad, format_, args = ziel + '.png', 'PNG', {'optimize': True}
        else:
            pfad, format_, args = ziel + '.jpg', 'JPEG', {'quality': 82, 'optimize': True}
        vorlaeufig = pfad + '.teil'
        bild.save(vorlaeufig, format_, **args)
        os.replace(vorlaeufig, pfad)   # erst umbenennen, wenn die Datei fertig ist
    except Exception as e:
        # No thumbnail possible (broken file, Pillow missing, exotic format):
        # then the original. Slow is better than blank.
        print("Thumbnail failed for %s: %s" % (str(nc_path)[:120], e))
        return studio_nc_image_proxy(request)

    _vorschau_cache_stutzen(ordner)
    return _ausliefern(pfad)


@login_required
def studio_nc_image_proxy(request):
    """Serves images AND moving images from Nextcloud through Django -
    same-origin, so the canvas is not tainted.

    Four things were missing here, and without them video is not reliable:

      * The media type came from Nextcloud. For .webm, Nextcloud often says
        application/octet-stream, and with that a <video> will not even start
        in Chrome. The file extension decides now.
      * Range requests were ignored. The browser fetches video in pieces;
        without a 206 answer there is no seeking, and larger files often do not
        start at all.
      * The whole file sat in memory before the first byte went out.
      * __local__ paths - the fallback for when Nextcloud was out of reach at
        save time - were not recognised. Such files were not fetchable this way
        at all, and the tile stayed grey.
    """
    nc_path = (request.GET.get('p') or '').strip()
    if not nc_path:
        raise Http404
    # The same limit as for deleting: the app's own folders only. Otherwise this
    # would be a reading window into the entire Nextcloud account.
    if not _within_app_folders(nc_path):
        raise Http404

    endung = os.path.splitext(nc_path)[1].lower()
    typ = medientyp(nc_path)
    ist_bewegt = endung in BEWEGTBILD
    bereich_kopf = request.META.get('HTTP_RANGE', '')

    def _fertig(resp):
        # Images can change under the same path (edit and save again) - those
        # must never come from the cache. For moving images "no-cache" is
        # enough: the browser checks back but may keep the pieces, which is what
        # makes seeking in a video bearable at all.
        resp['Cache-Control'] = 'no-cache' if ist_bewegt else 'no-cache, no-store, must-revalidate'
        resp['Accept-Ranges'] = 'bytes'
        return resp

    # ── Fallback files on the local disk ────────────────────────────────────
    if nc_path.startswith('__local__/'):
        from django.conf import settings as _s
        pfad = os.path.join(_s.BASE_DIR, 'media', nc_path[len('__local__/'):])
        if not os.path.isfile(pfad):
            raise Http404
        groesse = os.path.getsize(pfad)
        bereich = bereich_lesen(bereich_kopf, groesse)
        if bereich and bereich[0] == 'unerfuellbar':
            resp = HttpResponse(status=416)
            resp['Content-Range'] = 'bytes */%d' % groesse
            return _fertig(resp)
        if bereich:
            anfang, ende = bereich
            with open(pfad, 'rb') as f:
                f.seek(anfang)
                stueck = f.read(ende - anfang + 1)
            resp = HttpResponse(stueck, content_type=typ, status=206)
            resp['Content-Range'] = 'bytes %d-%d/%d' % (anfang, ende, groesse)
            resp['Content-Length'] = str(len(stueck))
            return _fertig(resp)
        resp = FileResponse(open(pfad, 'rb'), content_type=typ)
        resp['Content-Length'] = str(groesse)
        return _fertig(resp)

    # ── Nextcloud ──────────────────────────────────────────────────────────
    from posts_posted.nc_storage import stream_from_nextcloud
    antwort, grund = stream_from_nextcloud(nc_path, range_header=bereich_kopf or None)
    if antwort is None:
        # The reason belongs in the log. For the browser it stays a 404: an
        # <img> or <video> can do nothing with a piece of text.
        print("nc proxy:", grund, str(nc_path)[:120])
        raise Http404

    typ = medientyp(nc_path, antwort.headers.get('Content-Type', ''))
    resp = StreamingHttpResponse(
        antwort.iter_content(chunk_size=64 * 1024),
        content_type=typ,
        status=antwort.status_code if antwort.status_code == 206 else 200,
    )
    # Pass Nextcloud's own headers through, so the browser knows which piece it
    # got and how big the whole thing is.
    for kopf in ('Content-Range', 'Content-Length'):
        if antwort.headers.get(kopf):
            resp[kopf] = antwort.headers[kopf]
    return _fertig(resp)


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
    q = request.GET.get('q', '').strip()
    q_filter = ''
    q_params = []
    if q:
        q_filter = " AND (m.title LIKE %s OR m.tags LIKE %s)"
        like = f"%{q}%"
        q_params = [like, like]
    with connection.cursor() as c:
        # Load studio images together with their canvas_json to check for animations
        img_rows = _safe(c, """SELECT m.id, m.title, m.nc_path,
                                      si.canvas_json
                               FROM media_library_items m
                               LEFT JOIN studio_images si
                                 ON si.nc_path = m.nc_path
                                 AND si.id = (SELECT MAX(s2.id) FROM studio_images s2 WHERE s2.nc_path = m.nc_path)
                               WHERE FIND_IN_SET('studio', REPLACE(m.tags,' ',''))""" + q_filter + " ORDER BY m.id DESC", q_params)
        vid_rows = _safe(c, """SELECT m.id, m.title, m.nc_path,
                                      (SELECT COUNT(*) FROM studio_images s WHERE s.nc_path=m.nc_path AND s.canvas_json IS NOT NULL) as has_canvas
                               FROM media_library_items m
                               WHERE FIND_IN_SET('video', REPLACE(m.tags,' ',''))""" + q_filter + " ORDER BY m.id DESC", q_params)
        gif_rows = _safe(c, """SELECT m.id, m.title, m.nc_path,
                                      (SELECT COUNT(*) FROM studio_images s WHERE s.nc_path=m.nc_path AND s.canvas_json IS NOT NULL) as has_canvas
                               FROM media_library_items m
                               WHERE FIND_IN_SET('gif', REPLACE(m.tags,' ',''))""" + q_filter + " ORDER BY m.id DESC", q_params)

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

    # Non-animated Studio images → the images section
    images = [{'id': r[0], 'title': r[1] or '', 'url': f"/library/image/{r[0]}/"}
              for r in (img_rows or []) if not _has_anim(r[3])]
    # GIFs-Sektion: echte GIF-Dateien (Tag 'gif') + Legacy-animierte Studio-Bilder
    anim_images = [{'id': r[0], 'title': r[1] or '', 'url': f"/library/image/{r[0]}/",
                    'lib_item_id': r[0], 'has_canvas': bool(r[3])}
                   for r in (gif_rows or [])]
    anim_images += [{'id': r[0], 'title': r[1] or '', 'url': f"/library/image/{r[0]}/",
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
    # Hide Studio-generated images and videos from the library sidebar
    STUDIO_TAGS = {'studio', 'video', 'video-bild'}
    def _is_studio(item):
        tags = {t.strip().lower() for t in (item.get('tags') or '').split(',') if t.strip()}
        return bool(tags & STUDIO_TAGS)
    items = [i for i in items if not _is_studio(i)]

    data = [{'id': i['id'], 'title': i['title'], 'url': f"/library/image/{i['id']}/"} for i in items]
    return JsonResponse({'items': data, 'folders': [{'id': f['id'], 'name': f['name']} for f in folders]})


@login_required
def studio_api_posts_with_images(request):
    """A list of every post that has an image - for the picker "take an image
    from another post". Returns id, title and a same-origin thumbnail URL."""
    posts = []
    with connection.cursor() as c:
        rows = _safe(c, """SELECT id, COALESCE(title,''), COALESCE(planned_date,'')
                           FROM planner_posts
                           WHERE image IS NOT NULL AND image <> '' AND COALESCE(is_oj,0)=0
                           ORDER BY COALESCE(planned_date,'9999-12-31') DESC, id DESC
                           LIMIT 300""") or []
    for r in rows:
        posts.append({'id': r[0], 'title': (r[1] or '(ohne Titel)'),
                      'date': str(r[2] or ''),
                      'thumb': f'/planner/image/{r[0]}/'})
    return JsonResponse({'ok': True, 'posts': posts})


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
        return JsonResponse({'error': 'No image received'}, status=400)

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


# ── Nextcloud-based library (folders and images from Octotrial_Assets) ──

NC_ASSETS_ROOT = "Marketing & Design/Octotrial_Assets"


@login_required
def studio_nc_folders(request):
    """List top-level subfolders of Octotrial_Assets via WebDAV PROPFIND."""
    from posts_posted.nc_storage import _get_nc_credentials
    from urllib.parse import quote, unquote
    import xml.etree.ElementTree as ET

    nc_url, username, password = _get_nc_credentials()
    if not all([nc_url, username, password]):
        return JsonResponse({'folders': [], 'error': 'NC not configured'})

    propfind_url = "{}/remote.php/dav/files/{}/{}".format(
        nc_url.rstrip('/'), username, quote(NC_ASSETS_ROOT, safe='/')
    )
    try:
        import requests as _req
        from requests.auth import HTTPBasicAuth
        r = _req.request('PROPFIND', propfind_url,
                         auth=HTTPBasicAuth(username, password),
                         headers={'Depth': '1', 'Content-Type': 'application/xml'},
                         timeout=15)
        if r.status_code not in [200, 207]:
            return JsonResponse({'folders': [], 'error': f'NC {r.status_code}'})
    except Exception as e:
        return JsonResponse({'folders': [], 'error': str(e)})

    folders = []
    base_prefix = f"/remote.php/dav/files/{username}/"
    root_href_suffix = quote(NC_ASSETS_ROOT, safe='/') + '/'
    try:
        root = ET.fromstring(r.text)
        ns = {'d': 'DAV:'}
        for resp_el in root.findall('.//d:response', ns):
            href = resp_el.findtext('d:href', '', ns)
            decoded = unquote(href)
            if not decoded.endswith('/'):
                continue  # skip files
            # Skip the root folder itself
            bp = decoded.find(base_prefix)
            if bp >= 0:
                rel = decoded[bp + len(base_prefix):]
            else:
                continue
            rel = rel.strip('/')
            if rel == NC_ASSETS_ROOT.strip('/') or not rel.startswith(NC_ASSETS_ROOT):
                continue
            folder_name = rel.split('/')[-1]
            if folder_name.startswith('.') or folder_name in ('_data', 'Studio_Work', 'Studio_Output'):
                continue
            folders.append({'name': folder_name, 'nc_path': rel})
    except Exception as e:
        return JsonResponse({'folders': [], 'error': f'XML: {e}'})

    folders.sort(key=lambda f: f['name'].lower())
    return JsonResponse({'folders': folders})


@login_required
def studio_nc_browse(request):
    """List images in a specific NC folder (subfolder of Octotrial_Assets)."""
    from posts_posted.nc_storage import _get_nc_credentials
    from urllib.parse import quote, unquote
    import xml.etree.ElementTree as ET

    folder = request.GET.get('folder', '').strip()
    q = request.GET.get('q', '').strip().lower()
    show_all = (folder == '__all__')

    if not folder:
        return JsonResponse({'items': [], 'subfolders': []})

    # Security: only allow browsing within Octotrial_Assets
    nc_folder = NC_ASSETS_ROOT if show_all else f"{NC_ASSETS_ROOT}/{folder}"
    if '..' in nc_folder:
        return JsonResponse({'items': [], 'error': 'Invalid path'})

    nc_url, username, password = _get_nc_credentials()
    if not all([nc_url, username, password]):
        return JsonResponse({'items': [], 'error': 'NC not configured'})

    propfind_url = "{}/remote.php/dav/files/{}/{}".format(
        nc_url.rstrip('/'), username, quote(nc_folder, safe='/')
    )
    try:
        import requests as _req
        from requests.auth import HTTPBasicAuth
        depth = 'infinity' if show_all else '1'
        r = _req.request('PROPFIND', propfind_url,
                         auth=HTTPBasicAuth(username, password),
                         headers={'Depth': depth, 'Content-Type': 'application/xml'},
                         timeout=30)
        if r.status_code == 507 and show_all:
            r = _req.request('PROPFIND', propfind_url,
                             auth=HTTPBasicAuth(username, password),
                             headers={'Depth': '1', 'Content-Type': 'application/xml'},
                             timeout=15)
        if r.status_code not in [200, 207]:
            return JsonResponse({'items': [], 'subfolders': [], 'error': f'NC {r.status_code}'})
    except Exception as e:
        return JsonResponse({'items': [], 'subfolders': [], 'error': str(e)})

    items = []
    subfolders = []
    IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.webm', '.mp4', '.mov'}
    base_prefix = f"/remote.php/dav/files/{username}/"
    root_href = f"/remote.php/dav/files/{username}/{quote(nc_folder, safe='/')}/"
    try:
        root = ET.fromstring(r.text)
        ns = {'d': 'DAV:'}
        for resp_el in root.findall('.//d:response', ns):
            href = resp_el.findtext('d:href', '', ns)
            decoded = unquote(href)
            # Skip the folder itself
            if decoded.rstrip('/') == unquote(root_href).rstrip('/'):
                continue
            name = decoded.rstrip('/').split('/')[-1]
            if name.startswith('.') or name in ('_data', 'Studio_Work', 'Studio_Output'):
                continue
            # Subfolders (skipped for __all__, which shows images only)
            if decoded.endswith('/'):
                if not show_all:
                    subfolders.append({'name': name})
                continue
            # Dateien
            ext = os.path.splitext(name)[1].lower()
            if ext not in IMAGE_EXTS:
                continue
            if q and q not in name.lower():
                continue
            bp = decoded.find(base_prefix)
            if bp >= 0:
                nc_path = decoded[bp + len(base_prefix):]
            else:
                nc_path = f"{nc_folder}/{name}"
            proxy_url = f"/library/studio/nc-image/?p={quote(nc_path, safe='/')}"
            title = os.path.splitext(name)[0].replace('_', ' ')
            # Pass the modification time along. It is in the answer we are
            # reading anyway, so it costs nothing - and it is the key for the
            # thumbnail: with it in the address, a changed file can never get an
            # old thumbnail from the cache, and unchanged files may be cached
            # permanently.
            stand = _zeitstempel(resp_el.findtext('.//d:getlastmodified', '', ns))
            eintrag = {'name': name, 'title': title, 'url': proxy_url, 'nc_path': nc_path}
            if ext in VORSCHAU_FAEHIG:
                eintrag['thumb'] = "/library/studio/thumb/?p=%s&t=%d&w=%d" % (
                    quote(nc_path, safe='/'), stand, VORSCHAU_BREITEN[0])
            items.append(eintrag)
    except Exception as e:
        return JsonResponse({'items': [], 'subfolders': [], 'error': f'XML: {e}'})

    subfolders.sort(key=lambda f: f['name'].lower())
    return JsonResponse({'items': items, 'subfolders': subfolders})


# ── Shared assets (the shared NC folder for the image pool) ──

NC_SHARED_ASSETS_FOLDER = "Marketing & Design/Bilder_Bibliothek"


@login_required
def studio_shared_assets_list(request):
    """List images from the shared NC folder via WebDAV PROPFIND.
    Supports ?folder=subfolder to list only a specific subfolder,
    and ?folders_only=1 to list only subfolder names (for dropdown)."""
    from posts_posted.nc_storage import _get_nc_credentials
    from urllib.parse import quote, unquote
    import xml.etree.ElementTree as ET

    nc_url, username, password = _get_nc_credentials()
    if not all([nc_url, username, password]):
        return JsonResponse({'error': 'Nextcloud not configured'}, status=500)

    # Ensure folder exists
    _nc_ensure_folder(nc_url, username, password, NC_SHARED_ASSETS_FOLDER)

    q = (request.GET.get('q') or '').strip().lower()
    subfolder = (request.GET.get('folder') or '').strip().strip('/')
    folders_only = request.GET.get('folders_only') == '1'

    # Always PROPFIND the base folder (with infinity) to get all subfolders + files
    propfind_url = "{}/remote.php/dav/files/{}/{}".format(
        nc_url.rstrip('/'), username, quote(NC_SHARED_ASSETS_FOLDER, safe='/')
    )
    # Use infinity to find all subfolders and files recursively
    depth = 'infinity'
    try:
        import requests as _req
        from requests.auth import HTTPBasicAuth
        r = _req.request('PROPFIND', propfind_url,
                         auth=HTTPBasicAuth(username, password),
                         headers={'Depth': depth, 'Content-Type': 'application/xml'},
                         timeout=30)
        if r.status_code == 507 and depth == 'infinity':
            # Some NC servers reject infinity, fall back to Depth:1
            r = _req.request('PROPFIND', propfind_url,
                             auth=HTTPBasicAuth(username, password),
                             headers={'Depth': '1', 'Content-Type': 'application/xml'},
                             timeout=30)
        if r.status_code not in [200, 207]:
            return JsonResponse({'items': [], 'error': f'NC {r.status_code}'})
    except Exception as e:
        return JsonResponse({'items': [], 'error': str(e)})

    # folders_only mode: return just subfolder names
    if folders_only:
        folder_names = []
        base_prefix = f"/remote.php/dav/files/{username}/"
        base_nc = NC_SHARED_ASSETS_FOLDER.rstrip('/')
        try:
            root = ET.fromstring(r.text)
            ns = {'d': 'DAV:'}
            for resp_el in root.findall('.//d:response', ns):
                href = resp_el.findtext('d:href', '', ns)
                decoded = unquote(href)
                if not decoded.endswith('/'):
                    continue
                bp = decoded.find(base_prefix)
                if bp >= 0:
                    nc_path = decoded[bp + len(base_prefix):].rstrip('/')
                else:
                    continue
                # Skip the base folder itself
                if nc_path == base_nc:
                    continue
                # Get relative name
                if nc_path.startswith(base_nc + '/'):
                    rel = nc_path[len(base_nc) + 1:]
                else:
                    rel = nc_path
                if rel:
                    folder_names.append(rel)
        except Exception as e:
            print(f"folders_only XML error: {e}")
            return JsonResponse({'folders': [], 'error': f'XML parse: {e}'})
        folder_names.sort()
        print(f"folders_only: found {len(folder_names)} folders: {folder_names[:10]}")
        return JsonResponse({'folders': folder_names})

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
            # Filter by selected subfolder
            if subfolder:
                if not rel.startswith(subfolder + '/') and rel != subfolder:
                    continue
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
        return JsonResponse({'error': 'Nextcloud not configured'}, status=500)

    f = request.FILES.get('file')
    if not f:
        return JsonResponse({'error': 'No file'}, status=400)

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

    # Also save to media_library_items (Studio-Elemente) for DB search/access
    try:
        title = os.path.splitext(filename)[0].replace('_', ' ')
        with connection.cursor() as c:
            c.execute(
                """INSERT INTO media_library_items (nc_path, title, series, tags, folder_id)
                   VALUES (%s, %s, %s, %s, NULL)""",
                [nc_path, title, '', 'upload,studio']
            )
            db_id = c.lastrowid
    except Exception:
        db_id = None

    return JsonResponse({'ok': True, 'name': filename, 'url': proxy_url, 'nc_path': nc_path, 'db_id': db_id})


NC_STUDIO_UPLOAD_FOLDER = "Marketing & Design/Octotrial_Assets/Studio_Work/Upload"


@login_required
def studio_upload(request):
    """Uploads a file into Studio_Work/Upload on Nextcloud and returns the proxy
    URL (to insert it into the canvas straight away). No database entry."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    from posts_posted.nc_storage import _get_nc_credentials
    from urllib.parse import quote
    nc_url, username, password = _get_nc_credentials()
    if not all([nc_url, username, password]):
        return JsonResponse({'error': 'Nextcloud not configured'}, status=500)

    f = request.FILES.get('file')
    if not f:
        return JsonResponse({'error': 'No file'}, status=400)

    filename = f.name.replace(' ', '_')
    content = f.read()
    # Avoid name collisions. An upload with the same name used to overwrite the
    # existing file by WebDAV PUT - and because saved designs remember only the
    # path, an older design then quietly showed the NEW image where the old one
    # had been. A short content hash makes the name unique without creating
    # duplicates when the content is identical.
    import hashlib as _hl
    _stamm, _punkt, _ext = filename.rpartition('.')
    if not _stamm:
        _stamm, _ext = filename, ''
    _kurz = _hl.sha1(content).hexdigest()[:8]
    filename = f"{_stamm}_{_kurz}{('.' + _ext) if _ext else ''}"
    nc_path = _nc_upload(content, f"{NC_STUDIO_UPLOAD_FOLDER}/{filename}",
                         f.content_type or 'image/png')
    if not nc_path:
        return JsonResponse({'error': 'Upload fehlgeschlagen'}, status=500)

    proxy_url = f"/library/studio/nc-image/?p={quote(nc_path, safe='/')}"
    return JsonResponse({'ok': True, 'name': filename, 'url': proxy_url, 'nc_path': nc_path})


@login_required
def studio_upload_delete(request):
    """Deletes a file from Studio_Work/Upload. Only inside that folder is
    allowed (for safety)."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    nc_path = (request.POST.get('nc_path') or '').strip()
    # Check traversal segment by segment (no path part ".."); two dots inside a
    # file name are fine. On top of that, restrict it to the upload folder.
    if any(seg == '..' for seg in nc_path.split('/')) \
            or not nc_path.startswith(NC_STUDIO_UPLOAD_FOLDER + '/'):
        return JsonResponse({'error': 'Invalid path'}, status=400)
    # The same here: do not report "ok" without looking. Otherwise the tile in
    # the upload area vanishes while the file stays where it is.
    ok, grund = _nc_delete_detail(nc_path)
    if not ok:
        return JsonResponse({'ok': False, 'error': grund or 'Deletion failed'}, status=502)
    return JsonResponse({'ok': True})


@login_required
def studio_output_delete(request):
    """Deletes a finished output (image/GIF/video) from Studio_Work/Output/*,
    preview and database entries included. Only inside the output folders."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    from urllib.parse import unquote
    # Normalise the path: tolerate leading slashes and URL encoding, so the
    # whitelist comparison does not fail on formalities.
    nc_path = unquote((request.POST.get('nc_path') or '').strip()).lstrip('/')
    if not _within_app_folders(nc_path):
        return JsonResponse({'ok': False, 'error': f'Invalid path: {nc_path}'}, status=400)

    # The file first, then the database - and only carry on once the file really
    # is gone. This used to read "_nc_delete(nc_path)" with no check, and an
    # unconditional ok:True underneath. When the deletion failed, the user saw
    # success all the same: the tile vanished from the view, the file stayed in
    # Nextcloud and was back on the next load. That is exactly how the
    # impression arises that something "cannot be deleted any more".
    ok, grund = _nc_delete_detail(nc_path)
    if not ok:
        return JsonResponse({'ok': False, 'error': grund or 'Deletion failed'}, status=502)

    # Remove the matching preview file too (best effort - its absence does not
    # make the deletion invalid)
    try:
        folder, fname = nc_path.rsplit('/', 1)
        stem = fname.rsplit('.', 1)[0]
        _nc_delete_aufraeumen(f"{folder}/{stem}_preview.png", 'Vorschau der Ausgabe')
    except Exception:
        pass
    # Remove the database entries
    try:
        with connection.cursor() as c:
            c.execute("DELETE FROM studio_images WHERE nc_path=%s", [nc_path])
            c.execute("DELETE FROM media_library_items WHERE nc_path=%s", [nc_path])
    except Exception as e:
        print("output delete db:", e)
    return JsonResponse({'ok': True})


@login_required
def studio_shared_assets_delete(request):
    """Delete an image from the shared NC assets folder."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    nc_path = request.POST.get('nc_path', '')
    if not nc_path or not nc_path.startswith(NC_SHARED_ASSETS_FOLDER):
        return JsonResponse({'error': 'Invalid path'}, status=400)
    from posts_posted.nc_storage import delete_image_from_nextcloud
    # This was checked here before - only the reason was missing, and without a
    # reason the user is back to a mute "it did not work".
    ok, grund = _nc_delete_detail(nc_path)
    if not ok:
        return JsonResponse({'ok': False, 'error': grund or 'Deletion failed'}, status=502)
    return JsonResponse({'ok': True})


NC_STUDIO_ELEMENTE_NC_FOLDER = "Marketing & Design/Octotrial_Assets/Studio_Elemente"


@login_required
def studio_db_item_to_nc(request):
    """Copy a DB-based Studio-Element image to NC so it's also in the NC library."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    item_id = request.POST.get('item_id')
    nc_folder = request.POST.get('nc_folder', NC_STUDIO_ELEMENTE_NC_FOLDER)
    if not item_id:
        return JsonResponse({'error': 'item_id required'}, status=400)

    _ensure_table()
    with connection.cursor() as c:
        rows = _safe(c, "SELECT id, nc_path, title FROM media_library_items WHERE id=%s", [item_id])
    if not rows:
        return JsonResponse({'error': 'Element not found'}, status=404)

    row = rows[0]
    existing_nc_path = row[1]
    title = row[2] or f"element_{item_id}"

    # Download the image from its current source
    from posts_posted.nc_storage import _get_nc_credentials, download_image_from_nextcloud
    from urllib.parse import quote
    import requests as _req
    from requests.auth import HTTPBasicAuth

    content, ct = download_image_from_nextcloud(existing_nc_path)
    if not content:
        # Try via library image endpoint (local DB proxy)
        return JsonResponse({'error': 'Image not loadable'}, status=500)

    nc_url, username, password = _get_nc_credentials()
    if not all([nc_url, username, password]):
        return JsonResponse({'error': 'Nextcloud not configured'}, status=500)

    _nc_ensure_folder(nc_url, username, password, nc_folder)

    filename = title.replace(' ', '_') + '.png'
    dest_path = f"{nc_folder}/{filename}"
    upload_url = "{}/remote.php/dav/files/{}/{}".format(
        nc_url.rstrip('/'), username, quote(dest_path, safe='/')
    )
    try:
        r = _req.put(upload_url, data=content,
                     auth=HTTPBasicAuth(username, password),
                     headers={'Content-Type': ct or 'image/png'},
                     timeout=60)
        if r.status_code not in [200, 201, 204]:
            return JsonResponse({'error': f'Upload fehlgeschlagen: {r.status_code}'}, status=500)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

    return JsonResponse({'ok': True, 'nc_path': dest_path})
