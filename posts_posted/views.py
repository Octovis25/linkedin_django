import json
import re
import io
import urllib.request
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.db import connection
from django.contrib import messages
from django.http import HttpResponse, Http404, JsonResponse
from django.views.decorators.http import require_POST
from .models import LinkedinPostPosted
from .forms import PostPostedForm
from .nc_storage import download_image_from_nextcloud


def _norm_text(s):
    """Normalisiert Text fuer den Match (Kleinbuchstaben, nur a-z0-9, erste 25)."""
    return re.sub(r'[^a-z0-9]', '', (s or '').lower())[:25]


def fill_missing_post_images():
    """Fuellt fehlende Overview-Bilder (linkedin_posts_posted.post_image) automatisch
    mit dem passenden Buffer-Thumbnail (per Text-Match). Nur LEERE Bilder werden gesetzt.
    Gibt (gefuellt, geprueft, fehler) zurueck."""
    from .nc_storage import upload_image_to_nextcloud

    filled, checked, errors, dates_filled = 0, 0, 0, 0

    # --- Alle benoetigten Daten EINMAL laden ---
    with connection.cursor() as c:
        c.execute("""
            SELECT post_text, thumbnail_url, LEFT(sent_at,10) AS sd
            FROM buffer_posts_posted
            WHERE post_text IS NOT NULL AND post_text<>''
        """)
        buf, buf_dates = [], []
        for t, th, sd in c.fetchall():
            k = _norm_text(t)
            if not k:
                continue
            if th:
                buf.append((k, th))
            if sd:
                buf_dates.append((k, sd))

        # ALLE Posts (Titel + aktuelles Datum + Bildstatus).
        c.execute("""
            SELECT lp.post_id, lp.post_title, pp.id,
                   CAST(pp.post_date AS CHAR), pp.post_image
            FROM linkedin_posts lp
            LEFT JOIN linkedin_posts_posted pp ON lp.post_id = pp.post_id
            WHERE lp.post_title IS NOT NULL
        """)
        rows = c.fetchall()

    # --- 1) DATUM: Buffer-Datum hat Vorrang, ueberschreibt auch falsches ---
    for post_id, title, pp_id, cur_date, _img in rows:
        key = _norm_text(title)
        if not key:
            continue
        bd = next((d for bk, d in buf_dates if bk and (bk.startswith(key) or key.startswith(bk))), None)
        if not bd:
            continue
        if cur_date and str(cur_date)[:10] == str(bd)[:10]:
            continue  # schon korrekt
        try:
            with connection.cursor() as c3:
                if pp_id:
                    c3.execute("UPDATE linkedin_posts_posted SET post_date=%s WHERE id=%s", [bd, pp_id])
                else:
                    c3.execute("INSERT INTO linkedin_posts_posted (post_id, post_date) VALUES (%s,%s)",
                               [post_id, bd])
            dates_filled += 1
        except Exception:
            pass

    # --- 2) BILD: nur LEERE Bilder mit Buffer-Thumbnail fuellen ---
    for post_id, title, pp_id, _cur_date, post_image in rows:
        if post_image:
            continue  # Bild vorhanden -> nicht anfassen
        checked += 1
        key = _norm_text(title)
        if not key:
            continue
        thumb = next((th for bk, th in buf if bk and (bk.startswith(key) or key.startswith(bk))), None)
        if not thumb:
            continue
        try:
            req = urllib.request.Request(thumb, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read()
            if not data:
                continue
            bio = io.BytesIO(data)
            bio.content_type = 'image/jpeg'
            filename = f"buffer_auto_{post_id}.jpg"
            nc_path = upload_image_to_nextcloud(bio, filename)
            if not nc_path:
                errors += 1
                continue
            with connection.cursor() as c2:
                if pp_id:
                    c2.execute("UPDATE linkedin_posts_posted SET post_image=%s WHERE id=%s", [nc_path, pp_id])
                else:
                    c2.execute("INSERT INTO linkedin_posts_posted (post_id, post_image) VALUES (%s,%s)",
                               [post_id, nc_path])
            filled += 1
        except Exception:
            errors += 1

    return filled, checked, errors, dates_filled


@login_required
@require_POST
def buffer_fill_images(request):
    """Button-Aktion: fehlende Overview-Bilder + Daten automatisch aus Buffer befuellen."""
    try:
        filled, checked, errors, dates_filled = fill_missing_post_images()
        return JsonResponse({'ok': True, 'filled': filled, 'checked': checked,
                             'errors': errors, 'dates_filled': dates_filled})
    except Exception as e:
        return JsonResponse({'ok': False, 'error': str(e)}, status=500)


def _ensure_repost_column():
    """Stellt sicher, dass buffer_posts_posted eine is_repost-Spalte hat."""
    with connection.cursor() as c:
        try:
            c.execute("ALTER TABLE buffer_posts_posted ADD COLUMN is_repost TINYINT DEFAULT 0")
        except Exception:
            pass  # Spalte existiert bereits


@login_required
@require_POST
def buffer_toggle_repost(request):
    """Schaltet das Repost-Flag eines Buffer-Posts um (vom OJ-Tab aufgerufen)."""
    _ensure_repost_column()
    try:
        data = json.loads(request.body or '{}')
    except Exception:
        data = {}
    bpid = data.get('buffer_post_id')
    if not bpid:
        return JsonResponse({'ok': False, 'error': 'buffer_post_id fehlt'}, status=400)
    with connection.cursor() as c:
        c.execute("SELECT COALESCE(is_repost,0) FROM buffer_posts_posted WHERE buffer_post_id=%s", [bpid])
        row = c.fetchone()
        if not row:
            return JsonResponse({'ok': False, 'error': 'Post nicht gefunden'}, status=404)
        new_val = 0 if row[0] else 1
        c.execute("UPDATE buffer_posts_posted SET is_repost=%s WHERE buffer_post_id=%s", [new_val, bpid])
    return JsonResponse({'ok': True, 'is_repost': bool(new_val)})


@login_required
def post_list(request):
    # Auto-Sync: fehlende Posts + post_title aktualisieren
    from django.db import connection as _c
    with _c.cursor() as cur:
        cur.execute("""
            INSERT IGNORE INTO linkedin_posts_posted (post_id, post_url, post_date, post_title)
            SELECT lp.post_id, lp.post_url, lp.post_date, lp.post_title
            FROM linkedin_posts lp
            LEFT JOIN linkedin_posts_posted pp ON lp.post_id = pp.post_id
            WHERE pp.post_id IS NULL
              AND lp.post_id IS NOT NULL
              AND lp.post_url IS NOT NULL
        """)
        cur.execute("""
            UPDATE linkedin_posts_posted pp
            JOIN linkedin_posts lp ON pp.post_id = lp.post_id
            SET pp.post_title = lp.post_title
            WHERE pp.post_title IS NULL OR pp.post_title = ''
        """)
    # Auto-Sync: fehlende Posts aus linkedin_posts eintragen
    from django.db import connection as _c
    with _c.cursor() as cur:
        cur.execute("""
            INSERT IGNORE INTO linkedin_posts_posted (post_id, post_url, post_date)
            SELECT lp.post_id, lp.post_url, lp.post_date
            FROM linkedin_posts lp
            LEFT JOIN linkedin_posts_posted pp ON lp.post_id = pp.post_id
            WHERE pp.post_id IS NULL
              AND lp.post_id IS NOT NULL
              AND lp.post_url IS NOT NULL
        """)
    """linkedin_posts ist die fuehrende Tabelle (alle Posts)."""
    query = request.GET.get("q", "").strip()

    sql = """
        SELECT
            lp.post_id,
            lp.post_title,
            lp.post_url,
            pp.post_date,
            pp.post_image,
            pp.id AS pp_id
        FROM linkedin_posts lp
        LEFT JOIN linkedin_posts_posted pp
            ON lp.post_id = pp.post_id
    """
    params = []

    if query:
        sql += """
            WHERE lp.post_id LIKE %s
               OR lp.post_title LIKE %s
               OR lp.post_url LIKE %s
        """
        like = "%%{}%%".format(query)
        params = [like, like, like]

    sql += """
        ORDER BY
            pp.post_date IS NOT NULL, lp.post_date IS NOT NULL,
            COALESCE(pp.post_date, lp.post_date) DESC,
            lp.post_id DESC
    """

    with connection.cursor() as cur:
        cur.execute(sql, params)
        columns = [col[0] for col in cur.description]
        rows = cur.fetchall()

    posts = []
    for row in rows:
        d = dict(zip(columns, row))
        pd = d.get("post_date")
        posts.append({
            "post_id":          d["post_id"],
            "post_title":       d.get("post_title") or "",
            "post_url":        d.get("post_url") or "",
            "post_date":        pd,
            "post_date_formatted": pd.strftime("%d.%m.%Y") if pd else "",
            "post_image":       d.get("post_image") or "",
            "pp_id":            d.get("pp_id"),
            "has_date":         pd is not None,
        })

    return render(request, "posts_posted/list.html", {
        "posts": posts,
        "query": query,
    })


@login_required
def buffer_post_list(request):
    """
    Tab 'Buffer Posts Posted': liest aus der Tabelle buffer_posts_posted,
    die beim Upload und taeglich per Cron mit fetch_buffer_posts befuellt wird.
    Spalten wie bei 'Posts Posted' (Text, Bild, ID, LinkedIn-Link), ohne Bearbeiten.
    """
    error = None
    posts = []
    last_fetch = None

    # Octovis-Firmenchannel aus dem Token holen (buffer_profile_id = Firma).
    octovis_channel = None
    with connection.cursor() as c:
        try:
            c.execute("""
                SELECT t.buffer_profile_id
                FROM planner_linkedin_tokens t
                JOIN auth_user u ON t.user_id = u.id
                WHERE u.is_superuser = 1 AND t.buffer_profile_id IS NOT NULL
                LIMIT 1
            """)
            row = c.fetchone()
            octovis_channel = row[0] if row else None
        except Exception:
            octovis_channel = None

    with connection.cursor() as c:
        try:
            # Nur Octovis-Firmenposts (channel) und nur ab 2023.
            sql = """
                SELECT buffer_post_id, post_text, status, sent_at,
                       planner_post_id, has_image, linkedin_url, thumbnail_url, updated_at
                FROM buffer_posts_posted
                WHERE (sent_at IS NULL OR sent_at >= '2023-01-01')
            """
            params = []
            if octovis_channel:
                sql += " AND channel_id = %s"
                params.append(octovis_channel)
            sql += " ORDER BY sent_at DESC, id DESC"
            c.execute(sql, params)
            for bpid, text, status, sent_at, pid, has_image, link, thumb, updated in c.fetchall():
                if updated and (last_fetch is None or updated > last_fetch):
                    last_fetch = updated
                s = sent_at or ''
                posts.append({
                    "buffer_post_id": bpid,
                    "text": text or '',
                    "status": status or '',
                    "sent_at": s[:10] if s else '',
                    "planner_id": pid,
                    "has_image": bool(has_image),
                    "thumbnail_url": thumb or '',
                    "link": link or '',
                })
        except Exception as e:
            # Tabelle existiert noch nicht -> Hinweis, dass der Abruf laufen muss.
            if 'buffer_posts_posted' in str(e):
                error = ("Noch keine Buffer-Posts in der Datenbank. Bitte einmal "
                         "'python manage.py fetch_buffer_posts' ausfuehren.")
            else:
                error = "Fehler beim Lesen: {}".format(e)

    if not posts and not error:
        error = ("Noch keine Buffer-Posts in der Datenbank. Bitte einmal "
                 "'python manage.py fetch_buffer_posts' ausfuehren.")

    return render(request, "posts_posted/list_buffer.html", {
        "posts": posts,
        "error": error,
        "last_fetch": last_fetch,
    })


@login_required
def post_add(request):
    if request.method == "POST":
        form = PostPostedForm(request.POST)
        if form.is_valid():
            try:
                form.save()
                messages.success(request, "Post-Datum gespeichert!")
            except Exception as e:
                messages.error(request, str(e))
        else:
            for errs in form.errors.values():
                for e in errs:
                    messages.error(request, e)
    return redirect("posts_posted:list")


@login_required
def post_edit(request, pk):
    post = get_object_or_404(LinkedinPostPosted, pk=pk)
    if request.method == "POST":
        form = PostPostedForm(request.POST, request.FILES, instance=post)
        if form.is_valid():
            try:
                # Datum direkt per SQL speichern (umgeht full_clean/post_url-Validierung)
                new_date = form.cleaned_data.get('post_date')
                with connection.cursor() as cur:
                    cur.execute(
                        'UPDATE linkedin_posts_posted SET post_date=%s WHERE id=%s',
                        [new_date, post.pk]
                    )
                # Bild hochladen falls vorhanden
                upload_file = request.FILES.get("upload_image")
                if upload_file:
                    from .nc_storage import upload_image_to_nextcloud
                    import os, tempfile
                    suffix = os.path.splitext(upload_file.name)[1]
                    filename = "post_{}{}".format(post.post_id, suffix)
                    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                        for chunk in upload_file.chunks():
                            tmp.write(chunk)
                        tmp_path = tmp.name
                    try:
                        with open(tmp_path, 'rb') as img_f:
                            nc_path = upload_image_to_nextcloud(img_f, filename)
                        if nc_path:
                            with connection.cursor() as cur:
                                cur.execute(
                                    "UPDATE linkedin_posts_posted SET post_image=%s WHERE id=%s",
                                    [nc_path, post.pk]
                                )
                            messages.success(request, "Bild gespeichert!")
                        else:
                            messages.error(request, "Nextcloud-Upload fehlgeschlagen!")
                    finally:
                        os.unlink(tmp_path)
                messages.success(request, "Aktualisiert!")
            except Exception as e:
                messages.error(request, str(e))
            return redirect("posts_posted:list")
    else:
        form = PostPostedForm(instance=post)
    return render(request, "posts_posted/edit.html", {"form": form, "post": post})


@login_required
def post_delete(request, pk):
    post = get_object_or_404(LinkedinPostPosted, pk=pk)
    if request.method == "POST":
        post.delete()
        messages.success(request, "Post {} geloescht.".format(post.post_id))
        return redirect("posts_posted:list")
    return render(request, "posts_posted/confirm_delete.html", {"post": post})


@login_required
def post_image_proxy(request, pk):
    """Proxy: Holt das Bild aus Nextcloud und liefert es aus."""
    post = get_object_or_404(LinkedinPostPosted, pk=pk)
    if not post.post_image:
        raise Http404("Kein Bild vorhanden")
    nc_path = str(post.post_image)
    content, content_type = download_image_from_nextcloud(nc_path)
    if content is None:
        raise Http404("Bild konnte nicht aus Nextcloud geladen werden")
    response = HttpResponse(content, content_type=content_type)
    response['Cache-Control'] = 'public, max-age=86400'
    return response


@login_required
def post_delete_image(request, pk):
    """Löscht das Bild eines Posts (Nextcloud + DB)."""
    from django.db import connection as _conn
    from .nc_storage import delete_image_from_nextcloud
    with _conn.cursor() as cur:
        cur.execute("SELECT post_url, post_image FROM linkedin_posts_posted WHERE id = %s", [pk])
        row = cur.fetchone()
    if not row:
        messages.error(request, "Post nicht gefunden.")
        return redirect("posts_posted:list")
    post_url, nc_path = row
    if nc_path:
        delete_image_from_nextcloud(nc_path)
        with _conn.cursor() as cur:
            cur.execute("UPDATE linkedin_posts_posted SET post_image = NULL WHERE id = %s", [pk])
        messages.success(request, "Bild gelöscht.")
    else:
        messages.info(request, "Kein Bild vorhanden.")
    return redirect("posts_posted:list