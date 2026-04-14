from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import connection
from django.db.models import Q
from .models import LinkedinPostPosted
from .forms import PostPostedForm

@login_required
def post_list(request):
    query = request.GET.get("q", "").strip()
    posts = list(LinkedinPostPosted.objects.all().order_by('-post_date'))

    post_ids = [p.post_id for p in posts if p.post_id]
    title_map = {}
    if post_ids:
        placeholders = ','.join(['%s'] * len(post_ids))
        with connection.cursor() as cur:
            cur.execute(
                f"SELECT post_id, COALESCE(post_title, post_title_raw, '') "
                f"FROM linkedin_posts WHERE post_id IN ({placeholders})",
                post_ids
            )
            for row in cur.fetchall():
                title_map[row[0]] = row[1] or ''

    for p in posts:
        p.post_title = title_map.get(p.post_id, '')

    if query:
        q_lower = query.lower()
        posts = [p for p in posts
                 if q_lower in (p.post_title or '').lower()
                 or q_lower in (p.post_id or '').lower()
                 or q_lower in (p.post_link or '').lower()]

    return render(request, "posts_posted/list.html", {
        "posts": posts, "form": PostPostedForm(), "query": query
    })

@login_required
def post_add(request):
    if request.method == "POST":
        form = PostPostedForm(request.POST, request.FILES)
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
        # Datum direkt aus dem Formular lesen
        new_date = request.POST.get("post_date", "").strip()
        new_image = request.FILES.get("post_image")
        try:
            if new_date:
                from datetime import date as dt_date
                post.post_date = dt_date.fromisoformat(new_date)
            if new_image:
                post.post_image = new_image
            post.save()
            messages.success(request, "Aktualisiert!")
        except Exception as e:
            messages.error(request, str(e))
        return redirect("posts_posted:list")
    return render(request, "posts_posted/edit.html", {"post": post})

@login_required
def post_delete(request, pk):
    post = get_object_or_404(LinkedinPostPosted, pk=pk)
    if request.method == "POST":
        post.delete()
        messages.success(request, f"Post {post.post_id} geloescht.")
        return redirect("posts_posted:list")
    return render(request, "posts_posted/confirm_delete.html", {"post": post})
