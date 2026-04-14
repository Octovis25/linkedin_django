from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import connection
from django.db.models import Q
from django.http import HttpResponse, Http404
from .models import LinkedinPostPosted
from .forms import PostPostedForm
from .nc_storage import upload_image_to_nextcloud, download_image_from_nextcloud, delete_image_from_nextcloud


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
def post_edit(request, pk):
    post = get_object_or_404(LinkedinPostPosted, pk=pk)
    if request.method == "POST":
        form = PostPostedForm(request.POST, request.FILES, instance=post)
        if form.is_valid():
            try:
                obj = form.save(commit=False)

                # Handle image upload to Nextcloud
                upload_file = request.FILES.get('upload_image')
                if upload_file:
                    # Delete old image if exists
                    if obj.post_image:
                        delete_image_from_nextcloud(obj.post_image)

                    filename = f"{obj.post_id}_{upload_file.name}"
                    nc_path = upload_image_to_nextcloud(upload_file, filename)
                    if nc_path:
                        obj.post_image = nc_path
                        messages.success(request, "Aktualisiert + neues Bild hochgeladen!")
                    else:
                        messages.warning(request, "Aktualisiert, aber Bild-Upload fehlgeschlagen.")
                else:
                    messages.success(request, "Aktualisiert!")

                obj.save()
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
        # Delete image from Nextcloud too
        if post.post_image:
            delete_image_from_nextcloud(post.post_image)
        post.delete()
        messages.success(request, f"Post {post.post_id} geloescht.")
        return redirect("posts_posted:list")
    return render(request, "posts_posted/confirm_delete.html", {"post": post})


@login_required
def post_image_proxy(request, pk):
    """Proxy: Holt das Bild aus Nextcloud und liefert es aus.
    So braucht niemand direkten Nextcloud-Zugang."""
    post = get_object_or_404(LinkedinPostPosted, pk=pk)

    if not post.post_image:
        raise Http404("Kein Bild vorhanden")

    content, content_type = download_image_from_nextcloud(post.post_image)
    if content is None:
        raise Http404("Bild konnte nicht aus Nextcloud geladen werden")

    response = HttpResponse(content, content_type=content_type)
    response['Cache-Control'] = 'public, max-age=86400'  # 24h Cache
    return response
