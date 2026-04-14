#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# fix_posts_posted_complete.sh
#
# PROBLEM:  order_by('-created_at') crasht, weil das Model-Feld
#           created_at im Django-Model fehlt.
# LOESUNG:  - models.py: created_at + post_link ins Model
#           - views.py:  order_by nur '-post_date' (sicher)
#           - list.html: Titel-Tooltip + Datum TT.MM.JJJJ
#
# Ausfuehren im Codespace-Root:
#   bash fix_posts_posted_complete.sh
# ─────────────────────────────────────────────────────────────
set -euo pipefail
cd /workspaces/linkedin_django

echo "=== 1/4  models.py korrigieren ==="
cat > posts_posted/models.py << 'PYMODEL'
import re
from urllib.parse import unquote
from django.db import models
from django.core.exceptions import ValidationError

def extract_post_id(url):
    if not url: return None
    s = unquote(str(url)).strip().rstrip("/")
    m = re.search(r"urn:li:(?:activity|share|ugcpost):(\d+)", s, re.IGNORECASE)
    if m: return m.group(1)
    m = re.search(r"(?:activity|share|ugcpost)[:%3A]+(\d+)", s, re.IGNORECASE)
    if m: return m.group(1)
    m = re.search(r"(\d{10,})", s)
    return m.group(1) if m else None

class LinkedinPostPosted(models.Model):
    post_link  = models.CharField(max_length=512, unique=True, verbose_name="Post-Link")
    post_id    = models.CharField(max_length=30, unique=True, blank=True, null=True, verbose_name="Post-ID")
    created_at = models.DateTimeField(blank=True, null=True, verbose_name="Erstellt am")
    post_date  = models.DateField(blank=True, null=True, verbose_name="Tatsaechlich gepostet am")
    post_image = models.ImageField(upload_to="post_images/", blank=True, null=True, verbose_name="Post-Bild")

    class Meta:
        db_table = "linkedin_posts_posted"
        managed = False
        ordering = ["-post_date"]

    def clean(self):
        extracted = extract_post_id(self.post_link)
        if not extracted:
            raise ValidationError({"post_link": "Keine post_id im Link gefunden."})
        self.post_id = extracted
        qs = LinkedinPostPosted.objects.filter(post_id=self.post_id)
        if self.pk: qs = qs.exclude(pk=self.pk)
        if qs.exists():
            raise ValidationError({"post_link": f"Post mit ID {self.post_id} existiert bereits!"})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)
        from django.db import connection
        with connection.cursor() as cur:
            cur.execute(
                "UPDATE linkedin_posts SET post_date=%s WHERE post_id=%s AND (post_date IS NULL OR post_date!=%s)",
                [self.post_date, self.post_id, self.post_date]
            )
PYMODEL
echo "    -> models.py: 5 Felder (post_link, post_id, created_at, post_date, post_image)"

echo "=== 2/4  views.py korrigieren ==="
cat > posts_posted/views.py << 'PYVIEWS'
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
    # NUR post_date – KEIN created_at im order_by
    posts = list(LinkedinPostPosted.objects.all().order_by('-post_date'))
    if query:
        q_lower = query.lower()
        posts = [p for p in posts
                 if q_lower in (p.post_id or '').lower()
                 or q_lower in (p.post_link or '').lower()]

    # post_title aus linkedin_posts dazu mergen
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

    # Titel-Suche (nachtraeglich, weil Titel per JOIN kommt)
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
        form = PostPostedForm(request.POST, request.FILES, instance=post)
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
PYVIEWS
echo "    -> views.py: order_by NUR '-post_date' (kein created_at)"

echo "=== 3/4  list.html – Titel-Tooltip + Datum TT.MM.JJJJ ==="
TEMPLATE_DIR="posts_posted/templates/posts_posted"
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
echo "    -> list.html: Titel-Tooltip + Datum d.m.Y"

echo "=== 4/4  Git commit & push ==="
git add -A
git commit -m "FIX: FieldError created_at + Titel-Tooltip + Datum TT.MM.JJJJ

- models.py: created_at Feld hinzugefuegt (war in DB, fehlte im Model)
- views.py: order_by nur '-post_date' (robust, kein Crash)
- list.html: Titel mit Mouse-Over Tooltip, Datum als d.m.Y" || echo "(nichts zu committen)"
git push

echo ""
echo "========================================="
echo "  FERTIG – alles in einem Schritt"
echo "========================================="
echo ""
echo "Fixes:"
echo "  1. models.py  -> created_at Feld ergaenzt"
echo "  2. views.py   -> order_by NUR '-post_date'"
echo "  3. list.html  -> Titel-Tooltip + Datum TT.MM.JJJJ"
