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
                CREATE TABLE IF NOT EXISTS media_library_items (
                    id         INT AUTO_INCREMENT PRIMARY KEY,
                    nc_path    VARCHAR(512) NOT NULL,
                    title      VARCHAR(255) DEFAULT '',
                    person     VARCHAR(100) DEFAULT '',
                    series     VARCHAR(100) DEFAULT '',
                    tags       VARCHAR(255) DEFAULT '',
                    note       TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
        except Exception:
            pass


def _all_items(filters=None):
    filters = filters or {}
    sql = "SELECT id, nc_path, title, person, series, tags, note, created_at FROM media_library_items WHERE 1=1"
    params = []
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
         'tags': r[5] or '', 'note': r[6] or '',
         'created_at': r[7]}
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
    }
    items   = _all_items(f)
    persons, series, tags = _meta_options()
    return render(request, 'media_library/library.html', {
        'items': items, 'persons': persons, 'series_list': series, 'tags': tags,
        'filter_person': f['person'], 'filter_series': f['series'],
        'filter_tag': f['tag'], 'filter_q': f['q'],
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

    from posts_posted.nc_storage import upload_image_to_nextcloud
    suffix   = os.path.splitext(image.name)[1] or '.jpg'
    import time
    filename = f"lib_{int(time.time())}{suffix}"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        for chunk in image.chunks():
            tmp.write(chunk)
        tmp_path = tmp.name
    try:
        with open(tmp_path, 'rb') as f_obj:
            class _Wrap:
                def __init__(self, fobj, ct): self._f = fobj; self.content_type = ct
                def read(self): return self._f.read()
            nc_path_base = NC_LIBRARY_FOLDER + "/" + filename
            from urllib.parse import quote
            from requests.auth import HTTPBasicAuth
            import requests as _req
            from posts_posted.nc_storage import _get_nc_credentials
            nc_url, username, password = _get_nc_credentials()
            content = f_obj.read()
        if nc_url and username and password:
            upload_url = f"{nc_url}/remote.php/dav/files/{username}/{quote(nc_path_base, safe='/')}"
            r = _req.put(upload_url, data=content,
                auth=HTTPBasicAuth(username, password),
                headers={"Content-Type": image.content_type or "image/jpeg"},
                timeout=30)
            if r.status_code in [200, 201, 204]:
                nc_path = nc_path_base
            else:
                messages.error(request, f'Nextcloud-Upload fehlgeschlagen: HTTP {r.status_code}')
                return redirect('media_library:library')
        else:
            messages.error(request, 'Nextcloud nicht verbunden.')
            return redirect('media_library:library')
    finally:
        os.unlink(tmp_path)

    with connection.cursor() as c:
        c.execute("""INSERT INTO media_library_items (nc_path, title, person, series, tags, note)
                     VALUES (%s,%s,%s,%s,%s,%s)""",
                  [nc_path, title, person, series, tags, note or None])
    messages.success(request, 'Bild gespeichert!')
    return redirect('media_library:library')


@login_required
def library_image(request, item_id):
    with connection.cursor() as c:
        rows = _safe(c, "SELECT nc_path FROM media_library_items WHERE id=%s", [item_id])
    if not rows:
        raise Http404
    nc_path = rows[0][0]
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
        from posts_posted.nc_storage import delete_image_from_nextcloud
        delete_image_from_nextcloud(rows[0][0])
        with connection.cursor() as c:
            c.execute("DELETE FROM media_library_items WHERE id=%s", [item_id])
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
    persons, series, tags = _meta_options()
    data = []
    for item in items:
        data.append({
            'id':     item['id'],
            'title':  item['title'],
            'person': item['person'],
            'series': item['series'],
            'tags':   item['tags'],
            'url':    f"/library/image/{item['id']}/",
        })
    return JsonResponse({'items': data, 'persons': persons, 'series': series, 'tags': tags})
