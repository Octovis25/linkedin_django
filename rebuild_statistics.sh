#!/bin/bash
set -e

echo "╔══════════════════════════════════════════════════════════╗"
echo "║  REBUILD: linkedin_statistics - KOMPLETT NEU             ║"
echo "║  Alle Dateien mit stat_ Prefix!                          ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

APP="linkedin_statistics"
TPL="${APP}/templates/${APP}"

# ══════════════════════════════════════════════════════════════
# SCHRITT 1: ALLES LOESCHEN
# ══════════════════════════════════════════════════════════════
echo "=== 1. Altes Modul komplett loeschen ==="
rm -rf "${APP}"
echo "  ✅ ${APP}/ geloescht"
echo ""

# ══════════════════════════════════════════════════════════════
# SCHRITT 2: Verzeichnisse anlegen
# ══════════════════════════════════════════════════════════════
echo "=== 2. Verzeichnisse anlegen ==="
mkdir -p "${TPL}"
echo "  ✅ ${TPL}/"
echo ""

# ══════════════════════════════════════════════════════════════
# SCHRITT 3: __init__.py (muss so heissen - Python-Pflicht)
# ══════════════════════════════════════════════════════════════
echo "=== 3. __init__.py ==="
cat > "${APP}/__init__.py" << 'EOF'
EOF
echo "  ✅ __init__.py"

# ══════════════════════════════════════════════════════════════
# SCHRITT 4: stat_apps.py
# ══════════════════════════════════════════════════════════════
echo "=== 4. stat_apps.py ==="
cat > "${APP}/stat_apps.py" << 'EOF'
from django.apps import AppConfig

class LinkedinStatisticsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'linkedin_statistics'
    verbose_name = 'LinkedIn Statistics'
EOF
echo "  ✅ stat_apps.py"

# ══════════════════════════════════════════════════════════════
# SCHRITT 5: stat_views.py
# ══════════════════════════════════════════════════════════════
echo "=== 5. stat_views.py ==="
cat > "${APP}/stat_views.py" << 'PYEOF'
"""
linkedin_statistics/stat_views.py
Komplett neu. MySQL. Alle KPIs: letzter Snapshot pro Post, dann aggregieren.
"""
from datetime import date, timedelta
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.db import connection


def _defaults():
    return (date.today() - timedelta(days=365)).isoformat(), date.today().isoformat()


def _safe(cur, sql, params=None):
    try:
        cur.execute(sql, params or [])
        return cur.fetchall()
    except Exception:
        return None


def _overview_data(d_from, d_to):
    data = {
        'total_followers': 0, 'followers_change': '—',
        'total_posts': 0, 'total_impressions': 0, 'total_engagement': 0,
        'top_posts': [],
        'chart_labels': [], 'chart_impressions': [], 'chart_engagement': [],
    }
    with connection.cursor() as c:

        rows = _safe(c, "SELECT followers_total FROM linkedin_followers ORDER BY date DESC LIMIT 1")
        if rows and rows[0][0]:
            data['total_followers'] = rows[0][0]

        rows = _safe(c, """
            SELECT
              (SELECT followers_total FROM linkedin_followers WHERE date <= %s ORDER BY date DESC LIMIT 1),
              (SELECT followers_total FROM linkedin_followers WHERE date <= %s ORDER BY date DESC LIMIT 1)
        """, [d_to, d_from])
        if rows and rows[0][0] is not None and rows[0][1] is not None:
            delta = rows[0][0] - rows[0][1]
            data['followers_change'] = f"+{delta}" if delta >= 0 else str(delta)

        rows = _safe(c, """
            SELECT COUNT(*) FROM linkedin_posts lp
            LEFT JOIN linkedin_posts_posted pp ON lp.post_id = pp.post_id
            WHERE COALESCE(pp.post_date, lp.post_date) BETWEEN %s AND %s
        """, [d_from, d_to])
        if rows:
            data['total_posts'] = rows[0][0] or 0

        rows = _safe(c, """
            SELECT COALESCE(SUM(sub.impressions), 0) FROM (
                SELECT m.impressions
                FROM linkedin_posts_metrics m
                INNER JOIN (
                    SELECT post_id, MAX(metric_date) AS max_date
                    FROM linkedin_posts_metrics GROUP BY post_id
                ) lat ON m.post_id = lat.post_id AND m.metric_date = lat.max_date
            ) sub
        """)
        if rows:
            data['total_impressions'] = rows[0][0] or 0

        rows = _safe(c, """
            SELECT COALESCE(SUM(sub.eng), 0) FROM (
                SELECT (m.likes + m.comments + m.direct_shares) AS eng
                FROM linkedin_posts_metrics m
                INNER JOIN (
                    SELECT post_id, MAX(metric_date) AS max_date
                    FROM linkedin_posts_metrics GROUP BY post_id
                ) lat ON m.post_id = lat.post_id AND m.metric_date = lat.max_date
            ) sub
        """)
        if rows:
            data['total_engagement'] = rows[0][0] or 0

        rows = _safe(c, """
            SELECT lp.post_id,
                   COALESCE(lp.post_title, lp.post_id),
                   COALESCE(pp.post_date, lp.post_date),
                   lp.post_url,
                   COALESCE(m.impressions, 0),
                   COALESCE(m.likes, 0),
                   COALESCE(m.comments, 0),
                   COALESCE(m.direct_shares, 0)
            FROM linkedin_posts lp
            LEFT JOIN linkedin_posts_posted pp ON lp.post_id = pp.post_id
            INNER JOIN linkedin_posts_metrics m ON lp.post_id = m.post_id
            INNER JOIN (
                SELECT post_id, MAX(metric_date) AS max_date
                FROM linkedin_posts_metrics GROUP BY post_id
            ) lat ON m.post_id = lat.post_id AND m.metric_date = lat.max_date
            ORDER BY m.impressions DESC
            LIMIT 5
        """)
        if rows:
            data['top_posts'] = [{
                'title': r[1], 'post_date': r[2], 'link': r[3] or '',
                'impressions': r[4], 'likes': r[5], 'comments': r[6], 'shares': r[7],
            } for r in rows]

        rows = _safe(c, """
            SELECT
                DATE_FORMAT(m.metric_date, '%%Y-%%m') AS monat,
                COALESCE(SUM(m.impressions), 0),
                COALESCE(AVG(m.engagement_rate) * 100, 0)
            FROM linkedin_posts_metrics m
            INNER JOIN (
                SELECT post_id,
                       DATE_FORMAT(metric_date, '%%Y-%%m') AS mm,
                       MAX(metric_date) AS max_date
                FROM linkedin_posts_metrics
                WHERE metric_date IS NOT NULL
                GROUP BY post_id, DATE_FORMAT(metric_date, '%%Y-%%m')
            ) lat ON m.post_id = lat.post_id AND m.metric_date = lat.max_date
            GROUP BY monat ORDER BY monat
        """)
        if rows:
            data['chart_labels'] = [r[0] for r in rows]
            data['chart_impressions'] = [int(r[1]) for r in rows]
            data['chart_engagement'] = [round(float(r[2]), 2) for r in rows]

    return data


@login_required
def overview(request):
    df, dt = _defaults()
    d_from = request.GET.get('from', df)
    d_to = request.GET.get('to', dt)
    return render(request, 'linkedin_statistics/stat_overview.html', {
        'data': _overview_data(d_from, d_to),
        'date_from': d_from, 'date_to': d_to, 'tab': 'overview',
    })


@login_required
def timeline(request):
    posts = []
    with connection.cursor() as c:
        rows = _safe(c, """
            SELECT lp.post_id,
                   COALESCE(lp.post_title, lp.post_id),
                   COALESCE(pp.post_date, lp.post_date),
                   lp.post_url, lp.content_type,
                   COALESCE(m.impressions, 0),
                   COALESCE(m.likes, 0),
                   COALESCE(m.comments, 0),
                   COALESCE(m.direct_shares, 0),
                   COALESCE(m.clicks, 0)
            FROM linkedin_posts lp
            LEFT JOIN linkedin_posts_posted pp ON lp.post_id = pp.post_id
            LEFT JOIN linkedin_posts_metrics m ON lp.post_id = m.post_id
            LEFT JOIN (
                SELECT post_id, MAX(metric_date) AS max_date
                FROM linkedin_posts_metrics GROUP BY post_id
            ) lat ON m.post_id = lat.post_id AND m.metric_date = lat.max_date
            WHERE lat.max_date IS NOT NULL OR m.id IS NULL
            ORDER BY COALESCE(pp.post_date, lp.post_date) DESC
        """)
        if rows:
            posts = [{
                'title': r[1], 'post_date': r[2], 'link': r[3] or '',
                'content_type': r[4] or '', 'impressions': r[5],
                'likes': r[6], 'comments': r[7], 'shares': r[8],
                'clicks': r[9], 'engagement': r[6]+r[7]+r[8],
            } for r in rows]
    return render(request, 'linkedin_statistics/stat_timeline.html', {
        'posts': posts, 'tab': 'timeline',
    })


@login_required
def timeline_detail(request, post_id):
    return timeline(request)
PYEOF
echo "  ✅ stat_views.py"

# ══════════════════════════════════════════════════════════════
# SCHRITT 6: stat_urls.py
# ══════════════════════════════════════════════════════════════
echo "=== 6. stat_urls.py ==="
cat > "${APP}/stat_urls.py" << 'EOF'
from django.urls import path
from . import stat_views

app_name = 'linkedin_statistics'

urlpatterns = [
    path('',                        stat_views.overview,         name='overview'),
    path('timeline/',               stat_views.timeline,         name='timeline'),
    path('timeline/<str:post_id>/', stat_views.timeline_detail,  name='timeline_detail'),
]
EOF
echo "  ✅ stat_urls.py (from . import stat_views)"

# ══════════════════════════════════════════════════════════════
# SCHRITT 7: stat_overview.html
# ══════════════════════════════════════════════════════════════
echo "=== 7. stat_overview.html ==="
cat > "${TPL}/stat_overview.html" << 'HTMLEOF'
{% extends "base.html" %}
{% block title %}Statistics – Overview{% endblock %}
{% block content %}
<style>
.sh{display:flex;justify-content:space-between;align-items:center;margin-bottom:1.5rem;flex-wrap:wrap;gap:1rem}
.sh h1{margin:0;font-size:1.5rem}
.df{display:flex;gap:.5rem;align-items:center}
.df input[type=date]{padding:.35rem .5rem;border:1px solid #ced4da;border-radius:.25rem;font-size:.85rem}
.df button{padding:.35rem .75rem;background:#0077B5;color:#fff;border:none;border-radius:.25rem;cursor:pointer;font-size:.85rem}
.tabs{display:flex;gap:0;margin-bottom:1.5rem;border-bottom:2px solid #dee2e6}
.tabs a{padding:.6rem 1.2rem;text-decoration:none;color:#6c757d;font-weight:500;border-bottom:2px solid transparent;margin-bottom:-2px}
.tabs a.on{color:#0077B5;border-bottom-color:#0077B5}
.kg{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:1rem;margin-bottom:2rem}
.kc{background:#fff;border-radius:.5rem;padding:1.25rem;box-shadow:0 1px 3px rgba(0,0,0,.1);text-align:center}
.ki{font-size:1.8rem;margin-bottom:.25rem}.kl{font-size:.8rem;color:#6c757d;text-transform:uppercase;letter-spacing:.5px}
.kv{font-size:1.6rem;font-weight:700;color:#212529}.ks{font-size:.75rem;color:#6c757d;margin-top:.25rem}
.cc{background:#fff;border-radius:.5rem;padding:1.5rem;box-shadow:0 1px 3px rgba(0,0,0,.1);margin-bottom:2rem}
.cc h2{font-size:1.1rem;margin-bottom:1rem}
.pt{width:100%;border-collapse:collapse;font-size:.85rem}
.pt th{text-align:left;padding:.5rem;border-bottom:2px solid #dee2e6;font-weight:600;color:#495057}
.pt td{padding:.5rem;border-bottom:1px solid #f0f0f0}
</style>

<div class="sh">
  <h1>📊 LinkedIn Statistics</h1>
  <form method="get" class="df">
    <label>Von</label><input type="date" name="from" value="{{ date_from }}">
    <label>Bis</label><input type="date" name="to" value="{{ date_to }}">
    <button type="submit">Anwenden</button>
  </form>
</div>

<div class="tabs">
  <a href="{% url 'linkedin_statistics:overview' %}" class="{% if tab == 'overview' %}on{% endif %}">Overview</a>
  <a href="{% url 'linkedin_statistics:timeline' %}" class="{% if tab == 'timeline' %}on{% endif %}">Timeline</a>
</div>

<div class="kg">
  <div class="kc"><div class="ki">👥</div><div class="kl">Followers</div><div class="kv">{{ data.total_followers }}</div><div class="ks">{{ data.followers_change }} im Zeitraum</div></div>
  <div class="kc"><div class="ki">📝</div><div class="kl">Posts</div><div class="kv">{{ data.total_posts }}</div><div class="ks">im Zeitraum</div></div>
  <div class="kc"><div class="ki">👁️</div><div class="kl">Impressions</div><div class="kv">{{ data.total_impressions }}</div><div class="ks">letzter Stand pro Post</div></div>
  <div class="kc"><div class="ki">❤️</div><div class="kl">Engagement</div><div class="kv">{{ data.total_engagement }}</div><div class="ks">Likes + Comments + Shares</div></div>
</div>

<div class="cc">
  <h2>📈 Content Metrics</h2>
  <canvas id="chart1" height="100"></canvas>
</div>

<div class="cc" style="padding:0">
  <h2 style="padding:1rem 1.5rem .5rem">🏆 Top 5 Posts</h2>
  {% if data.top_posts %}
  <table class="pt">
    <thead><tr><th>#</th><th>Post</th><th>Datum</th><th>Impressions</th><th>Likes</th><th>Comments</th><th>Shares</th></tr></thead>
    <tbody>
    {% for p in data.top_posts %}
    <tr>
      <td>{{ forloop.counter }}</td>
      <td>{% if p.link %}<a href="{{ p.link }}" target="_blank">{{ p.title|truncatechars:50 }}</a>{% else %}{{ p.title|truncatechars:50 }}{% endif %}</td>
      <td>{{ p.post_date|date:"d.m.Y"|default:"—" }}</td>
      <td>{{ p.impressions }}</td><td>{{ p.likes }}</td><td>{{ p.comments }}</td><td>{{ p.shares }}</td>
    </tr>
    {% endfor %}
    </tbody>
  </table>
  {% else %}<p style="padding:1.5rem;text-align:center;color:#6c757d">Keine Daten vorhanden.</p>{% endif %}
</div>

<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<script>
{% if data.chart_labels %}
new Chart(document.getElementById('chart1').getContext('2d'),{
  type:'line',
  data:{
    labels:{{ data.chart_labels|safe }},
    datasets:[
      {label:'Impressions',data:{{ data.chart_impressions|safe }},borderColor:'#2196F3',borderWidth:2,tension:.3,fill:false,yAxisID:'y',pointBackgroundColor:'#2196F3'},
      {label:'Engagement Rate %',data:{{ data.chart_engagement|safe }},borderColor:'#e53935',borderWidth:2,borderDash:[5,5],tension:.3,fill:false,yAxisID:'y1',pointBackgroundColor:'#e53935'}
    ]
  },
  options:{
    responsive:true,
    interaction:{mode:'index',intersect:false},
    plugins:{legend:{position:'bottom'}},
    scales:{
      y:{type:'linear',position:'left',title:{display:true,text:'Impressions'},beginAtZero:true},
      y1:{type:'linear',position:'right',title:{display:true,text:'Engagement %'},grid:{drawOnChartArea:false},beginAtZero:true}
    }
  }
});
{% else %}
document.getElementById('chart1').parentElement.innerHTML+='<p style="text-align:center;color:#6c757d">Keine Chart-Daten.</p>';
{% endif %}
</script>
{% endblock %}
HTMLEOF
echo "  ✅ stat_overview.html"

# ══════════════════════════════════════════════════════════════
# SCHRITT 8: stat_timeline.html
# ══════════════════════════════════════════════════════════════
echo "=== 8. stat_timeline.html ==="
cat > "${TPL}/stat_timeline.html" << 'HTMLEOF'
{% extends "base.html" %}
{% block title %}Statistics – Timeline{% endblock %}
{% block content %}
<style>
.sh{display:flex;justify-content:space-between;align-items:center;margin-bottom:1.5rem;flex-wrap:wrap;gap:1rem}
.sh h1{margin:0;font-size:1.5rem}
.tabs{display:flex;gap:0;margin-bottom:1.5rem;border-bottom:2px solid #dee2e6}
.tabs a{padding:.6rem 1.2rem;text-decoration:none;color:#6c757d;font-weight:500;border-bottom:2px solid transparent;margin-bottom:-2px}
.tabs a.on{color:#0077B5;border-bottom-color:#0077B5}
.cc{background:#fff;border-radius:.5rem;padding:1.5rem;box-shadow:0 1px 3px rgba(0,0,0,.1)}
.pt{width:100%;border-collapse:collapse;font-size:.85rem}
.pt th{text-align:left;padding:.5rem;border-bottom:2px solid #dee2e6;font-weight:600;color:#495057}
.pt td{padding:.5rem;border-bottom:1px solid #f0f0f0}
</style>

<div class="sh"><h1>📊 LinkedIn Statistics</h1></div>

<div class="tabs">
  <a href="{% url 'linkedin_statistics:overview' %}" class="{% if tab == 'overview' %}on{% endif %}">Overview</a>
  <a href="{% url 'linkedin_statistics:timeline' %}" class="{% if tab == 'timeline' %}on{% endif %}">Timeline</a>
</div>

<div class="cc">
  <h2>📊 Alle Posts</h2>
  {% if posts %}
  <table class="pt">
    <thead><tr><th>Post</th><th>Datum</th><th>Typ</th><th>Impressions</th><th>Engagement</th><th>Link</th></tr></thead>
    <tbody>
    {% for p in posts %}
    <tr>
      <td><small>{{ p.title|truncatechars:60 }}</small></td>
      <td>{{ p.post_date|date:"d.m.Y"|default:"—" }}</td>
      <td>{{ p.content_type|default:"—" }}</td>
      <td>{{ p.impressions }}</td>
      <td>{{ p.engagement }}</td>
      <td>{% if p.link %}<a href="{{ p.link }}" target="_blank">🔗</a>{% else %}—{% endif %}</td>
    </tr>
    {% endfor %}
    </tbody>
  </table>
  {% else %}<p style="text-align:center;color:#6c757d;padding:2rem">Keine Posts gefunden.</p>{% endif %}
</div>
{% endblock %}
HTMLEOF
echo "  ✅ stat_timeline.html"

# ══════════════════════════════════════════════════════════════
# SCHRITT 9: Haupt-urls.py pruefen/korrigieren
# ══════════════════════════════════════════════════════════════
echo ""
echo "=== 9. Haupt-urls.py pruefen ==="
# Die Haupt-urls.py muss linkedin_statistics.stat_urls einbinden!
MAIN_URLS=$(find . -path "*/urls.py" -not -path "./${APP}/*" -not -path "./.git/*" -not -path "*/migrations/*" 2>/dev/null | xargs grep -l "urlpatterns" 2>/dev/null | head -1)
if [ -n "$MAIN_URLS" ]; then
    echo "  Gefunden: $MAIN_URLS"
    # Pruefen ob alter oder neuer Include drin ist
    if grep -q "linkedin_statistics.stat_urls" "$MAIN_URLS"; then
        echo "  ✅ Korrekt: linkedin_statistics.stat_urls"
    elif grep -q "linkedin_statistics.urls" "$MAIN_URLS"; then
        echo "  ⚠️  Alter Include gefunden: linkedin_statistics.urls → korrigiere..."
        sed -i "s|linkedin_statistics\.urls|linkedin_statistics.stat_urls|g" "$MAIN_URLS"
        echo "  ✅ Korrigiert zu linkedin_statistics.stat_urls"
    elif grep -q "linkedin_statistics" "$MAIN_URLS"; then
        echo "  ⚠️  linkedin_statistics gefunden aber nicht als stat_urls:"
        grep "linkedin_statistics" "$MAIN_URLS"
        sed -i "s|linkedin_statistics\.urls|linkedin_statistics.stat_urls|g" "$MAIN_URLS"
    else
        echo "  ❌ FEHLT! Fuege manuell in die Haupt-urls.py ein:"
        echo "     path('statistics/', include('linkedin_statistics.stat_urls')),"
    fi
else
    echo "  ⚠️  Haupt-urls.py nicht eindeutig gefunden"
fi

# ══════════════════════════════════════════════════════════════
# SCHRITT 10: INSTALLED_APPS pruefen
# ══════════════════════════════════════════════════════════════
echo ""
echo "=== 10. INSTALLED_APPS pruefen ==="
SETTINGS=$(find . -path "*/settings.py" -not -path "./${APP}/*" -not -path "./.git/*" 2>/dev/null | head -1)
if [ -n "$SETTINGS" ]; then
    if grep -q "linkedin_statistics" "$SETTINGS"; then
        echo "  ✅ linkedin_statistics in INSTALLED_APPS"
    else
        echo "  ⚠️  FEHLT → fuege ein..."
        sed -i "/INSTALLED_APPS/,/]/{
            /dashboard/a\\    'linkedin_statistics',
        }" "$SETTINGS" 2>/dev/null
        grep -q "linkedin_statistics" "$SETTINGS" && echo "  ✅ Eingefuegt!" || echo "  ❌ Bitte manuell einfuegen!"
    fi
fi

# ══════════════════════════════════════════════════════════════
# ERGEBNIS
# ══════════════════════════════════════════════════════════════
echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║  ERGEBNIS                                                ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
find "${APP}" -type f | sort
echo ""
echo "ALLES mit stat_ Prefix:"
echo "  stat_apps.py"
echo "  stat_views.py"
echo "  stat_urls.py"
echo "  stat_overview.html"
echo "  stat_timeline.html"
echo "  (__init__.py = Python-Pflicht, bleibt so)"
echo ""
echo "Haupt-urls.py Include muss sein:"
echo "  path('statistics/', include('linkedin_statistics.stat_urls')),"
echo ""
echo "Naechste Schritte:"
echo "  python manage.py check"
echo "  python manage.py runserver"
echo "  git add -A && git commit -m 'rebuild: linkedin_statistics komplett neu mit stat_ prefix' && git push"
