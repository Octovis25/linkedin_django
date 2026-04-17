#!/bin/bash
# ============================================================
#  FIX_STATISTICS_FINAL.sh
#  – Dopplung entfernen
#  – linkedin_statistics-App sauber aufbauen
#  – Echte MySQL-Daten (linkedin_posts + linkedin_posts_posted)
#  – Tabs: Overview | Post Timeline
# ============================================================
set -euo pipefail

echo "=================================================="
echo "  STATISTICS FIX – FINAL"
echo "=================================================="

# ── SCHRITT 1: settings.py bereinigen ─────────────────────
echo ""
echo "[1/7] settings.py bereinigen ..."
python3 - << 'PYEOF'
path = 'dashboard/settings.py'
with open(path) as f:
    content = f.read()

# Entferne 'statistics' (Python-stdlib-Konflikt)
import re
# Entferne alle Zeilen mit reinem 'statistics' (ohne linkedin_)
lines = content.split('\n')
new_lines = []
seen_li_stat = False
for line in lines:
    stripped = line.strip().strip(',').strip('"').strip("'")
    # Entferne reines 'statistics' (nicht linkedin_statistics)
    if stripped == 'statistics':
        print(f"  Entfernt: {line.strip()}")
        continue
    # Entferne Duplikate von linkedin_statistics
    if 'linkedin_statistics' in line:
        if seen_li_stat:
            print(f"  Duplikat entfernt: {line.strip()}")
            continue
        seen_li_stat = True
    new_lines.append(line)

# Falls linkedin_statistics noch gar nicht drin ist, hinzufügen
result = '\n'.join(new_lines)
if 'linkedin_statistics' not in result:
    result = result.replace(
        "'collectives',",
        "'collectives',\n    'linkedin_statistics',"
    )
    print("  linkedin_statistics in INSTALLED_APPS eingefügt.")
else:
    print("  linkedin_statistics ist korrekt vorhanden.")

with open(path, 'w') as f:
    f.write(result)
print("  settings.py OK")
PYEOF

# ── SCHRITT 2: Ordnerstruktur anlegen ─────────────────────
echo ""
echo "[2/7] Ordnerstruktur ..."
mkdir -p linkedin_statistics/templates/linkedin_statistics
touch linkedin_statistics/__init__.py
echo "  OK"

# ── SCHRITT 3: apps.py (EINE, korrekte) ───────────────────
echo ""
echo "[3/7] apps.py ..."
cat > linkedin_statistics/apps.py << 'EOF'
from django.apps import AppConfig

class LinkedinStatisticsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'linkedin_statistics'
    label = 'linkedin_statistics'          # explizit – verhindert Kollision
    verbose_name = 'LinkedIn Statistics'
EOF
echo "  OK"

# ── SCHRITT 4: views.py ───────────────────────────────────
echo ""
echo "[4/7] views.py ..."
cat > linkedin_statistics/views.py << 'EOF'
"""
LinkedIn Statistics – views.py
Liest direkt aus der MySQL-Datenbank (raw SQL).
Tabellen:
  linkedin_posts        – Timelines je Post (impressions, clicks, etc.)
  linkedin_posts_posted – Initiales Postdatum + post_id
"""
from datetime import datetime, timedelta, date
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.db import connection


# ──────────────────────────────────────────────────────────
# Hilfsfunktionen
# ──────────────────────────────────────────────────────────
def _get_date_range(request):
    """Liest ?from=YYYY-MM-DD&to=YYYY-MM-DD; Default: letzte 30 Tage."""
    today = date.today()
    d_from = today - timedelta(days=30)
    d_to   = today
    try:
        if request.GET.get('from'):
            d_from = datetime.strptime(request.GET['from'], '%Y-%m-%d').date()
        if request.GET.get('to'):
            d_to = datetime.strptime(request.GET['to'], '%Y-%m-%d').date()
    except ValueError:
        pass
    return d_from, d_to


def _fmt(d):
    return d.strftime('%Y-%m-%d') if d else ''


# ──────────────────────────────────────────────────────────
# Datenbankabfragen
# ──────────────────────────────────────────────────────────
def _get_overview_kpis(d_from, d_to):
    """Aggregierte KPIs über alle Posts im Zeitraum."""
    with connection.cursor() as cur:
        cur.execute("""
            SELECT
                COUNT(DISTINCT p.post_id)           AS total_posts,
                COALESCE(SUM(p.impressions), 0)     AS total_impressions,
                COALESCE(SUM(p.clicks), 0)          AS total_clicks,
                COALESCE(SUM(p.likes), 0)           AS total_likes,
                COALESCE(SUM(p.comments), 0)        AS total_comments,
                COALESCE(SUM(p.shares), 0)          AS total_shares
            FROM linkedin_posts p
            WHERE p.date BETWEEN %s AND %s
        """, [d_from, d_to])
        row = cur.fetchone()
    if row:
        return {
            'total_posts':       row[0] or 0,
            'total_impressions': row[1] or 0,
            'total_clicks':      row[2] or 0,
            'total_likes':       row[3] or 0,
            'total_comments':    row[4] or 0,
            'total_shares':      row[5] or 0,
        }
    return {k: 0 for k in ('total_posts','total_impressions','total_clicks',
                            'total_likes','total_comments','total_shares')}


def _get_timeline_posts(d_from, d_to):
    """
    Gibt alle Posts zurück, die im Zeitraum Timeline-Daten haben.
    Verknüpft linkedin_posts mit linkedin_posts_posted über post_id,
    um das echte Postdatum (post_date) zu erhalten.
    """
    with connection.cursor() as cur:
        # Prüfe zuerst, welche Spalten in linkedin_posts existieren
        cur.execute("SHOW COLUMNS FROM linkedin_posts")
        cols = {row[0].lower() for row in cur.fetchall()}

    # Dynamischer SELECT je nach vorhandenen Spalten
    select_parts = [
        "p.post_id",
        "MIN(p.date) AS first_data_date",
        "MAX(p.date) AS last_data_date",
        "COALESCE(SUM(p.impressions), 0) AS total_impressions",
    ]
    if 'clicks' in cols:
        select_parts.append("COALESCE(SUM(p.clicks), 0) AS total_clicks")
    else:
        select_parts.append("0 AS total_clicks")
    if 'likes' in cols:
        select_parts.append("COALESCE(SUM(p.likes), 0) AS total_likes")
    else:
        select_parts.append("0 AS total_likes")
    if 'comments' in cols:
        select_parts.append("COALESCE(SUM(p.comments), 0) AS total_comments")
    else:
        select_parts.append("0 AS total_comments")

    sql = f"""
        SELECT
            {', '.join(select_parts)},
            pp.post_date   AS posted_on,
            pp.post_link
        FROM linkedin_posts p
        LEFT JOIN linkedin_posts_posted pp ON pp.post_id = p.post_id
        WHERE p.date BETWEEN %s AND %s
        GROUP BY p.post_id, pp.post_date, pp.post_link
        ORDER BY pp.post_date DESC, p.post_id
    """
    with connection.cursor() as cur:
        cur.execute(sql, [d_from, d_to])
        rows = cur.fetchall()

    posts = []
    for row in rows:
        posts.append({
            'post_id':           row[0],
            'first_data_date':   row[1],
            'last_data_date':    row[2],
            'total_impressions': row[3],
            'total_clicks':      row[4],
            'total_likes':       row[5],
            'total_comments':    row[6],
            'posted_on':         row[7],
            'post_link':         row[8],
        })
    return posts


def _get_post_daily_timeline(post_id):
    """Tagesweise Daten für einen einzelnen Post."""
    with connection.cursor() as cur:
        cur.execute("SHOW COLUMNS FROM linkedin_posts")
        cols = {row[0].lower() for row in cur.fetchall()}

    select_parts = ["date", "COALESCE(impressions, 0) AS impressions"]
    if 'clicks' in cols:
        select_parts.append("COALESCE(clicks, 0) AS clicks")
    else:
        select_parts.append("0 AS clicks")
    if 'likes' in cols:
        select_parts.append("COALESCE(likes, 0) AS likes")
    else:
        select_parts.append("0 AS likes")

    sql = f"""
        SELECT {', '.join(select_parts)}
        FROM linkedin_posts
        WHERE post_id = %s
        ORDER BY date
    """
    with connection.cursor() as cur:
        cur.execute(sql, [post_id])
        rows = cur.fetchall()
    return [{'date': r[0], 'impressions': r[1], 'clicks': r[2], 'likes': r[3]} for r in rows]


# ──────────────────────────────────────────────────────────
# Views
# ──────────────────────────────────────────────────────────
@login_required
def overview(request):
    d_from, d_to = _get_date_range(request)
    try:
        kpis = _get_overview_kpis(d_from, d_to)
        db_error = None
    except Exception as e:
        kpis = {k: '—' for k in ('total_posts','total_impressions','total_clicks',
                                   'total_likes','total_comments','total_shares')}
        db_error = str(e)

    return render(request, 'linkedin_statistics/overview.html', {
        'active_tab':  'overview',
        'date_from':   _fmt(d_from),
        'date_to':     _fmt(d_to),
        'default_from': _fmt(date.today() - timedelta(days=30)),
        'default_to':   _fmt(date.today()),
        'kpis':        kpis,
        'db_error':    db_error,
    })


@login_required
def timeline(request):
    d_from, d_to = _get_date_range(request)
    try:
        posts    = _get_timeline_posts(d_from, d_to)
        db_error = None
    except Exception as e:
        posts    = []
        db_error = str(e)

    return render(request, 'linkedin_statistics/timeline.html', {
        'active_tab':  'timeline',
        'date_from':   _fmt(d_from),
        'date_to':     _fmt(d_to),
        'default_from': _fmt(date.today() - timedelta(days=30)),
        'default_to':   _fmt(date.today()),
        'posts':       posts,
        'db_error':    db_error,
    })
EOF
echo "  OK"

# ── SCHRITT 5: URLs ───────────────────────────────────────
echo ""
echo "[5/7] urls.py ..."
cat > linkedin_statistics/urls.py << 'EOF'
from django.urls import path
from . import views

app_name = 'linkedin_statistics'

urlpatterns = [
    path('',          views.overview, name='overview'),
    path('timeline/', views.timeline, name='timeline'),
]
EOF
echo "  OK"

# ── SCHRITT 6: Templates ──────────────────────────────────
echo ""
echo "[6/7] Templates ..."

# base_stats.html (Sub-Navigation)
cat > linkedin_statistics/templates/linkedin_statistics/base_stats.html << 'EOF'
{% extends "core/base.html" %}
{% load static %}
{% block title %}Statistics – LinkedIn Dashboard{% endblock %}

{% block content %}
<!-- Statistics Sub-Navigation -->
<div class="sub-nav" style="background:var(--octo-light-gray);padding:0 1.5rem;display:flex;gap:0;border-bottom:2px solid #e0e0e0;">
  <a href="/statistics/" {% if active_tab == 'overview' %}class="active"{% endif %}
     style="padding:0.5rem 1.2rem;font-size:0.9rem;text-decoration:none;color:var(--octo-dark-petrol);border-bottom:2px solid transparent;">
    📊 Overview
  </a>
  <a href="/statistics/timeline/" {% if active_tab == 'timeline' %}class="active"{% endif %}
     style="padding:0.5rem 1.2rem;font-size:0.9rem;text-decoration:none;color:var(--octo-dark-petrol);border-bottom:2px solid transparent;">
    📈 Post Timeline
  </a>
</div>

<!-- Datumsfilter -->
<div style="background:#fff;border:1px solid #e0e0e0;border-radius:8px;padding:12px 20px;margin:1rem 0;display:flex;align-items:center;gap:12px;flex-wrap:wrap;">
  <span style="font-size:13px;font-weight:600;color:#555;">Date range:</span>
  <form method="get" style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
    <input type="date" name="from" value="{{ date_from }}"
           style="padding:6px 10px;border:1px solid #ccc;border-radius:6px;font-size:13px;">
    <span style="color:#888;font-size:13px;">to</span>
    <input type="date" name="to" value="{{ date_to }}"
           style="padding:6px 10px;border:1px solid #ccc;border-radius:6px;font-size:13px;">
    <button type="submit"
            style="padding:6px 16px;background:#008591;color:#fff;border:none;border-radius:6px;font-size:13px;font-weight:600;cursor:pointer;">
      Apply
    </button>
    <a href="?from={{ default_from }}&to={{ default_to }}"
       style="padding:6px 16px;background:#F56E28;color:#fff;border-radius:6px;font-size:13px;font-weight:600;text-decoration:none;">
      Last 30 days
    </a>
  </form>
</div>

{% if db_error %}
<div style="background:#fce4ec;color:#c62828;padding:12px 16px;border-radius:8px;margin-bottom:1rem;font-size:13px;">
  ⚠️ Datenbankfehler: {{ db_error }}
</div>
{% endif %}

{% block stats_content %}{% endblock %}
{% endblock %}
EOF

# overview.html
cat > linkedin_statistics/templates/linkedin_statistics/overview.html << 'EOF'
{% extends "linkedin_statistics/base_stats.html" %}
{% block stats_content %}

<h2 style="color:var(--octo-petrol);margin-bottom:1rem;">📊 Overview</h2>

<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:16px;margin-bottom:2rem;">
  {% for label, val, color in kpi_cards %}
  <div style="background:#fff;border-radius:10px;border:1px solid #e0e0e0;padding:20px 16px;box-shadow:0 1px 4px rgba(0,0,0,.07);">
    <div style="font-size:11px;font-weight:700;color:#888;letter-spacing:.5px;text-transform:uppercase;margin-bottom:6px;">{{ label }}</div>
    <div style="font-size:26px;font-weight:800;color:{{ color }};">{{ val }}</div>
  </div>
  {% endfor %}
</div>

<p style="color:#999;font-size:12px;">Zeitraum: {{ date_from }} bis {{ date_to }}</p>

{% endblock %}
EOF

# timeline.html
cat > linkedin_statistics/templates/linkedin_statistics/timeline.html << 'EOF'
{% extends "linkedin_statistics/base_stats.html" %}
{% block stats_content %}

<h2 style="color:var(--octo-petrol);margin-bottom:1rem;">📈 Post Timeline – All Posts</h2>

{% if posts %}
<div style="display:flex;flex-direction:column;gap:16px;">
  {% for post in posts %}
  <div style="background:#fff;border:1px solid #e0e0e0;border-radius:10px;padding:18px 20px;box-shadow:0 1px 4px rgba(0,0,0,.06);">
    <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:8px;margin-bottom:10px;">
      <div>
        <span style="font-size:11px;color:#888;font-weight:600;">POST ID</span>
        <div style="font-size:14px;font-weight:700;color:#005F68;margin-top:2px;">
          {% if post.post_link %}
            <a href="{{ post.post_link }}" target="_blank"
               style="color:#008591;text-decoration:none;">{{ post.post_id }}</a>
          {% else %}
            {{ post.post_id }}
          {% endif %}
        </div>
      </div>
      <div style="text-align:right;">
        <span style="font-size:11px;color:#888;">Gepostet am</span>
        <div style="font-size:13px;font-weight:600;color:#333;margin-top:2px;">
          {% if post.posted_on %}{{ post.posted_on }}{% else %}—{% endif %}
        </div>
      </div>
    </div>

    <!-- KPI-Zeile -->
    <div style="display:flex;gap:24px;flex-wrap:wrap;border-top:1px solid #f0f0f0;padding-top:10px;">
      <div>
        <span style="font-size:10px;color:#aaa;font-weight:700;text-transform:uppercase;">Impressions</span>
        <div style="font-size:18px;font-weight:800;color:#008591;">{{ post.total_impressions }}</div>
      </div>
      <div>
        <span style="font-size:10px;color:#aaa;font-weight:700;text-transform:uppercase;">Clicks</span>
        <div style="font-size:18px;font-weight:800;color:#F56E28;">{{ post.total_clicks }}</div>
      </div>
      <div>
        <span style="font-size:10px;color:#aaa;font-weight:700;text-transform:uppercase;">Likes</span>
        <div style="font-size:18px;font-weight:800;color:#61CEBC;">{{ post.total_likes }}</div>
      </div>
      <div>
        <span style="font-size:10px;color:#aaa;font-weight:700;text-transform:uppercase;">Comments</span>
        <div style="font-size:18px;font-weight:800;color:#555;">{{ post.total_comments }}</div>
      </div>
      <div style="margin-left:auto;font-size:11px;color:#bbb;align-self:flex-end;">
        Daten: {{ post.first_data_date }} – {{ post.last_data_date }}
      </div>
    </div>
  </div>
  {% endfor %}
</div>

{% else %}
<div style="background:#fff;border:1px solid #e0e0e0;border-radius:10px;padding:48px;text-align:center;color:#999;">
  No post data found. Please import LinkedIn CSV data first.
</div>
{% endif %}

{% endblock %}
EOF
echo "  Templates OK"

# ── SCHRITT 7: dashboard/urls.py + base.html patchen ─────
echo ""
echo "[7/7] urls.py + base.html ..."

# urls.py: statistics-Route einfügen (falls nicht da)
URLS_FILE="dashboard/urls.py"
if ! grep -q "linkedin_statistics" "$URLS_FILE"; then
    sed -i 's|path("collectives/", include("collectives.urls"))|path("collectives/", include("collectives.urls")),\n    path("statistics/", include("linkedin_statistics.urls")),|' "$URLS_FILE"
    echo "  statistics-Route in urls.py eingefügt."
else
    echo "  statistics-Route bereits vorhanden."
fi

# base.html: Doppelten Statistics-Link entfernen, genau einen sicherstellen
# Suche in allen möglichen base.html-Pfaden
for BASE in core/templates/core/base.html templates/core/base.html; do
    if [ -f "$BASE" ]; then
        # Entferne alle /statistics/-Links
        python3 - "$BASE" << 'PYEOF'
import sys, re
path = sys.argv[1]
with open(path) as f:
    content = f.read()

# Entferne alle vorhandenen Statistics-Links (verschiedene Varianten)
content = re.sub(r'\s*<a[^>]*/statistics/[^>]*>[^<]*</a>', '', content)

# Füge Statistics-Link genau einmal ein (nach Collectives)
if '/statistics/' not in content:
    content = content.replace(
        'href="/collectives/"',
        'href="/collectives/"'
    )
    # Füge nach dem Collectives-Link ein
    content = re.sub(
        r'(<a[^>]*href="/collectives/"[^>]*>[^<]*</a>)',
        r'\1\n    <a href="/statistics/" {% if \'/statistics/\' in request.path %}class="active"{% endif %}>Statistics</a>',
        content
    )
    print(f"  Statistics-Link in {path} eingefügt.")
else:
    print(f"  {path}: Statistics-Link bereits korrekt vorhanden.")

with open(path, 'w') as f:
    f.write(content)
PYEOF
    fi
done

echo ""
echo "=================================================="
echo "  FERTIG – jetzt ausführen:"
echo "  python manage.py runserver 0.0.0.0:8000"
echo "  → http://localhost:8000/statistics/"
echo "=================================================="
