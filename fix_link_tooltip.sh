#!/bin/bash
##############################################################
# fix_link_tooltip.sh
# 1. linkedin_posts als fuehrende Tabelle (alle 45 Posts)
# 2. Link-Tooltip mit voller URL
# 3. Kein Add, kein Delete
##############################################################
set -e
cd /opt/render/project/src 2>/dev/null || cd "$(dirname "$0")"

echo "=== 1. views.py: linkedin_posts als fuehrende Tabelle ==="

cat > posts_posted/views.py << 'PYEOF'
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import connection
from django.http import HttpResponse, Http404
from .models import LinkedinPostPosted
from .forms import PostPostedForm
from .nc_storage import upload_image_to_nextcloud, download_image_from_nextcloud, delete_image_from_nextcloud


@login_required
def post_list(request):
    """linkedin_posts ist die fuehrende Tabelle.
    Alle Posts werden angezeigt, auch ohne Datum."""
    query = request.GET.get("q", "").strip()

    # Fuehrend: linkedin_posts (alle Posts)
    # LEFT JOIN mit linkedin_posts_posted (Datum + Bild)
    sql = """
        SELECT
            lp.post_id,
            lp.post_title,
            lp.post_link,
            COALESCE(pp.post_date, NULL) AS post_date,
            pp.post_image,
            pp.post_link AS pp_pk
        FROM linkedin_posts lp
        LEFT JOIN linkedin_posts_posted pp ON lp.post_id = pp.post_id
    """
    params = []

    if query:
        sql += " WHERE lp.post_id LIKE %s OR lp.post_title LIKE %s OR lp.post_link LIKE %s"
        like = f"%{query}%"
        params = [like, like, like]

    sql += " ORDER BY lp.post_date DESC, lp.post_id DESC"

    with connection.cursor() as cur:
        cur.execute(sql, params)
        columns = [col[0] for col in cur.description]
        rows = cur.fetchall()

    posts = []
    for row in rows:
        post = dict(zip(columns, row))
        posts.append({
            'post_id': post['post_id'],
            'post_title': post.get('post_title') or '',
            'post_link': post.get('post_link') or '',
            'post_date': post.get('post_date'),
            'post_image': post.get('post_image') or '',
            'pp_pk': post.get('pp_pk') or '',  # PK fuer Bearbeiten-Link
            'has_posted_entry': bool(post.get('pp_pk')),
        })

    return render(request, "posts_posted/list.html", {"posts": posts, "query": query})


@login_required
def post_edit(request, pk):
    post = get_object_or_404(LinkedinPostPosted, pk=pk)
    if request.method == "POST":
        form = PostPostedForm(request.POST, request.FILES, instance=post)
        if form.is_valid():
            try:
                obj = form.save(commit=False)

                upload_file = request.FILES.get('upload_image')
                if upload_file:
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
echo "   views.py aktualisiert (linkedin_posts fuehrend)."

echo ""
echo "=== 2. urls.py sauber (nur list, edit, image_proxy) ==="

cat > posts_posted/urls.py << 'PYEOF'
from django.urls import path
from . import views

app_name = 'posts_posted'

urlpatterns = [
    path('', views.post_list, name='list'),
    path('<path:pk>/edit/', views.post_edit, name='edit'),
    path('<path:pk>/image/', views.post_image_proxy, name='image_proxy'),
]
PYEOF
echo "   urls.py aktualisiert."

echo ""
echo "=== 3. list.html mit Tooltip + fuehrender Tabelle ==="

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
.post-thumb {
    max-width: 80px;
    max-height: 60px;
    border-radius: 4px;
    cursor: pointer;
    transition: transform 0.3s;
}
.post-thumb:hover {
    transform: scale(2);
    z-index: 10;
    position: relative;
    box-shadow: 0 4px 12px rgba(0,0,0,0.3);
}
.copy-link-btn {
    cursor: pointer;
    margin-left: 0.3rem;
    color: var(--octo-petrol);
    text-decoration: none;
}
.copy-link-btn:hover { color: var(--octo-orange); }
.lightbox-overlay {
    display: none; position: fixed; top: 0; left: 0;
    width: 100%; height: 100%; background: rgba(0,0,0,0.85);
    z-index: 9999; justify-content: center; align-items: center;
    cursor: pointer;
}
.lightbox-overlay.active { display: flex; }
.lightbox-overlay img {
    max-width: 90%; max-height: 90%;
    border-radius: 8px; box-shadow: 0 4px 20px rgba(0,0,0,0.5);
}
.no-date { color: #cc6600; font-style: italic; }
</style>

<div class="card" style="margin-bottom: 1rem;">
    <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 1rem;">
        <h2 style="margin: 0;">Alle Eintraege ({{ posts|length }})</h2>
        <form method="get" style="display:flex; gap:0.5rem;">
            <input type="text" name="q" value="{{ query|default:'' }}" placeholder="Suche..."
                   style="padding: 0.4rem 0.8rem; border: 2px solid var(--octo-light-gray); border-radius: 6px;">
            <button type="submit" class="btn btn-secondary btn-sm">Suchen</button>
        </form>
    </div>
</div>

<table>
    <thead>
        <tr>
            <th>Post-ID</th>
            <th>Titel</th>
            <th>Post-Link</th>
            <th>Gepostet am</th>
            <th>Bild</th>
            <th>Aktionen</th>
        </tr>
    </thead>
    <tbody>
        {% for p in posts %}
        <tr>
            <td>{{ p.post_id }}</td>
            <td class="post-title-cell" title="{{ p.post_title|default:'-' }}">{{ p.post_title|default:"-"|truncatechars:50 }}</td>
            <td>
                <a href="{{ p.post_link }}" target="_blank" rel="noopener noreferrer"
                   title="{{ p.post_link }}">&#128279; Link</a>
                <a href="#" class="copy-link-btn" onclick="copyLink('{{ p.post_link }}', event)" title="Link kopieren">&#128203;</a>
            </td>
            <td>
                {% if p.post_date %}
                    {{ p.post_date|date:"d.m.Y" }}
                {% else %}
                    <span class="no-date">&ndash;</span>
                {% endif %}
            </td>
            <td>
                {% if p.post_image %}
                    <img src="{% url 'posts_posted:image_proxy' p.pp_pk %}"
                         alt="Post-Bild" class="post-thumb"
                         onclick="openLightbox(this.src)">
                {% else %}
                    &ndash;
                {% endif %}
            </td>
            <td>
                {% if p.has_posted_entry %}
                    <a href="{% url 'posts_posted:edit' p.pp_pk %}" class="btn btn-secondary btn-sm">Bearbeiten</a>
                {% else %}
                    <span style="color:#aaa; font-size:0.85rem;">kein Eintrag</span>
                {% endif %}
            </td>
        </tr>
        {% empty %}
        <tr><td colspan="6" style="text-align:center; color:#aaa; padding:2rem;">Noch keine Eintraege.</td></tr>
        {% endfor %}
    </tbody>
</table>

<!-- Lightbox -->
<div class="lightbox-overlay" id="lightbox" onclick="closeLightbox()">
    <img id="lightboxImg" src="" alt="Vollbild">
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
function openLightbox(src) {
    document.getElementById('lightboxImg').src = src;
    document.getElementById('lightbox').classList.add('active');
}
function closeLightbox() {
    document.getElementById('lightbox').classList.remove('active');
}
document.addEventListener('keydown', function(e) { if (e.key === 'Escape') closeLightbox(); });
</script>
{% endblock %}
HTMLEOF
echo "   list.html aktualisiert (Tooltip + fuehrende Tabelle)."

echo ""
echo "=== 4. Alte Duplikate loeschen ==="
find . -name "list.html" -not -path "*/posts_posted/templates/posts_posted/list.html" -not -path "./.git/*" -not -path "*/collectives/*" -not -path "*/core/*" 2>/dev/null | while read f; do
    echo "   LOESCHE: $f"
    rm -f "$f"
done
find . -name "list_*.html" -not -path "./.git/*" 2>/dev/null | while read f; do
    echo "   LOESCHE ALT: $f"
    rm -f "$f"
done

echo ""
echo "=== 5. Kontrolle ==="
echo "--- Verbleibende list*.html ---"
find . -name "list*.html" -not -path "./.git/*" 2>/dev/null
echo ""
echo "--- urls.py ---"
cat posts_posted/urls.py

echo ""
echo "============================================"
echo " FERTIG! Jetzt:"
echo "  git add -A"
echo "  git commit -m 'Fix: linkedin_posts fuehrend, tooltip, cleanup'"
echo "  git push"
echo "============================================"
