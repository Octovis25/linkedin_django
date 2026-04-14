
#!/usr/bin/env bash
# ============================================================
# FIX_ALL_POSTS_POSTED.sh
# Komplettfix: views.py, urls.py, settings.py (whitenoise),
# alles in einem Schritt.
# ============================================================
set -euo pipefail

echo "=== 1) Backup ==="
for f in posts_posted/views.py posts_posted/urls.py posts_posted/templates/posts_posted/list.html dashboard/settings.py; do
    [ -f "$f" ] && cp "$f" "${f}.bak.$(date +%Y%m%d%H%M)" || true
done

echo "=== 2) whitenoise aus settings.py entfernen ==="
if [ -f dashboard/settings.py ]; then
    # Entferne jede Zeile die whitenoise enthaelt
    sed -i '/whitenoise/Id' dashboard/settings.py
    # Entferne whitenoise aus requirements.txt falls vorhanden
    [ -f requirements.txt ] && sed -i '/whitenoise/Id' requirements.txt || true
    echo "  -> whitenoise-Referenzen entfernt"
fi

echo "=== 3) posts_posted/urls.py bereinigen ==="
cat > posts_posted/urls.py << 'EOF'
from django.urls import path
from . import views

app_name = "posts_posted"

urlpatterns = [
    path("", views.post_list, name="list"),
    path("add/", views.post_add, name="add"),
    path("<int:pk>/edit/", views.post_edit, name="edit"),
    path("<int:pk>/delete/", views.post_delete, name="delete"),
]
EOF
echo "  -> urls.py: image_proxy entfernt, <int:pk> statt <path:pk>"

echo "=== 4) posts_posted/views.py neu schreiben ==="
cat > posts_posted/views.py << 'EOF'
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import connection
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
            WHERE lp.post_id LIKE %s
               OR lp.post_title LIKE %s
               OR lp.post_link LIKE %s
        """
        like = "%%{}%%".format(query)
        params = [like, like, like]

    sql += " ORDER BY COALESCE(pp.post_date, lp.post_date) DESC, lp.post_id DESC"

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
        messages.success(request, "Post {} geloescht.".format(post.post_id))
        return redirect("posts_posted:list")
    return render(request, "posts_posted/confirm_delete.html", {"post": post})
EOF
echo "  -> views.py: LEFT JOIN, LIKE statt ILIKE (MySQL-kompatibel), kein nc_storage"

echo "=== 5) posts_posted/templates/posts_posted/list.html neu schreiben ==="
mkdir -p posts_posted/templates/posts_posted
cat > posts_posted/templates/posts_posted/list.html << 'EOF'
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
</style>

<div class="card">
<h2>Neuen Post eintragen</h2>
<form method="post" action="{% url 'posts_posted:add' %}">{% csrf_token %}
<div style="display:grid;grid-template-columns:1fr 200px auto;gap:1rem;align-items:end">
<div class="form-group"><label>{{ form.post_link.label }}</label>{{ form.post_link }}<div class="help">{{ form.post_link.help_text }}</div></div>
<div class="form-group"><label>{{ form.post_date.label }}</label>{{ form.post_date }}</div>
<button type="submit" class="btn btn-primary">Speichern</button>
</div></form></div>

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
            {{ p.post_date }}
        {% else %}
            <span class="no-date">kein Datum</span>
        {% endif %}
    </td>
    <td class="actions-cell">
        {% if p.pp_id %}
            <a href="{% url 'posts_posted:edit' p.pp_id %}" class="btn btn-secondary btn-sm">Bearbeiten</a>
            <a href="{% url 'posts_posted:delete' p.pp_id %}" class="btn btn-danger btn-sm">L&ouml;schen</a>
        {% else %}
            <span style="color:#aaa;font-size:0.8rem">&mdash;</span>
        {% endif %}
    </td>
</tr>
{% empty %}
<tr><td colspan="5" style="text-align:center;color:#aaa;padding:2rem">Noch keine Eintraege.</td></tr>
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
EOF
echo "  -> list.html: Dictionary-Keys statt ORM-Attribute"

echo "=== 6) Alte nicht mehr benoetigte Dateien entfernen ==="
rm -f posts_posted/nc_storage.py 2>/dev/null && echo "  -> nc_storage.py entfernt" || true
rm -f posts_posted/views_TOOLTIP_DATE.py 2>/dev/null && echo "  -> views_TOOLTIP_DATE.py entfernt" || true

echo ""
echo "============================================"
echo "  FERTIG - Alle Fixes angewendet"
echo "============================================"
echo ""
echo "Gepatchte Dateien:"
echo "  1. dashboard/settings.py  -> whitenoise entfernt"
echo "  2. posts_posted/urls.py   -> image_proxy entfernt"
echo "  3. posts_posted/views.py  -> LEFT JOIN, MySQL LIKE"
echo "  4. posts_posted/list.html -> Dict-Keys"
echo "  5. Alte Dateien geloescht"
echo ""
echo "Jetzt ausfuehren:"
echo "  git add -A"
echo "  git commit -m 'Komplettfix posts_posted + whitenoise'"
echo "  git push"
