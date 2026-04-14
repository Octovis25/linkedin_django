#!/bin/bash
##############################################################
# fix_list_final.sh
# 1. Schreibt die RICHTIGE list.html in den RICHTIGEN Pfad
# 2. Loescht ALLE anderen/falschen list.html Kopien
# 3. Entfernt post_add und post_delete aus Views + URLs
##############################################################
set -e
cd /opt/render/project/src 2>/dev/null || cd "$(dirname "$0")"

echo "============================================"
echo " SAUBERMACHEN - list.html"
echo "============================================"

echo ""
echo "=== 1. ALLE falschen list.html finden und loeschen ==="
# Finde alle list.html die NICHT im richtigen Pfad liegen
find . -name "list.html" -not -path "*/posts_posted/templates/posts_posted/list.html" -not -path "./node_modules/*" -not -path "./.git/*" 2>/dev/null | while read f; do
    echo "   LOESCHE: $f"
    rm -f "$f"
done

# Auch alte Varianten loeschen
for old in list_FIXED.html list_TOOLTIP_DATE.html; do
    find . -name "$old" -not -path "./.git/*" 2>/dev/null | while read f; do
        echo "   LOESCHE ALT: $f"
        rm -f "$f"
    done
done
echo "   Alte/doppelte Templates geloescht."

echo ""
echo "=== 2. Richtiges Template-Verzeichnis sicherstellen ==="
mkdir -p posts_posted/templates/posts_posted
echo "   OK: posts_posted/templates/posts_posted/"

echo ""
echo "=== 3. SAUBERE list.html schreiben ==="

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
                <a href="{{ p.post_link }}" target="_blank" rel="noopener noreferrer">&#128279; Link</a>
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
            <td>
                <a href="{% url 'posts_posted:edit' p.pk %}" class="btn btn-secondary btn-sm">Bearbeiten</a>
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
echo "   RICHTIGE list.html geschrieben."

echo ""
echo "=== 4. post_add aus views.py entfernen ==="
if grep -q "def post_add" posts_posted/views.py 2>/dev/null; then
    python3 -c "
import re
with open('posts_posted/views.py','r') as f: code=f.read()
code2 = re.sub(r'\n@login_required\ndef post_add\(request\):.*?(?=\n@login_required|\n@csrf|\ndef |\Z)', '', code, flags=re.S)
with open('posts_posted/views.py','w') as f: f.write(code2)
print('   post_add view entfernt.')
"
else
    echo "   post_add nicht gefunden (OK)."
fi

echo ""
echo "=== 5. add-Route aus urls.py entfernen ==="
if grep -q "'add'" posts_posted/urls.py 2>/dev/null; then
    sed -i "/name='add'/d" posts_posted/urls.py
    echo "   add-Route entfernt."
else
    echo "   add-Route nicht gefunden (OK)."
fi

echo ""
echo "=== 6. delete-Route aus urls.py entfernen ==="
if grep -q "'delete'" posts_posted/urls.py 2>/dev/null; then
    sed -i "/name='delete'/d" posts_posted/urls.py
    echo "   delete-Route entfernt."
else
    echo "   delete-Route nicht gefunden (OK)."
fi

echo ""
echo "=== 7. Kontrolle ==="
echo "--- urls.py ---"
cat posts_posted/urls.py
echo ""
echo "--- Alle list.html im Projekt ---"
find . -name "list.html" -not -path "./.git/*" 2>/dev/null
echo ""
echo "--- Alle list_*.html im Projekt ---"
find . -name "list_*.html" -not -path "./.git/*" 2>/dev/null
echo ""

echo "============================================"
echo " FERTIG! Jetzt:"
echo "  git add -A"
echo "  git commit -m 'Fix: clean list - no add, no delete, image proxy'"
echo "  git push"
echo "============================================"
