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
            "post_link":        d.get("post_url") or "",
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
        form = PostPostedForm(request.POST, instance=post)
        if form.is_valid():
            try:
                form.save()
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
    content, content_type = download_image_from_nextcloud(post.post_image)
    if content is None:
        raise Http404("Bild konnte nicht aus Nextcloud geladen werden")
    response = HttpResponse(content, content_type=content_type)
    response['Cache-Control'] = 'public, max-age=86400'
    return response
