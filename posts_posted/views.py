from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import connection
from .models import LinkedinPostPosted
from .forms import PostPostedForm


class PostRow:
    """Leichtgewichtiges Objekt fuer Template-Zugriff."""
    def __init__(self, data):
        for k, v in data.items():
            setattr(self, k, v)
        self.pk = data.get("posted_pk") or data.get("post_id")


@login_required
def post_list(request):
    query = request.GET.get("q", "").strip()

    sql = """
        SELECT
            lp.post_id,
            COALESCE(lp.post_title, lp.post_title_raw, '') AS post_title,
            lp.post_url                                     AS post_link,
            lp.created_at,
            pp.post_date,
            pp.post_image,
            pp.id                                            AS posted_pk
        FROM linkedin_posts lp
        LEFT JOIN linkedin_posts_posted pp ON pp.post_id = lp.post_id
    """
    params = []
    if query:
        sql += """
        WHERE lp.post_id LIKE %s
           OR COALESCE(lp.post_title, lp.post_title_raw, '') LIKE %s
           OR COALESCE(lp.post_url, '') LIKE %s
        """
        like = f"%{query}%"
        params = [like, like, like]

    sql += " ORDER BY COALESCE(pp.post_date, lp.post_date, lp.created_at) DESC"

    with connection.cursor() as cur:
        cur.execute(sql, params)
        columns = [col[0] for col in cur.description]
        rows = cur.fetchall()

    posts = [PostRow(dict(zip(columns, row))) for row in rows]

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
    # pk kann posted_pk (int) oder post_id (string) sein
    posted = None
    post_id = str(pk)

    # Versuche erst linkedin_posts_posted zu finden
    try:
        posted = LinkedinPostPosted.objects.get(pk=int(pk))
        post_id = posted.post_id
    except (LinkedinPostPosted.DoesNotExist, ValueError):
        # pk ist eine post_id — evtl. noch kein Eintrag in posts_posted
        posted = LinkedinPostPosted.objects.filter(post_id=post_id).first()

    # Post-Info aus linkedin_posts holen
    with connection.cursor() as cur:
        cur.execute(
            "SELECT post_id, COALESCE(post_title, post_title_raw, '') AS post_title, "
            "post_url, created_at FROM linkedin_posts WHERE post_id = %s",
            [post_id]
        )
        row = cur.fetchone()

    post_info = {}
    if row:
        post_info = {"post_id": row[0], "post_title": row[1],
                     "post_link": row[2], "created_at": row[3]}

    if request.method == "POST":
        new_date = request.POST.get("post_date", "").strip()
        new_image = request.FILES.get("post_image")
        try:
            from datetime import date as dt_date
            if posted is None:
                # Noch kein Eintrag in linkedin_posts_posted -> neu anlegen
                posted = LinkedinPostPosted()
                posted.post_id = post_id
                posted.post_link = post_info.get("post_link", "")
            if new_date:
                posted.post_date = dt_date.fromisoformat(new_date)
            if new_image:
                posted.post_image = new_image
            posted.save()
            messages.success(request, "Aktualisiert!")
        except Exception as e:
            messages.error(request, str(e))
        return redirect("posts_posted:list")

    # Template-Kontext
    class EditPost:
        pass
    p = EditPost()
    p.post_id = post_info.get("post_id", post_id)
    p.post_title = post_info.get("post_title", "")
    p.post_link = post_info.get("post_link", "")
    p.post_date = posted.post_date if posted else None
    p.post_image = posted.post_image if posted else None
    p.pk = posted.pk if posted else post_id

    return render(request, "posts_posted/edit.html", {"post": p})


@login_required
def post_delete(request, pk):
    post = get_object_or_404(LinkedinPostPosted, pk=pk)
    if request.method == "POST":
        post.delete()
        messages.success(request, f"Post {post.post_id} geloescht.")
        return redirect("posts_posted:list")
    return render(request, "posts_posted/confirm_delete.html", {"post": post})
