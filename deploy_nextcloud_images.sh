#!/bin/bash
##############################################################
# deploy_nextcloud_images.sh
# Post-Bilder via Nextcloud WebDAV speichern + Proxy ausliefern
# KEIN Auto-Deploy! Manuell committen & pushen.
##############################################################
set -e
cd /opt/render/project/src 2>/dev/null || cd "$(dirname "$0")"

echo "============================================"
echo " Nextcloud Post-Bilder Integration"
echo "============================================"

########################################
# 1. Model: post_image -> nc_image_path
########################################
echo ""
echo "=== 1. Model aktualisieren ==="

cat > posts_posted/models.py << 'PYEOF'
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
    post_link = models.CharField(max_length=512, primary_key=True, verbose_name="Post-Link")
    post_id = models.CharField(max_length=30, unique=True, blank=True, null=True, verbose_name="Post-ID")
    created_at = models.DateTimeField(blank=True, null=True, verbose_name="Erstellt am")
    post_date = models.DateField(verbose_name="Tatsaechlich gepostet am")
    post_image = models.CharField(max_length=512, blank=True, null=True, verbose_name="Nextcloud Bild-Pfad")

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
            cur.execute("SELECT 1 FROM linkedin_posts WHERE post_id=%s LIMIT 1", [self.post_id])
            if cur.fetchone():
                cur.execute("UPDATE linkedin_posts SET post_date=%s WHERE post_id=%s AND (post_date IS NULL OR post_date!=%s)",
                    [self.post_date, self.post_id, self.post_date])
PYEOF
echo "   models.py aktualisiert."

########################################
# 2. Forms: FileField fuer Upload
########################################
echo ""
echo "=== 2. Forms aktualisieren ==="

cat > posts_posted/forms.py << 'PYEOF'
from django import forms
from .models import LinkedinPostPosted

class PostPostedForm(forms.ModelForm):
    # Separates Upload-Feld (nicht im Model)
    upload_image = forms.ImageField(
        required=False,
        label="Post-Bild",
        widget=forms.ClearableFileInput(attrs={'accept': 'image/*'})
    )

    class Meta:
        model = LinkedinPostPosted
        fields = ["post_link", "post_date"]
        widgets = {
            "post_link": forms.TextInput(attrs={
                "placeholder": "LinkedIn Post-URL einfuegen...",
                "class": "form-control"
            }),
            "post_date": forms.DateInput(attrs={
                "type": "date",
                "class": "form-control"
            }),
        }
PYEOF
echo "   forms.py aktualisiert."

########################################
# 3. Nextcloud Helper (nc_storage.py)
########################################
echo ""
echo "=== 3. Nextcloud Storage Helper erstellen ==="

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

# Nextcloud folder for post images
NC_IMAGE_FOLDER = "Marketing & Design/LinkedIn/Post-Bilder"


def _get_nc_credentials():
    """Get Nextcloud credentials from collectives config or env."""
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
    """Create the image folder in Nextcloud if it doesn't exist."""
    parts = NC_IMAGE_FOLDER.split("/")
    current = ""
    for part in parts:
        current = f"{current}/{part}" if current else part
        folder_url = f"{nc_url}/remote.php/dav/files/{username}/{quote(current)}/"
        requests.request(
            'MKCOL', folder_url,
            auth=HTTPBasicAuth(username, password),
            timeout=10
        )
        # Ignore errors (folder may already exist)


def upload_image_to_nextcloud(image_file, filename):
    """
    Upload an image file to Nextcloud via WebDAV.
    Returns the Nextcloud path (relative) on success, None on failure.
    """
    nc_url, username, password = _get_nc_credentials()
    if not all([nc_url, username, password]):
        return None

    try:
        _ensure_folder_exists(nc_url, username, password)

        # Clean filename
        safe_filename = filename.replace(" ", "_")
        nc_path = f"{NC_IMAGE_FOLDER}/{safe_filename}"
        upload_url = f"{nc_url}/remote.php/dav/files/{username}/{quote(nc_path)}"

        # Read file content
        content = image_file.read()

        # Upload via PUT
        r = requests.put(
            upload_url,
            data=content,
            auth=HTTPBasicAuth(username, password),
            headers={'Content-Type': image_file.content_type or 'image/png'},
            timeout=30
        )

        if r.status_code in [200, 201, 204]:
            return nc_path
        else:
            print(f"Nextcloud upload failed: HTTP {r.status_code} - {r.text[:200]}")
            return None

    except Exception as e:
        print(f"Nextcloud upload error: {e}")
        return None


def download_image_from_nextcloud(nc_path):
    """
    Download an image from Nextcloud via WebDAV.
    Returns (content_bytes, content_type) or (None, None).
    """
    nc_url, username, password = _get_nc_credentials()
    if not all([nc_url, username, password]):
        return None, None

    try:
        download_url = f"{nc_url}/remote.php/dav/files/{username}/{quote(nc_path)}"

        r = requests.get(
            download_url,
            auth=HTTPBasicAuth(username, password),
            timeout=30
        )

        if r.status_code == 200:
            content_type = r.headers.get('Content-Type', 'image/png')
            return r.content, content_type
        else:
            return None, None

    except Exception as e:
        print(f"Nextcloud download error: {e}")
        return None, None


def delete_image_from_nextcloud(nc_path):
    """Delete an image from Nextcloud via WebDAV."""
    nc_url, username, password = _get_nc_credentials()
    if not all([nc_url, username, password]):
        return False

    try:
        delete_url = f"{nc_url}/remote.php/dav/files/{username}/{quote(nc_path)}"
        r = requests.delete(
            delete_url,
            auth=HTTPBasicAuth(username, password),
            timeout=10
        )
        return r.status_code in [200, 204]
    except Exception:
        return False
PYEOF
echo "   nc_storage.py erstellt."

########################################
# 4. Views aktualisieren
########################################
echo ""
echo "=== 4. Views aktualisieren ==="

cat > posts_posted/views.py << 'PYEOF'
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
def post_add(request):
    if request.method == "POST":
        form = PostPostedForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                post = form.save(commit=False)

                # Handle image upload to Nextcloud
                upload_file = request.FILES.get('upload_image')
                if upload_file:
                    filename = f"{post.post_id}_{upload_file.name}"
                    nc_path = upload_image_to_nextcloud(upload_file, filename)
                    if nc_path:
                        post.post_image = nc_path
                        messages.success(request, "Post gespeichert + Bild in Nextcloud hochgeladen!")
                    else:
                        messages.warning(request, "Post gespeichert, aber Bild-Upload nach Nextcloud fehlgeschlagen.")
                else:
                    messages.success(request, "Post-Datum gespeichert!")

                post.save()
            except Exception as e:
                messages.error(request, str(e))
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
PYEOF
echo "   views.py aktualisiert."

########################################
# 5. URLs: Proxy-Route hinzufuegen
########################################
echo ""
echo "=== 5. URLs aktualisieren ==="

cat > posts_posted/urls.py << 'PYEOF'
from django.urls import path
from . import views

app_name = 'posts_posted'

urlpatterns = [
    path('', views.post_list, name='list'),
    path('add/', views.post_add, name='add'),
    path('<path:pk>/edit/', views.post_edit, name='edit'),
    path('<path:pk>/delete/', views.post_delete, name='delete'),
    path('<path:pk>/image/', views.post_image_proxy, name='image_proxy'),
]
PYEOF
echo "   urls.py aktualisiert."

########################################
# 6. Template: list.html
########################################
echo ""
echo "=== 6. Template aktualisieren ==="

cat > posts_posted/templates/posts_posted/list.html << 'HTMLEOF'
{% extends "core/base.html" %}
{% load static %}
{% block title %}Post-Datum-Zuordnung{% endblock %}
{% block content %}
<style>
    .drag-drop-area {
        border: 2px dashed var(--octo-petrol);
        border-radius: 8px;
        padding: 30px;
        text-align: center;
        background: var(--octo-light-gray);
        cursor: pointer;
        transition: all 0.3s;
        margin-bottom: 1rem;
    }
    .drag-drop-area.dragover {
        background: #e0f7fa;
        border-color: var(--octo-orange);
    }
    .drag-drop-area:hover { background: #f0f0f0; }
    .drag-drop-area img {
        max-width: 200px;
        max-height: 150px;
        margin-top: 10px;
        border-radius: 6px;
    }
    .copy-link-btn {
        cursor: pointer;
        margin-left: 0.3rem;
        color: var(--octo-petrol);
        text-decoration: none;
        font-size: 1rem;
    }
    .copy-link-btn:hover { color: var(--octo-orange); }
    .post-title-cell {
        max-width: 300px;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }
    .actions-cell .btn { font-size: 0.75rem; padding: 0.25rem 0.6rem; }
    .post-thumb {
        max-width: 80px;
        max-height: 60px;
        border-radius: 4px;
        cursor: pointer;
        transition: transform 0.2s;
    }
    .post-thumb:hover { transform: scale(1.5); }
    /* Lightbox */
    .lightbox-overlay {
        display: none; position: fixed; top: 0; left: 0;
        width: 100%; height: 100%; background: rgba(0,0,0,0.8);
        z-index: 9999; justify-content: center; align-items: center;
        cursor: pointer;
    }
    .lightbox-overlay.active { display: flex; }
    .lightbox-overlay img {
        max-width: 90%; max-height: 90%;
        border-radius: 8px; box-shadow: 0 4px 20px rgba(0,0,0,0.5);
    }
</style>

<h2>Neuen Post eintragen</h2>
<form method="post" action="{% url 'posts_posted:add' %}" enctype="multipart/form-data" class="card" style="margin-bottom: 1.5rem;">
    {% csrf_token %}
    <div style="display: flex; gap: 1rem; flex-wrap: wrap; align-items: flex-end;">
        <div style="flex: 2; min-width: 250px;">
            {{ form.post_link.label }}
            {{ form.post_link }}
            <small style="color: #888;">{{ form.post_link.help_text }}</small>
        </div>
        <div style="flex: 1; min-width: 150px;">
            {{ form.post_date.label }}
            {{ form.post_date }}
        </div>
        <div style="flex: 1; min-width: 200px;">
            <label>Post-Bild</label>
            <div class="drag-drop-area" id="dragDropArea">
                &#128247; Bild hierher ziehen oder klicken
                <div id="imagePreview"></div>
            </div>
            <input type="file" name="upload_image" id="id_upload_image"
                   accept="image/*" style="display: none;">
        </div>
        <div>
            <button type="submit" class="btn btn-primary">Speichern</button>
        </div>
    </div>
</form>

<h2>Alle Eintraege ({{ posts|length }})</h2>
<div style="display: flex; justify-content: flex-end; margin-bottom: 0.5rem;">
    <form method="get" style="display:flex; gap:0.5rem;">
        <input type="text" name="q" value="{{ query|default:'' }}" placeholder="Suche..."
               style="padding: 0.4rem 0.8rem; border: 2px solid var(--octo-light-gray); border-radius: 6px;">
        <button type="submit" class="btn btn-secondary btn-sm">Suchen</button>
    </form>
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
                <a href="{{ p.post_link }}" target="_blank" title="Auf LinkedIn oeffnen">&#128279; Link</a>
                <a href="#" class="copy-link-btn" onclick="copyLink('{{ p.post_link }}', event)" title="Link kopieren">&#128203;</a>
            </td>
            <td>{{ p.post_date|date:"d.m.Y"|default:"-" }}</td>
            <td>
                {% if p.post_image %}
                    <img src="{% url 'posts_posted:image_proxy' p.pk %}"
                         alt="Post-Bild" class="post-thumb"
                         onclick="openLightbox(this.src)">
                {% else %}
                    &ndash;
                {% endif %}
            </td>
            <td class="actions-cell">
                <a href="{% url 'posts_posted:edit' p.pk %}" class="btn btn-secondary btn-sm">Bearbeiten</a>
            </td>
        </tr>
        {% empty %}
        <tr><td colspan="6">Noch keine Eintraege.</td></tr>
        {% endfor %}
    </tbody>
</table>

<!-- Lightbox -->
<div class="lightbox-overlay" id="lightbox" onclick="closeLightbox()">
    <img id="lightboxImg" src="" alt="Vollbild">
</div>

{% endblock %}

{% block extra_js %}
<script>
// Drag & Drop
const dragArea = document.getElementById('dragDropArea');
const fileInput = document.getElementById('id_upload_image');
const imagePreview = document.getElementById('imagePreview');

dragArea.addEventListener('click', () => fileInput.click());
dragArea.addEventListener('dragover', (e) => { e.preventDefault(); dragArea.classList.add('dragover'); });
dragArea.addEventListener('dragleave', () => { dragArea.classList.remove('dragover'); });
dragArea.addEventListener('drop', (e) => {
    e.preventDefault();
    dragArea.classList.remove('dragover');
    const files = e.dataTransfer.files;
    if (files.length > 0 && files[0].type.startsWith('image/')) {
        fileInput.files = files;
        showPreview(files[0]);
    }
});
fileInput.addEventListener('change', () => {
    if (fileInput.files.length > 0) showPreview(fileInput.files[0]);
});

function showPreview(file) {
    const reader = new FileReader();
    reader.onload = (e) => {
        imagePreview.innerHTML = `<br><img src="${e.target.result}" alt="Preview">
            <br><small style="color: var(--octo-dark-petrol); font-weight: 500;">&#10003; ${file.name}</small>`;
    };
    reader.readAsDataURL(file);
}

// Copy link
function copyLink(link, event) {
    event.preventDefault();
    navigator.clipboard.writeText(link).then(() => {
        const btn = event.target;
        const orig = btn.textContent;
        btn.textContent = '\u2713';
        btn.style.color = 'green';
        setTimeout(() => { btn.textContent = orig; btn.style.color = ''; }, 1500);
    });
}

// Lightbox
function openLightbox(src) {
    document.getElementById('lightboxImg').src = src;
    document.getElementById('lightbox').classList.add('active');
}
function closeLightbox() {
    document.getElementById('lightbox').classList.remove('active');
}
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeLightbox(); });
</script>
{% endblock %}
HTMLEOF
echo "   list.html aktualisiert."

########################################
# 7. DB-Spalte anpassen (falls noetig)
########################################
echo ""
echo "=== 7. DB-Spalte pruefen ==="
echo "   Die post_image Spalte in der DB muss VARCHAR(512) sein."
echo "   Falls sie als BLOB/LONGBLOB existiert, bitte manuell aendern:"
echo "   ALTER TABLE linkedin_posts_posted MODIFY post_image VARCHAR(512) NULL;"

########################################
# 8. Edit-Template aktualisieren
########################################
echo ""
echo "=== 8. Edit-Template aktualisieren ==="

cat > posts_posted/templates/posts_posted/edit.html << 'HTMLEOF'
{% extends "core/base.html" %}
{% block title %}Post bearbeiten{% endblock %}
{% block content %}
<style>
    .drag-drop-area {
        border: 2px dashed var(--octo-petrol);
        border-radius: 8px;
        padding: 30px;
        text-align: center;
        background: var(--octo-light-gray);
        cursor: pointer;
        transition: all 0.3s;
        margin-bottom: 1rem;
    }
    .drag-drop-area.dragover { background: #e0f7fa; border-color: var(--octo-orange); }
    .drag-drop-area:hover { background: #f0f0f0; }
    .drag-drop-area img { max-width: 200px; max-height: 150px; margin-top: 10px; border-radius: 6px; }
    .current-image { margin: 0.5rem 0; }
    .current-image img { max-width: 200px; border-radius: 6px; }
</style>

<h2>Post bearbeiten: {{ post.post_id }}</h2>
<form method="post" enctype="multipart/form-data" class="card">
    {% csrf_token %}
    <div class="form-group">
        {{ form.post_link.label }}
        {{ form.post_link }}
    </div>
    <div class="form-group">
        {{ form.post_date.label }}
        {{ form.post_date }}
    </div>
    <div class="form-group">
        <label>Post-Bild</label>
        {% if post.post_image %}
        <div class="current-image">
            <p><small>Aktuelles Bild:</small></p>
            <img src="{% url 'posts_posted:image_proxy' post.pk %}" alt="Aktuelles Bild">
        </div>
        <p><small style="color: #888;">Neues Bild hochladen um zu ersetzen:</small></p>
        {% endif %}
        <div class="drag-drop-area" id="dragDropArea">
            &#128247; Bild hierher ziehen oder klicken
            <div id="imagePreview"></div>
        </div>
        <input type="file" name="upload_image" id="id_upload_image"
               accept="image/*" style="display: none;">
    </div>
    <div style="display: flex; gap: 0.5rem;">
        <button type="submit" class="btn btn-primary">Speichern</button>
        <a href="{% url 'posts_posted:list' %}" class="btn btn-secondary">Abbrechen</a>
    </div>
</form>

<script>
const dragArea = document.getElementById('dragDropArea');
const fileInput = document.getElementById('id_upload_image');
const imagePreview = document.getElementById('imagePreview');
dragArea.addEventListener('click', () => fileInput.click());
dragArea.addEventListener('dragover', (e) => { e.preventDefault(); dragArea.classList.add('dragover'); });
dragArea.addEventListener('dragleave', () => { dragArea.classList.remove('dragover'); });
dragArea.addEventListener('drop', (e) => {
    e.preventDefault(); dragArea.classList.remove('dragover');
    const files = e.dataTransfer.files;
    if (files.length > 0 && files[0].type.startsWith('image/')) {
        fileInput.files = files;
        const reader = new FileReader();
        reader.onload = (ev) => {
            imagePreview.innerHTML = `<br><img src="${ev.target.result}" alt="Preview">
                <br><small style="color: var(--octo-dark-petrol);">&#10003; ${files[0].name}</small>`;
        };
        reader.readAsDataURL(files[0]);
    }
});
fileInput.addEventListener('change', () => {
    if (fileInput.files.length > 0) {
        const reader = new FileReader();
        reader.onload = (ev) => {
            imagePreview.innerHTML = `<br><img src="${ev.target.result}" alt="Preview">
                <br><small style="color: var(--octo-dark-petrol);">&#10003; ${fileInput.files[0].name}</small>`;
        };
        reader.readAsDataURL(fileInput.files[0]);
    }
});
</script>
{% endblock %}
HTMLEOF
echo "   edit.html aktualisiert."

echo ""
echo "============================================"
echo " FERTIG!"
echo "============================================"
echo ""
echo "WICHTIG - DB-Spalte pruefen/anpassen:"
echo "  Falls post_image als BLOB gespeichert ist:"
echo "  ALTER TABLE linkedin_posts_posted MODIFY post_image VARCHAR(512) NULL;"
echo ""
echo "Dann committen & pushen:"
echo "  git add -A"
echo "  git commit -m 'Feature: Post-Bilder via Nextcloud WebDAV + Proxy'"
echo "  git push"
echo ""
echo "Nextcloud-Ordner: Marketing & Design/LinkedIn/Post-Bilder/"
echo "============================================"
