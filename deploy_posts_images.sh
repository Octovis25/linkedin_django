#!/usr/bin/env bash
set -euo pipefail

echo "=== 1) nc_storage.py erstellen ==="
cat > posts_posted/nc_storage.py << 'PYEOF'
"""
Nextcloud WebDAV Storage for Post Images.
Uploads images to: Marketing & Design/LinkedIn/Post-Bilder/
Proxies images back through Django (no public Nextcloud link needed).
"""
import os
import requests
from requests.auth import HTTPBasicAuth
from urllib.parse import quote

NC_IMAGE_FOLDER = "Marketing & Design/LinkedIn/Post-Bilder"

def _get_nc_credentials():
    try:
        from collectives.views import get_config_with_env
        config = get_config_with_env()
        return config.nextcloud_url, config.username, config.app_password
    except Exception:
        url = os.environ.get('NEXTCLOUD_URL', '').strip()
        user = os.environ.get('NEXTCLOUD_USER', '').strip()
        pw = os.environ.get('NEXTCLOUD_APP_PASSWORD', '').strip()
        return url, user, pw

def _ensure_folder_exists(nc_url, username, password):
    parts = NC_IMAGE_FOLDER.split("/")
    current = ""
    for part in parts:
        current = "{}/{}".format(current, part) if current else part
        folder_url = "{}/remote.php/dav/files/{}/{}/".format(nc_url, username, quote(current))
        requests.request('MKCOL', folder_url, auth=HTTPBasicAuth(username, password), timeout=10)

def upload_image_to_nextcloud(image_file, filename):
    nc_url, username, password = _get_nc_credentials()
    if not all([nc_url, username, password]):
        return None
    try:
        _ensure_folder_exists(nc_url, username, password)
        safe_filename = filename.replace(" ", "_")
        nc_path = "{}/{}".format(NC_IMAGE_FOLDER, safe_filename)
        upload_url = "{}/remote.php/dav/files/{}/{}".format(nc_url, username, quote(nc_path))
        content = image_file.read()
        r = requests.put(upload_url, data=content, auth=HTTPBasicAuth(username, password),
            headers={'Content-Type': getattr(image_file, 'content_type', 'image/png')}, timeout=30)
        if r.status_code in [200, 201, 204]:
            return nc_path
        return None
    except Exception as e:
        print("Nextcloud upload error: {}".format(e))
        return None

def download_image_from_nextcloud(nc_path):
    nc_url, username, password = _get_nc_credentials()
    if not all([nc_url, username, password]):
        return None, None
    try:
        download_url = "{}/remote.php/dav/files/{}/{}".format(nc_url, username, quote(nc_path))
        r = requests.get(download_url, auth=HTTPBasicAuth(username, password), timeout=30)
        if r.status_code == 200:
            return r.content, r.headers.get('Content-Type', 'image/png')
        return None, None
    except Exception:
        return None, None

def delete_image_from_nextcloud(nc_path):
    nc_url, username, password = _get_nc_credentials()
    if not all([nc_url, username, password]):
        return False
    try:
        delete_url = "{}/remote.php/dav/files/{}/{}".format(nc_url, username, quote(nc_path))
        r = requests.delete(delete_url, auth=HTTPBasicAuth(username, password), timeout=10)
        return r.status_code in [200, 204]
    except Exception:
        return False
PYEOF
echo "  -> nc_storage.py erstellt"

echo "=== 2) views.py aktualisieren ==="
cat > posts_posted/views.py << 'PYEOF'
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
            CASE WHEN pp.post_date IS NULL AND lp.post_date IS NULL THEN 0 ELSE 1 END,
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
PYEOF
echo "  -> views.py mit image_proxy erstellt"

echo "=== 3) urls.py aktualisieren ==="
cat > posts_posted/urls.py << 'PYEOF'
from django.urls import path
from . import views

app_name = "posts_posted"

urlpatterns = [
    path("", views.post_list, name="list"),
    path("add/", views.post_add, name="add"),
    path("<int:pk>/edit/", views.post_edit, name="edit"),
    path("<int:pk>/delete/", views.post_delete, name="delete"),
    path("<int:pk>/image/", views.post_image_proxy, name="image_proxy"),
]
PYEOF
echo "  -> urls.py mit image_proxy Route"

echo "=== 4) list.html aktualisieren ==="
mkdir -p posts_posted/templates/posts_posted
cat > posts_posted/templates/posts_posted/list.html << 'HTMLEOF'
{% extends "core/base.html" %}
{% block title %}Post-Datum-Zuordnung{% endblock %}
{% block content %}
<style>
.post-title-cell {
    max-width: 300px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}
.copy-link-btn {
    cursor: pointer;
    margin-left: 0.3rem;
    color: var(--octo-petrol);
    text-decoration: none;
    font-size: 1rem;
}
.copy-link-btn:hover { color: var(--octo-orange); }
.actions-cell .btn { font-size: 0.75rem; padding: 0.25rem 0.6rem; }
.no-date { color: #e74c3c; font-style: italic; }

/* Thumbnail mit Hover-Zoom */
.thumb-wrap {
    position: relative;
    display: inline-block;
}
.thumb-wrap img.thumb {
    max-height: 40px;
    max-width: 60px;
    border-radius: 4px;
    cursor: pointer;
    transition: transform 0.2s;
}
.thumb-wrap .thumb-large {
    display: none;
    position: absolute;
    bottom: 100%;
    left: 50%;
    transform: translateX(-50%);
    z-index: 1000;
    border: 3px solid var(--octo-petrol);
    border-radius: 8px;
    box-shadow: 0 8px 24px rgba(0,0,0,0.3);
    background: #fff;
    max-width: 400px;
    max-height: 350px;
}
.thumb-wrap:hover .thumb-large {
    display: block;
}
</style>

<div class="card">
<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem">
<h2 style="margin:0">Alle Posts ({{ posts|length }})</h2>
<form style="display:flex;gap:.5rem;width:300px">
<input type="text" name="q" value="{{ query }}" class="form-input" placeholder="Suche...">
<button type="submit" class="btn btn-secondary btn-sm">Suchen</button>
</form></div>

<table>
<thead><tr>
    <th>Post-ID</th>
    <th>Post-Titel</th>
    <th>Post-Link</th>
    <th>Gepostet am</th>
    <th>Bild</th>
    <th>Aktionen</th>
</tr></thead>
<tbody>
{% for p in posts %}
<tr>
    <td><span class="badge">{{ p.post_id }}</span></td>
    <td class="post-title-cell" title="{{ p.post_title }}">{{ p.post_title|default:"-"|truncatechars:80 }}</td>
    <td>
        {% if p.post_link %}
        <a href="{{ p.post_link }}" target="_blank" title="{{ p.post_link }}">&#x1F517; LinkedIn</a>
        <a href="#" class="copy-link-btn" title="Link kopieren" onclick="copyLink('{{ p.post_link }}', event)">&#x1F4CB;</a>
        {% else %}-{% endif %}
    </td>
    <td>
        {% if p.has_date %}
            {{ p.post_date_formatted }}
        {% else %}
            <span class="no-date">kein Datum</span>
        {% endif %}
    </td>
    <td>
        {% if p.pp_id and p.post_image %}
        <div class="thumb-wrap">
            <img src="{% url 'posts_posted:image_proxy' p.pp_id %}" class="thumb" alt="Post-Bild">
            <img src="{% url 'posts_posted:image_proxy' p.pp_id %}" class="thumb-large" alt="Post-Bild gross">
        </div>
        {% else %}
            <span style="color:#aaa">—</span>
        {% endif %}
    </td>
    <td class="actions-cell">
        {% if p.pp_id %}
            <a href="{% url 'posts_posted:edit' p.pp_id %}" class="btn btn-secondary btn-sm">Bearbeiten</a>
        {% else %}
            <span style="color:#aaa;font-size:0.8rem">&mdash;</span>
        {% endif %}
    </td>
</tr>
{% empty %}
<tr><td colspan="6" style="text-align:center;color:#aaa;padding:2rem">Noch keine Eintraege.</td></tr>
{% endfor %}
</tbody></table>
</div>

<script>
function copyLink(link, event) {
    event.preventDefault();
    navigator.clipboard.writeText(link).then(function() {
        var btn = event.target;
        var orig = btn.textContent;
        btn.textContent = '\u2713';
        btn.style.color = 'green';
        setTimeout(function() { btn.textContent = orig; btn.style.color = ''; }, 1500);
    });
}
</script>
{% endblock %}
HTMLEOF
echo "  -> list.html mit Bild-Spalte und Hover-Zoom"

echo ""
echo "============================================"
echo "  FERTIG"
echo "============================================"
echo "  - Kein 'Neuen Post eintragen' Formular"
echo "  - Kein Loeschen-Button"
echo "  - Datum: TT.MM.JJJJ"
echo "  - Ohne Datum = ganz oben"
echo "  - Bild aus Nextcloud mit Hover-Zoom"
echo "  - 45 Posts (linkedin_posts fuehrend)"
echo ""
echo "  git add -A && git commit -m 'posts_posted komplett' && git push"
