#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# deploy_titel_tooltip.sh
# Aenderungen:
#   1. Titel-Spalte: Mouse-Over (tooltip) zeigt vollen Post-Text
#   2. Datum "Gepostet am": Format TT.MM.JJJJ  (z.B. 30.03.2026)
#   3. Suche auch im Titel
# Ausfuehren im Codespace-Root (linkedin_django):
#   bash deploy_titel_tooltip.sh
# ─────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")"
PROJECT_ROOT="$(pwd)"

echo "=== 1/3  list.html aktualisieren ==="

TEMPLATE_DIR="$PROJECT_ROOT/posts_posted/templates/posts_posted"
mkdir -p "$TEMPLATE_DIR"

cat > "$TEMPLATE_DIR/list.html" << 'HTML'
{% extends "core/base.html" %}
{% block title %}Post-Datum-Zuordnung{% endblock %}
{% block content %}
<div class="card">
<h2>Neuen Post eintragen</h2>
<form method="post" action="{% url 'posts_posted:add' %}" enctype="multipart/form-data">{% csrf_token %}
<div style="display:grid;grid-template-columns:1fr 200px 200px auto;gap:1rem;align-items:end">
<div class="form-group"><label>{{ form.post_link.label }}</label>{{ form.post_link }}<div class="help">{{ form.post_link.help_text }}</div></div>
<div class="form-group"><label>{{ form.post_date.label }}</label>{{ form.post_date }}</div>
<div class="form-group"><label>{{ form.post_image.label }}</label>{{ form.post_image }}</div>
<button type="submit" class="btn btn-primary">Speichern</button>
</div></form></div>
<div class="card">
<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem">
<h2 style="margin:0">Alle Eintraege ({{ posts|length }})</h2>
<form style="display:flex;gap:.5rem;width:300px">
<input type="text" name="q" value="{{ query }}" class="form-input" placeholder="Suche...">
<button type="submit" class="btn btn-secondary btn-sm">Suchen</button>
</form></div>
<table><thead><tr>
<th>Post-ID</th>
<th>Titel</th>
<th>Post-Link</th>
<th>Gepostet am</th>
<th>Bild</th>
<th>Aktionen</th>
</tr></thead>
<tbody>{% for p in posts %}<tr>
<td><span class="badge">{{ p.post_id }}</span></td>
<td><span title="{{ p.post_title|default:'' }}" style="cursor:default;display:inline-block;max-width:420px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{{ p.post_title|default:"-"|truncatechars:80 }}</span></td>
<td><a href="{{ p.post_link }}" target="_blank" rel="noopener noreferrer" class="post-link">&#x1F517; Link</a>
{% if p.post_link %}<a href="javascript:void(0)" onclick="navigator.clipboard.writeText('{{ p.post_link|escapejs }}')" title="Link kopieren" style="margin-left:.3rem;cursor:pointer">&#x1F4CB;</a>{% endif %}</td>
<td>{{ p.post_date|date:"d.m.Y"|default:"-" }}</td>
<td>{% if p.post_image %}<div style="display:flex;align-items:center;gap:.4rem"><a href="{{ p.post_image.url }}" target="_blank"><img src="{{ p.post_image.url }}" style="max-height:50px;max-width:80px;border-radius:4px" alt="Post-Bild"></a></div>{% else %}&ndash;{% endif %}</td>
<td class="actions">
<a href="{% url 'posts_posted:edit' p.pk %}" class="btn btn-secondary btn-sm">Bearbeiten</a>
<a href="{% url 'posts_posted:delete' p.pk %}" class="btn btn-danger btn-sm">Loeschen</a>
</td></tr>{% empty %}
<tr><td colspan="6" style="text-align:center;color:#aaa;padding:2rem">Noch keine Eintraege.</td></tr>{% endfor %}
</tbody></table></div>
{% endblock %}
HTML

echo "    -> list.html geschrieben"

echo "=== 2/3  views.py – Suche auf Titel erweitern ==="

cat > "$PROJECT_ROOT/posts_posted/views.py" << 'PYVIEWS'
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
            cur.execute(f"SELECT post_id, COALESCE(post_title, post_title_raw, '') FROM linkedin_posts WHERE post_id IN ({placeholders})", post_ids)
            for row in cur.fetchall():
                title_map[row[0]] = row[1] or ''

    for p in posts:
        p.post_title = title_map.get(p.post_id, '')

    # Falls Suche: auch im Titel filtern (nachtraeglich)
    if query:
        q_lower = query.lower()
        posts = [p for p in posts if q_lower in (p.post_title or '').lower()
                 or q_lower in (p.post_id or '').lower()
                 or q_lower in (p.post_link or '').lower()]

    return render(request, "posts_posted/list.html", {"posts": posts, "form": PostPostedForm(), "query": query})

@login_required
def post_add(request):
    if request.method == "POST":
        form = PostPostedForm(request.POST, request.FILES)
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
        form = PostPostedForm(request.POST, request.FILES, instance=post)
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
PYVIEWS

echo "    -> views.py geschrieben"

echo "=== 3/3  Git commit & push ==="
cd "$PROJECT_ROOT"
git add -A
git commit -m "Titel: Mouse-Over Tooltip + Datum als TT.MM.JJJJ

- Titel-Spalte: title-Attribut zeigt vollen Text bei Hover
- truncatechars:80 + CSS text-overflow:ellipsis
- post_date|date:'d.m.Y' -> deutsches Datumsformat
- COALESCE(post_title, post_title_raw) als Fallback
- Suche auch im Titel" || echo "(nichts zu committen)"
git push

echo ""
echo "=== FERTIG ==="
echo "Aenderungen:"
echo "  - Titel: Mouse-Over zeigt vollen Text"
echo "  - Datum: jetzt TT.MM.JJJJ (z.B. 30.03.2026)"
echo "  - Suche funktioniert auch im Titel"
