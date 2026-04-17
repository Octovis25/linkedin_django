#!/bin/bash
##############################################################
# deploy_timeline_v2.sh
# Post Timeline – neuer Flow:
#  1. Zeitraum wählen → Post-Liste
#  2. Post anklicken → individuelle Timeline-Grafik
##############################################################
set -e
cd /opt/render/project/src 2>/dev/null || cd "$(dirname "$0")"

STAT_APP="linkedin_statistics"
STAT_TPL="${STAT_APP}/templates/${STAT_APP}"
mkdir -p "${STAT_TPL}"

echo "=== 1. views.py ==="
cat > "${STAT_APP}/views.py" << 'PYEOF'
"""
linkedin_statistics/views.py
Timeline Flow:
  1. timeline()       – Zeitraum-Filter → Post-Liste (klickbar)
  2. timeline_detail()– Grafik für einen einzelnen Post
"""
from datetime import date, timedelta
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.db import connection
import json


# ── Hilfsfunktionen ───────────────────────────────────────────

def _default_from():
    return (date.today() - timedelta(days=30)).isoformat()

def _default_to():
    return date.today().isoformat()

def _fmt_date(val):
    """Gibt das Datum als String zurück oder ''."""
    if not val:
        return ''
    return str(val)[:10]


def _posts_in_range(date_from, date_to):
    """
    Alle Posts, die im Zeitraum gepostet wurden.
    Führende Tabelle: linkedin_posts  (hat alle 45 Posts)
    Datum: COALESCE(pp.post_date, lp.post_date)
    """
    sql = """
        SELECT
            lp.post_id,
            COALESCE(lp.post_title, lp.post_id)          AS post_title,
            COALESCE(pp.post_date, lp.post_date)          AS post_date,
            COALESCE(lp.post_url, pp.post_link)           AS post_url,
            lp.content_type,
            lp.post_distribution
        FROM linkedin_posts lp
        LEFT JOIN linkedin_posts_posted pp ON lp.post_id = pp.post_id
        WHERE COALESCE(pp.post_date, lp.post_date) BETWEEN %s AND %s
        ORDER BY COALESCE(pp.post_date, lp.post_date) DESC
    """
    with connection.cursor() as cur:
        cur.execute(sql, [date_from, date_to])
        cols = [c[0] for c in cur.description]
        rows = cur.fetchall()
    return [dict(zip(cols, r)) for r in rows]


def _post_detail(post_id):
    """Stammdaten eines Posts."""
    sql = """
        SELECT
            lp.post_id,
            COALESCE(lp.post_title, lp.post_id)   AS post_title,
            COALESCE(pp.post_date, lp.post_date)   AS post_date,
            COALESCE(lp.post_url, pp.post_link)    AS post_url
        FROM linkedin_posts lp
        LEFT JOIN linkedin_posts_posted pp ON lp.post_id = pp.post_id
        WHERE lp.post_id = %s
        LIMIT 1
    """
    with connection.cursor() as cur:
        cur.execute(sql, [post_id])
        cols = [c[0] for c in cur.description]
        row  = cur.fetchone()
    if not row:
        return None
    return dict(zip(cols, row))


def _post_metrics(post_id, group_by):
    """
    Zeitreihe der Metriken aus linkedin_posts_metrics.
    Aggregiert nach Tag / Woche / Monat ab dem Post-Datum.
    """
    if group_by == 'week':
        period_sql   = "DATE_FORMAT(m.metric_date, '%x-W%v')"
        label_sql    = "DATE_FORMAT(MIN(m.metric_date), '%d.%m.%Y')"
    elif group_by == 'month':
        period_sql   = "DATE_FORMAT(m.metric_date, '%Y-%m')"
        label_sql    = "DATE_FORMAT(MIN(m.metric_date), '%m/%Y')"
    else:  # day
        period_sql   = "DATE(m.metric_date)"
        label_sql    = "DATE_FORMAT(MIN(m.metric_date), '%d.%m.%Y')"

    sql = f"""
        SELECT
            {period_sql}                              AS period_key,
            {label_sql}                               AS label,
            COALESCE(SUM(m.impressions),   0)         AS impressions,
            COALESCE(SUM(m.clicks),        0)         AS clicks,
            COALESCE(SUM(m.likes),         0)         AS likes,
            COALESCE(SUM(m.comments),      0)         AS comments,
            COALESCE(SUM(m.direct_shares), 0)         AS shares
        FROM linkedin_posts_metrics m
        WHERE m.post_id = %s
        GROUP BY period_key
        ORDER BY period_key ASC
    """
    with connection.cursor() as cur:
        cur.execute(sql, [post_id])
        cols = [c[0] for c in cur.description]
        rows = cur.fetchall()
    return [dict(zip(cols, r)) for r in rows]


# ── Views ─────────────────────────────────────────────────────

@login_required
def overview(request):
    return render(request, f'{__package__}/overview.html', {'active_tab': 'overview'})


@login_required
def timeline(request):
    """
    Schritt 1: Zeitraum wählen → Post-Liste.
    Jede Zeile ist klickbar → timeline_detail.
    """
    date_from = request.GET.get('date_from', _default_from())
    date_to   = request.GET.get('date_to',   _default_to())
    search    = request.GET.get('q', '').strip().lower()

    posts    = []
    db_error = None

    try:
        posts = _posts_in_range(date_from, date_to)
    except Exception as e:
        db_error = str(e)

    # Client-seitige Suche (Fallback serverseitig)
    if search:
        posts = [p for p in posts if
                 search in (p['post_title'] or '').lower() or
                 search in (p['post_id']    or '').lower()]

    return render(request, f'{__package__}/timeline.html', {
        'active_tab': 'timeline',
        'date_from':  date_from,
        'date_to':    date_to,
        'search':     search,
        'posts':      posts,
        'db_error':   db_error,
    })


@login_required
def timeline_detail(request, post_id):
    """
    Schritt 2: Grafik für einen einzelnen Post.
    """
    group_by = request.GET.get('group_by', 'week')
    db_error = None
    post     = None
    chart_data = None

    try:
        post = _post_detail(post_id)
        if post:
            rows = _post_metrics(post_id, group_by)
            if rows:
                chart_data = {
                    'labels':      [r['label']       for r in rows],
                    'impressions': [r['impressions']  for r in rows],
                    'clicks':      [r['clicks']       for r in rows],
                    'likes':       [r['likes']        for r in rows],
                    'comments':    [r['comments']     for r in rows],
                    'shares':      [r['shares']       for r in rows],
                }
    except Exception as e:
        db_error = str(e)

    return render(request, f'{__package__}/timeline_detail.html', {
        'active_tab':      'timeline',
        'post':            post,
        'group_by':        group_by,
        'chart_data_json': json.dumps(chart_data) if chart_data else 'null',
        'db_error':        db_error,
        # Zurück-Link
        'back_from':  request.GET.get('back_from', ''),
        'back_to':    request.GET.get('back_to', ''),
    })
PYEOF

echo "  ✅ views.py"

echo "=== 2. urls.py ==="
cat > "${STAT_APP}/urls.py" << 'URLEOF'
from django.urls import path
from . import views

app_name = 'linkedin_statistics'

urlpatterns = [
    path('',                        views.overview,         name='overview'),
    path('timeline/',               views.timeline,         name='timeline'),
    path('timeline/<str:post_id>/', views.timeline_detail,  name='timeline_detail'),
]
URLEOF
echo "  ✅ urls.py"

echo "=== 3. timeline.html (Post-Liste) ==="
cat > "${STAT_TPL}/timeline.html" << 'HTMLEOF'
{% extends "core/base.html" %}
{% block title %}Post Timeline{% endblock %}
{% block content %}
<style>
:root {
  --octo-teal:   #007c89;
  --octo-orange: #e07b39;
  --octo-bg:     #faf8f5;
  --octo-card:   #ffffff;
  --octo-border: #e2ddd8;
}
.tl-hero {
  padding: 1.4rem 0 .6rem;
  border-bottom: 2px solid var(--octo-border);
  margin-bottom: 1.4rem;
}
.tl-hero h1 { font-size: 1.3rem; color: var(--octo-teal); margin: 0; }
.tl-hero p  { color: #777; font-size: .88rem; margin: .3rem 0 0; }

/* Filter-Leiste */
.filter-bar {
  background: var(--octo-bg);
  border: 1px solid var(--octo-border);
  border-radius: 10px;
  padding: 1rem 1.3rem;
  display: flex;
  flex-wrap: wrap;
  gap: .9rem;
  align-items: flex-end;
  margin-bottom: 1.4rem;
}
.fg { display: flex; flex-direction: column; gap: .25rem; }
.fg label { font-size: .78rem; font-weight: 700; color: #555; text-transform: uppercase; letter-spacing: .03em; }
.fg input[type=date],
.fg input[type=search] {
  padding: .5rem .8rem;
  border: 1px solid #ccc;
  border-radius: 7px;
  font-size: .9rem;
  min-width: 150px;
}
.fg input[type=search] { min-width: 200px; }
.btn-teal {
  background: var(--octo-teal);
  color: #fff;
  border: none;
  border-radius: 7px;
  padding: .55rem 1.2rem;
  font-size: .88rem;
  font-weight: 700;
  cursor: pointer;
  margin-bottom: 1px;
}
.btn-teal:hover { opacity: .87; }
.btn-orange {
  background: var(--octo-orange);
  color: #fff;
  border: none;
  border-radius: 7px;
  padding: .55rem 1.1rem;
  font-size: .88rem;
  font-weight: 700;
  cursor: pointer;
  margin-bottom: 1px;
}
.btn-orange:hover { opacity: .87; }

/* Post-Tabelle */
.post-table-wrap {
  background: var(--octo-card);
  border-radius: 10px;
  border: 1px solid var(--octo-border);
  overflow: hidden;
}
.post-table-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: .9rem 1.2rem;
  border-bottom: 1px solid var(--octo-border);
}
.post-table-header h2 { font-size: 1rem; color: var(--octo-teal); margin: 0; }
.post-count { font-size: .82rem; color: #888; }

table { width: 100%; border-collapse: collapse; }
thead th {
  text-align: left;
  font-size: .75rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: .04em;
  color: #888;
  padding: .7rem 1rem;
  border-bottom: 2px solid var(--octo-border);
  background: #fafafa;
}
tbody tr {
  cursor: pointer;
  transition: background .13s;
}
tbody tr:hover { background: #f0f8f9; }
tbody tr:hover .post-title-cell { color: var(--octo-teal); }
tbody td {
  padding: .75rem 1rem;
  border-bottom: 1px solid #f0ece8;
  font-size: .88rem;
  vertical-align: middle;
}
.post-title-cell {
  font-weight: 600;
  color: #222;
  max-width: 420px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  transition: color .13s;
}
.badge-date {
  background: #e8f5f6;
  color: var(--octo-teal);
  padding: .2rem .6rem;
  border-radius: 20px;
  font-size: .78rem;
  font-weight: 700;
  white-space: nowrap;
}
.badge-type {
  background: #fff3ec;
  color: var(--octo-orange);
  padding: .2rem .6rem;
  border-radius: 20px;
  font-size: .75rem;
  white-space: nowrap;
}
.arrow-cell { color: #bbb; font-size: 1rem; text-align: right; }
.empty-state {
  text-align: center;
  padding: 3rem 1rem;
  color: #999;
}
.empty-state .icon { font-size: 2.5rem; margin-bottom: .5rem; }
.alert-error {
  background: #fde8e8;
  border-left: 4px solid #e53935;
  padding: .9rem 1.2rem;
  border-radius: 0 8px 8px 0;
  color: #b71c1c;
  font-size: .88rem;
  margin-bottom: 1rem;
}
</style>

<div class="tl-hero">
  <h1>📈 Post Timeline</h1>
  <p>Wähle einen Zeitraum → alle Posts darin erscheinen → Post anklicken für die detaillierte Metriken-Grafik.</p>
</div>

{% if db_error %}
<div class="alert-error">⚠️ {{ db_error }}</div>
{% endif %}

<form method="get" id="filterForm">
  <div class="filter-bar">
    <div class="fg">
      <label>Von</label>
      <input type="date" name="date_from" value="{{ date_from }}">
    </div>
    <div class="fg">
      <label>Bis</label>
      <input type="date" name="date_to" value="{{ date_to }}">
    </div>
    <div class="fg">
      <label>Suche</label>
      <input type="search" name="q" value="{{ search }}" placeholder="Titel / Post-ID…">
    </div>
    <button type="submit" class="btn-teal">🔍 Anzeigen</button>
    <button type="button" class="btn-orange" onclick="setLast30()">Letzte 30 Tage</button>
  </div>
</form>

<div class="post-table-wrap">
  <div class="post-table-header">
    <h2>📋 Posts im Zeitraum {{ date_from }} – {{ date_to }}</h2>
    <span class="post-count">{{ posts|length }} Post{{ posts|length|pluralize:"s" }}</span>
  </div>

  {% if posts %}
  <table>
    <thead>
      <tr>
        <th>Post-Datum</th>
        <th>Titel</th>
        <th>Typ</th>
        <th>Post-ID</th>
        <th></th>
      </tr>
    </thead>
    <tbody>
      {% for p in posts %}
      <tr onclick="window.location='{% url 'linkedin_statistics:timeline_detail' p.post_id %}?back_from={{ date_from }}&back_to={{ date_to }}'">
        <td><span class="badge-date">{{ p.post_date|default:"–" }}</span></td>
        <td class="post-title-cell" title="{{ p.post_title }}">{{ p.post_title|default:p.post_id|truncatechars:80 }}</td>
        <td>
          {% if p.content_type %}
          <span class="badge-type">{{ p.content_type }}</span>
          {% else %}–{% endif %}
        </td>
        <td style="color:#aaa;font-size:.78rem;font-family:monospace">{{ p.post_id }}</td>
        <td class="arrow-cell">›</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  {% else %}
  <div class="empty-state">
    <div class="icon">📭</div>
    <p>Keine Posts im gewählten Zeitraum gefunden.</p>
    <p style="font-size:.82rem;margin-top:.4rem">
      Bitte prüfe, ob das Post-Datum in <code>linkedin_posts_posted</code> oder <code>linkedin_posts</code> eingetragen ist.
    </p>
  </div>
  {% endif %}
</div>

<script>
function setLast30() {
  const to   = new Date();
  const from = new Date();
  from.setDate(from.getDate() - 30);
  const fmt = d => d.toISOString().slice(0,10);
  document.querySelector('[name=date_from]').value = fmt(from);
  document.querySelector('[name=date_to]').value   = fmt(to);
  document.getElementById('filterForm').submit();
}
</script>
{% endblock %}
HTMLEOF

echo "  ✅ timeline.html"

echo "=== 4. timeline_detail.html (Grafik) ==="
cat > "${STAT_TPL}/timeline_detail.html" << 'HTMLEOF'
{% extends "core/base.html" %}
{% block title %}Post Timeline – Detail{% endblock %}
{% block content %}
<style>
:root {
  --octo-teal:   #007c89;
  --octo-orange: #e07b39;
  --octo-border: #e2ddd8;
  --octo-bg:     #faf8f5;
}
.back-link {
  display: inline-flex;
  align-items: center;
  gap: .4rem;
  color: var(--octo-teal);
  text-decoration: none;
  font-size: .88rem;
  font-weight: 600;
  margin-bottom: 1.2rem;
}
.back-link:hover { opacity: .75; }

.detail-hero {
  background: linear-gradient(135deg, var(--octo-teal) 0%, #00a0b0 100%);
  color: #fff;
  padding: 1.3rem 1.6rem;
  border-radius: 10px;
  margin-bottom: 1.4rem;
}
.detail-hero h1 { font-size: 1.2rem; margin: 0 0 .3rem; }
.detail-hero .meta { font-size: .85rem; opacity: .85; display: flex; gap: 1.5rem; flex-wrap: wrap; }

/* Gruppen-Switcher */
.group-bar {
  display: flex;
  gap: .5rem;
  margin-bottom: 1.4rem;
  flex-wrap: wrap;
  align-items: center;
}
.group-bar span { font-size: .85rem; color: #666; margin-right: .3rem; }
.gb-btn {
  padding: .4rem 1rem;
  border-radius: 20px;
  border: 2px solid var(--octo-border);
  background: #fff;
  color: #555;
  font-size: .83rem;
  font-weight: 700;
  cursor: pointer;
  text-decoration: none;
  transition: all .15s;
}
.gb-btn:hover,
.gb-btn.active {
  border-color: var(--octo-teal);
  background: var(--octo-teal);
  color: #fff;
}

/* Chart-Karte */
.chart-card {
  background: #fff;
  border: 1px solid var(--octo-border);
  border-radius: 10px;
  padding: 1.4rem 1.6rem;
  margin-bottom: 1.4rem;
}
.chart-card h2 { font-size: 1rem; color: var(--octo-teal); margin: 0 0 1rem; }
.chart-wrap { position: relative; height: 380px; }

/* Metriken-Kacheln */
.kpi-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: .9rem;
  margin-bottom: 1.4rem;
}
.kpi-card {
  background: #fff;
  border: 1px solid var(--octo-border);
  border-radius: 10px;
  padding: 1rem 1.2rem;
  text-align: center;
}
.kpi-card .kpi-val { font-size: 1.6rem; font-weight: 800; color: #222; }
.kpi-card .kpi-lbl { font-size: .75rem; color: #888; text-transform: uppercase; letter-spacing: .04em; margin-top: .2rem; }

.alert-info {
  background: #e8f5f6;
  border-left: 4px solid var(--octo-teal);
  padding: .9rem 1.2rem;
  border-radius: 0 8px 8px 0;
  color: #005f6b;
  font-size: .88rem;
}
.alert-error {
  background: #fde8e8;
  border-left: 4px solid #e53935;
  padding: .9rem 1.2rem;
  border-radius: 0 8px 8px 0;
  color: #b71c1c;
  font-size: .88rem;
  margin-bottom: 1rem;
}
</style>

<a class="back-link" href="{% url 'linkedin_statistics:timeline' %}?date_from={{ back_from }}&date_to={{ back_to }}&{% if search %}q={{ search }}{% endif %}">
  ← Zurück zur Post-Liste
</a>

{% if db_error %}
<div class="alert-error">⚠️ {{ db_error }}</div>
{% endif %}

{% if post %}
<div class="detail-hero">
  <h1>{{ post.post_title|default:post.post_id|truncatechars:100 }}</h1>
  <div class="meta">
    <span>📅 {{ post.post_date|default:"Datum unbekannt" }}</span>
    <span>🆔 {{ post.post_id }}</span>
    {% if post.post_url %}
    <a href="{{ post.post_url }}" target="_blank" style="color:#fff;opacity:.9">🔗 LinkedIn öffnen</a>
    {% endif %}
  </div>
</div>

<!-- Gruppen-Switcher -->
<div class="group-bar">
  <span>Gruppierung:</span>
  <a href="?group_by=day&back_from={{ back_from }}&back_to={{ back_to }}"
     class="gb-btn {% if group_by == 'day' %}active{% endif %}">Tag</a>
  <a href="?group_by=week&back_from={{ back_from }}&back_to={{ back_to }}"
     class="gb-btn {% if group_by == 'week' %}active{% endif %}">Woche</a>
  <a href="?group_by=month&back_from={{ back_from }}&back_to={{ back_to }}"
     class="gb-btn {% if group_by == 'month' %}active{% endif %}">Monat</a>
</div>

{% if chart_data_json != 'null' %}

<!-- KPI-Kacheln (Summen) -->
<div class="kpi-grid" id="kpiGrid"></div>

<!-- Balkendiagramm -->
<div class="chart-card">
  <h2>📊 Interaktionen über Zeit ({{ group_by|capfirst }})</h2>
  <div class="chart-wrap">
    <canvas id="detailChart"></canvas>
  </div>
</div>

{% else %}
<div class="alert-info">
  ℹ️ Für diesen Post sind noch keine Metriken in <code>linkedin_posts_metrics</code> vorhanden.<br>
  Bitte prüfe, ob der LinkedIn-Export für Post-ID <strong>{{ post.post_id }}</strong> importiert wurde.
</div>
{% endif %}

{% else %}
<div class="alert-error">Post nicht gefunden.</div>
{% endif %}

<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.2/dist/chart.umd.min.js"></script>
<script>
const chartData = {{ chart_data_json|safe }};

if (chartData) {
  // ── KPI-Summen ──────────────────────────────────────────────
  const sum = arr => arr.reduce((a, b) => a + b, 0);
  const kpis = [
    { label: 'Impressionen', key: 'impressions', color: '#0077b5' },
    { label: 'Clicks',       key: 'clicks',      color: '#00a0dc' },
    { label: 'Likes',        key: 'likes',       color: '#e53935' },
    { label: 'Comments',     key: 'comments',    color: '#43a047' },
    { label: 'Shares',       key: 'shares',      color: '#f57c00' },
  ];
  const grid = document.getElementById('kpiGrid');
  kpis.forEach(k => {
    const total = sum(chartData[k.key]);
    grid.innerHTML += `
      <div class="kpi-card">
        <div class="kpi-val" style="color:${k.color}">${total.toLocaleString('de-DE')}</div>
        <div class="kpi-lbl">${k.label}</div>
      </div>`;
  });

  // ── Balkendiagramm ──────────────────────────────────────────
  const ctx = document.getElementById('detailChart').getContext('2d');
  new Chart(ctx, {
    type: 'bar',
    data: {
      labels: chartData.labels,
      datasets: [
        { label: 'Impressionen', data: chartData.impressions, backgroundColor: 'rgba(0,119,181,.75)',  borderRadius: 4 },
        { label: 'Clicks',       data: chartData.clicks,      backgroundColor: 'rgba(0,160,220,.75)',  borderRadius: 4 },
        { label: 'Likes',        data: chartData.likes,       backgroundColor: 'rgba(229,57,53,.75)',  borderRadius: 4 },
        { label: 'Comments',     data: chartData.comments,    backgroundColor: 'rgba(67,160,71,.75)',  borderRadius: 4 },
        { label: 'Shares',       data: chartData.shares,      backgroundColor: 'rgba(245,124,0,.75)',  borderRadius: 4 },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { position: 'top' },
        tooltip: { mode: 'index', intersect: false },
      },
      scales: {
        x: { grid: { display: false } },
        y: {
          beginAtZero: true,
          grid: { color: 'rgba(0,0,0,.04)' },
          title: { display: true, text: 'Anzahl' },
        },
      },
    },
  });
}
</script>
{% endblock %}
HTMLEOF

echo "  ✅ timeline_detail.html"

echo ""
echo "=== 5. Neustart ==="
supervisorctl restart web 2>/dev/null || \
  systemctl restart gunicorn 2>/dev/null || \
  pkill -HUP gunicorn 2>/dev/null || true

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  ✅  POST TIMELINE V2 DEPLOYED                               ║"
echo "║                                                              ║"
echo "║  Flow:                                                       ║"
echo "║  1. /statistics/timeline/                                   ║"
echo "║     → Zeitraum wählen (inkl. 'Letzte 30 Tage'-Button)       ║"
echo "║     → Post-Liste erscheint, jede Zeile klickbar             ║"
echo "║                                                              ║"
echo "║  2. /statistics/timeline/<post_id>/                         ║"
echo "║     → KPI-Kacheln (Summen) + Balkendiagramm                 ║"
echo "║     → Gruppierung: Tag / Woche / Monat                      ║"
echo "║     → Zurück-Button behält Zeitraum                         ║"
echo "╚══════════════════════════════════════════════════════════════╝"
