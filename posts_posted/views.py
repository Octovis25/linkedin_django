from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import connection
from django.http import HttpResponse, Http404
from .models import LinkedinPostPosted
from .forms import PostPostedForm
from .nc_storage import download_image_from_nextcloud


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
    return redirect("posts_posted:list")
