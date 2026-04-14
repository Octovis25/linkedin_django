from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import connection
from django.http import HttpResponse, Http404
from .models import LinkedinPostPosted
from .forms import PostPostedForm


@login_required
def post_list(request):
    """linkedin_posts ist die fuehrende Tabelle.
    Alle Posts werden angezeigt, auch wenn kein Eintrag
    in linkedin_posts_posted existiert (= kein Datum)."""
    query = request.GET.get("q", "").strip()

    sql = """
        SELECT
            lp.post_id,
            lp.post_title,
            lp.post_link,
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
            WHERE lp.post_id ILIKE %s
               OR lp.post_title ILIKE %s
               OR lp.post_link ILIKE %s
        """
        like = f"%{query}%"
        params = [like, like, like]

    sql += " ORDER BY COALESCE(pp.post_date, lp.post_date) DESC NULLS LAST, lp.post_id DESC"

    with connection.cursor() as cur:
        cur.execute(sql, params)
        columns = [col[0] for col in cur.description]
        rows = cur.fetchall()

    posts = []
    for row in rows:
        d = dict(zip(columns, row))
        posts.append({
            "post_id":    d["post_id"],
            "post_title": d.get("post_title") or "",
            "post_link":  d.get("post_link") or "",
            "post_date":  d.get("post_date"),
            "post_image": d.get("post_image") or "",
            "pp_id":      d.get("pp_id"),
            "has_date":   d.get("post_date") is not None,
        })

    return render(request, "posts_posted/list.html", {
        "posts": posts,
        "form": PostPostedForm(),
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
        messages.success(request, f"Post {post.post_id} geloescht.")
        return redirect("posts_posted:list")
    return render(request, "posts_posted/confirm_delete.html", {"post": post})
