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
    posts = LinkedinPostPosted.objects.all().order_by('-post_date', '-created_at')
    if query:
        posts = posts.filter(Q(post_link__icontains=query)|Q(post_id__icontains=query))

    # post_title aus linkedin_posts dazu mergen
    post_ids = [p.post_id for p in posts if p.post_id]
    title_map = {}
    if post_ids:
        placeholders = ','.join(['%s'] * len(post_ids))
        with connection.cursor() as cur:
            cur.execute(f"SELECT post_id, post_title FROM linkedin_posts WHERE post_id IN ({placeholders})", post_ids)
            for row in cur.fetchall():
                title_map[row[0]] = row[1]

    for p in posts:
        p.post_title = title_map.get(p.post_id, '')

    return render(request, "posts_posted/list.html", {"posts": posts, "form": PostPostedForm(), "query": query})

@login_required
def post_add(request):
    if request.method == "POST":
        form = PostPostedForm(request.POST)
        if form.is_valid():
            try: form.save(); messages.success(request, "Post-Datum gespeichert!")
            except Exception as e: messages.error(request, str(e))
        else:
            for errs in form.errors.values():
                for e in errs: messages.error(request, e)
    return redirect("posts_posted:list")

@login_required
def post_edit(request, pk):
    post = get_object_or_404(LinkedinPostPosted, pk=pk)
    if request.method == "POST":
        form = PostPostedForm(request.POST, instance=post)
        if form.is_valid():
            try: form.save(); messages.success(request, "Aktualisiert!")
            except Exception as e: messages.error(request, str(e))
            return redirect("posts_posted:list")
    else: form = PostPostedForm(instance=post)
    return render(request, "posts_posted/edit.html", {"form": form, "post": post})

@login_required
def post_delete(request, pk):
    post = get_object_or_404(LinkedinPostPosted, pk=pk)
    if request.method == "POST":
        post.delete(); messages.success(request, f"Post {post.post_id} geloescht.")
        return redirect("posts_posted:list")
    return render(request, "posts_posted/confirm_delete.html", {"post": post})
