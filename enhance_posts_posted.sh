#!/bin/bash
set -e

echo "=== Posts Posted Enhancement ==="
echo "Adding: Title column, Image thumbnail, Copy link button"

# Backup
mkdir -p backups/$(date +%Y%m%d_%H%M%S)
cp posts_posted/templates/posts_posted/list.html backups/$(date +%Y%m%d_%H%M%S)/ 2>/dev/null || true
cp posts_posted/models.py backups/$(date +%Y%m%d_%H%M%S)/ 2>/dev/null || true
cp posts_posted/views.py backups/$(date +%Y%m%d_%H%M%S)/ 2>/dev/null || true

# 1) Update Model - add title field if not exists
if ! grep -q "post_title" posts_posted/models.py; then
    sed -i '/post_link/a\    post_title = models.CharField(max_length=500, blank=True, null=True, verbose_name="Post Title")' posts_posted/models.py
    echo "✅ Model: post_title field added"
else
    echo "ℹ️  Model: post_title already exists"
fi

# 2) Create new list.html template with all features
cat > posts_posted/templates/posts_posted/list.html << 'HTML'
{% extends "core/base.html" %}
{% load static %}

{% block title %}Posts Posted{% endblock %}

{% block content %}
<style>
/* Tooltip styles */
.title-cell {
    max-width: 200px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    cursor: default;
}
.title-cell:hover {
    overflow: visible;
    white-space: normal;
    position: relative;
    z-index: 10;
    background: #fff;
    box-shadow: 0 2px 8px rgba(0,0,0,0.15);
    padding: 4px 8px;
    border-radius: 4px;
}

/* Link cell with copy button */
.link-cell {
    display: flex;
    align-items: center;
    gap: 8px;
}
.link-cell a {
    color: var(--octo-petrol);
    text-decoration: none;
}
.link-cell a:hover {
    text-decoration: underline;
}
.copy-btn {
    background: none;
    border: 1px solid #ddd;
    border-radius: 4px;
    padding: 2px 6px;
    cursor: pointer;
    font-size: 12px;
}
.copy-btn:hover {
    background: #f0f0f0;
}
.copy-btn.copied {
    background: #e8f5e9;
    border-color: #4caf50;
}

/* Thumbnail styles */
.thumb-cell {
    width: 50px;
    text-align: center;
}
.thumb-img {
    width: 40px;
    height: 40px;
    object-fit: cover;
    border-radius: 4px;
    cursor: pointer;
    border: 1px solid #ddd;
    transition: transform 0.2s;
}
.thumb-img:hover {
    transform: scale(1.1);
}
.no-image {
    color: #ccc;
    font-size: 20px;
}

/* Lightbox */
.lightbox {
    display: none;
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    background: rgba(0,0,0,0.8);
    z-index: 1000;
    justify-content: center;
    align-items: center;
    flex-direction: column;
}
.lightbox.active {
    display: flex;
}
.lightbox img {
    max-width: 90%;
    max-height: 80%;
    border-radius: 8px;
}
.lightbox-close {
    position: absolute;
    top: 20px;
    right: 30px;
    color: white;
    font-size: 30px;
    cursor: pointer;
}
.lightbox-download {
    margin-top: 16px;
    padding: 10px 20px;
    background: var(--octo-petrol);
    color: white;
    border: none;
    border-radius: 6px;
    cursor: pointer;
    text-decoration: none;
}

/* Drag & Drop */
.drop-zone {
    border: 2px dashed #ccc;
    border-radius: 8px;
    padding: 20px;
    text-align: center;
    transition: all 0.3s;
    cursor: pointer;
}
.drop-zone:hover, .drop-zone.dragover {
    border-color: var(--octo-petrol);
    background: #e0f7fa;
}
.drop-zone input[type="file"] {
    display: none;
}
.preview-img {
    max-width: 100px;
    max-height: 100px;
    margin-top: 10px;
    border-radius: 4px;
}

/* Error message */
.error-msg {
    background: #fce4ec;
    color: #c62828;
    padding: 12px 16px;
    border-radius: 8px;
    margin-bottom: 16px;
}
.success-msg {
    background: #e8f5e9;
    color: #2e7d32;
    padding: 12px 16px;
    border-radius: 8px;
    margin-bottom: 16px;
}
</style>

{% if error %}
<div class="error-msg">{{ error }}</div>
{% endif %}
{% if success %}
<div class="success-msg">{{ success }}</div>
{% endif %}

<!-- Neuen Post eintragen -->
<div class="card" style="background:white; padding:20px; border-radius:8px; margin-bottom:24px; border:1px solid #e0e0e0;">
    <h2 style="color:var(--octo-petrol); margin-bottom:16px;">Neuen Post eintragen</h2>
    <form method="post" enctype="multipart/form-data" action="{% url 'posts_posted:create' %}">
        {% csrf_token %}
        <div style="display:flex; gap:16px; flex-wrap:wrap; align-items:flex-end;">
            <div style="flex:2; min-width:300px;">
                <label style="display:block; font-size:12px; font-weight:600; color:#666; margin-bottom:4px;">LinkedIn Post-Link</label>
                <input type="text" name="post_link" placeholder="https://www.linkedin.com/feed/update/urn:li:activity:..." 
                       style="width:100%; padding:10px; border:1px solid #ddd; border-radius:6px;">
                <small style="color:#888;">Kompletten Link einfuegen.</small>
            </div>
            <div style="flex:1; min-width:150px;">
                <label style="display:block; font-size:12px; font-weight:600; color:#666; margin-bottom:4px;">Post-Title (optional)</label>
                <input type="text" name="post_title" placeholder="Kurzer Titel..."
                       style="width:100%; padding:10px; border:1px solid #ddd; border-radius:6px;">
            </div>
            <div style="flex:1; min-width:150px;">
                <label style="display:block; font-size:12px; font-weight:600; color:#666; margin-bottom:4px;">Tatsaechlich gepostet am</label>
                <input type="date" name="posted_at" style="width:100%; padding:10px; border:1px solid #ddd; border-radius:6px;">
            </div>
            <div style="flex:1; min-width:180px;">
                <label style="display:block; font-size:12px; font-weight:600; color:#666; margin-bottom:4px;">Post-Bild</label>
                <div class="drop-zone" onclick="document.getElementById('imageInput').click();" id="dropZone">
                    <span id="dropText">📷 Bild hierher ziehen oder klicken</span>
                    <input type="file" name="post_image" id="imageInput" accept="image/*">
                    <img id="previewImg" class="preview-img" style="display:none;">
                </div>
            </div>
            <div>
                <button type="submit" class="btn btn-primary">Speichern</button>
            </div>
        </div>
    </form>
</div>

<!-- Alle Einträge -->
<div class="card" style="background:white; padding:20px; border-radius:8px; border:1px solid #e0e0e0;">
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px;">
        <h2 style="color:var(--octo-petrol); margin:0;">Alle Eintraege ({{ posts|length }})</h2>
        <div style="display:flex; gap:8px;">
            <input type="text" id="searchInput" placeholder="Suche..." 
                   style="padding:8px 12px; border:1px solid #ddd; border-radius:6px; width:200px;"
                   onkeyup="filterTable()">
            <button class="btn btn-primary btn-sm" onclick="filterTable()">Suchen</button>
        </div>
    </div>
    
    <table id="postsTable">
        <thead>
            <tr>
                <th>Post-ID</th>
                <th>Title</th>
                <th>Post-Link</th>
                <th>Gepostet am</th>
                <th>Erstellt am</th>
                <th>Bild</th>
                <th>Aktionen</th>
            </tr>
        </thead>
        <tbody>
            {% for post in posts %}
            <tr>
                <td>{{ post.post_id|default:"-" }}</td>
                <td class="title-cell" title="{{ post.post_title|default:'' }}">
                    {{ post.post_title|default:"-"|truncatechars:30 }}
                </td>
                <td class="link-cell">
                    {% if post.post_link %}
                    <a href="{{ post.post_link }}" target="_blank" title="{{ post.post_link }}">🔗 LinkedIn Post oeffnen</a>
                    <button class="copy-btn" onclick="copyLink('{{ post.post_link }}', this)" title="Link kopieren">📋</button>
                    {% else %}
                    -
                    {% endif %}
                </td>
                <td>{{ post.posted_at|date:"M d, Y"|default:"-" }}</td>
                <td>{{ post.created_at|date:"M d, Y"|default:"-" }}</td>
                <td class="thumb-cell">
                    {% if post.post_image %}
                    <img src="{{ post.post_image.url }}" class="thumb-img" 
                         onclick="openLightbox('{{ post.post_image.url }}')" 
                         title="Klicken zum Vergroessern">
                    {% else %}
                    <span class="no-image">—</span>
                    {% endif %}
                </td>
                <td>
                    <a href="{% url 'posts_posted:edit' post.pk %}" class="btn btn-sm btn-primary">Bearbeiten</a>
                    <a href="{% url 'posts_posted:delete' post.pk %}" class="btn btn-sm btn-danger">Loeschen</a>
                </td>
            </tr>
            {% empty %}
            <tr>
                <td colspan="7" style="text-align:center; color:#888; padding:32px;">Keine Posts vorhanden.</td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
</div>

<!-- Lightbox -->
<div class="lightbox" id="lightbox" onclick="closeLightbox()">
    <span class="lightbox-close">&times;</span>
    <img id="lightboxImg" src="" alt="Post Bild">
    <a id="lightboxDownload" class="lightbox-download" href="" download onclick="event.stopPropagation();">⬇️ Download</a>
</div>

<script>
// Copy link function
function copyLink(link, btn) {
    navigator.clipboard.writeText(link).then(() => {
        btn.classList.add('copied');
        btn.textContent = '✓';
        setTimeout(() => {
            btn.classList.remove('copied');
            btn.textContent = '📋';
        }, 2000);
    });
}

// Lightbox functions
function openLightbox(src) {
    document.getElementById('lightboxImg').src = src;
    document.getElementById('lightboxDownload').href = src;
    document.getElementById('lightbox').classList.add('active');
}
function closeLightbox() {
    document.getElementById('lightbox').classList.remove('active');
}

// Search/Filter
function filterTable() {
    const query = document.getElementById('searchInput').value.toLowerCase();
    const rows = document.querySelectorAll('#postsTable tbody tr');
    rows.forEach(row => {
        const text = row.textContent.toLowerCase();
        row.style.display = text.includes(query) ? '' : 'none';
    });
}

// Drag & Drop
const dropZone = document.getElementById('dropZone');
const imageInput = document.getElementById('imageInput');
const previewImg = document.getElementById('previewImg');
const dropText = document.getElementById('dropText');

['dragenter', 'dragover'].forEach(e => {
    dropZone.addEventListener(e, (ev) => {
        ev.preventDefault();
        dropZone.classList.add('dragover');
    });
});
['dragleave', 'drop'].forEach(e => {
    dropZone.addEventListener(e, (ev) => {
        ev.preventDefault();
        dropZone.classList.remove('dragover');
    });
});
dropZone.addEventListener('drop', (ev) => {
    const files = ev.dataTransfer.files;
    if (files.length) {
        imageInput.files = files;
        showPreview(files[0]);
    }
});
imageInput.addEventListener('change', () => {
    if (imageInput.files.length) {
        showPreview(imageInput.files[0]);
    }
});
function showPreview(file) {
    const reader = new FileReader();
    reader.onload = (e) => {
        previewImg.src = e.target.result;
        previewImg.style.display = 'block';
        dropText.textContent = file.name;
    };
    reader.readAsDataURL(file);
}
</script>
{% endblock %}
HTML

echo "✅ Template: list.html updated with all features"

# 3) Update views.py to handle new fields
cat > /tmp/views_patch.py << 'PYPATCH'
import re
import sys

with open('posts_posted/views.py', 'r') as f:
    content = f.read()

# Check if create view handles post_title and post_image
if 'post_title' not in content:
    # Find the create function and add handling
    content = re.sub(
        r"(post_link\s*=\s*request\.POST\.get\('post_link'\))",
        r"\1\n        post_title = request.POST.get('post_title', '')\n        post_image = request.FILES.get('post_image')",
        content
    )
    
    # Update object creation to include new fields
    content = re.sub(
        r"(PostPosted\.objects\.create\([^)]*post_link\s*=\s*post_link)",
        r"\1, post_title=post_title, post_image=post_image",
        content
    )
    
    print("Views patched for post_title and post_image")
else:
    print("Views already have post_title handling")

with open('posts_posted/views.py', 'w') as f:
    f.write(content)
PYPATCH

python3 /tmp/views_patch.py || echo "⚠️ Manual views.py update may be needed"

echo ""
echo "=== Done! ==="
echo ""
echo "Next steps:"
echo "1) python manage.py makemigrations posts_posted"
echo "2) python manage.py migrate"
echo "3) git add . && git commit -m 'Add title, image thumbnail, copy link to posts' && git push"
echo "4) Manual deploy on Render"
