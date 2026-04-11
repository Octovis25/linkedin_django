from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q
from .models import LinkedinPostPosted
from .forms import PostPostedForm

@login_required
def post_list(request):
    query = request.GET.get("q", "").strip()
    posts = LinkedinPostPosted.objects.all()
    if query: posts = posts.filter(Q(post_link__icontains=query)|Q(post_id__icontains=query))
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
