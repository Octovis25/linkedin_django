#!/usr/bin/env bash
set -euo pipefail
cd /workspaces/linkedin_django

echo "=== Backup ==="
S=$(date +%Y%m%d_%H%M%S)
cp linkedin_statistics/stat_views.py "linkedin_statistics/stat_views.py.bak.${S}" 2>/dev/null || true
cp linkedin_statistics/templates/linkedin_statistics/stat_overview.html \
   "linkedin_statistics/templates/linkedin_statistics/stat_overview.html.bak.${S}" 2>/dev/null || true

# ═══════════════════════════════════════════════
#  stat_views.py
# ═══════════════════════════════════════════════
cat > linkedin_statistics/stat_views.py << 'PYEOF'
"""linkedin_statistics/stat_views.py – FINAL (2026-04-18)

Datenquelle fuer Charts: linkedin_content_metrics (NICHT linkedin_posts_metrics!)
  - metric_date = X-Achse
  - Aggregation: SUM pro Tag/Woche/Monat
  - impressions_total, clicks_total, reactions_total, comments_total,
    shares_direct_total, engagement_rate_total

KPI-Kacheln: Immer letzter Stand (unabhaengig Von/Bis).
"""

import json
from datetime import date, timedelta

from django.contrib.auth.decorators import login_required
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import render


def _defaults():
    return (date.today() - timedelta(days=365)).isoformat(), date.today().isoformat()


def _safe(cur, sql, params=None):
    try:
        cur.execute(sql, params or [])
        return cur.fetchall()
    except Exception:
        return None


def _period_fmt(group_by):
    group_by = (group_by or 'month').lower()
    if group_by == 'day':
        return '%Y-%m-%d'
    if group_by == 'week':
        return '%x-W%v'
    return '%Y-%m'


def _agg_text(group_by):
    return {'day': 'tagesweise', 'week': 'wochenweise', 'month': 'monatsweise'}.get(
        (group_by or 'month').lower(), 'monatsweise')


# ── Chart-Daten aus linkedin_content_metrics ──
def _chart_series(d_from, d_to, group_by):
    """SUM ueber linkedin_content_metrics, gruppiert nach Periode."""
    fmt = _period_fmt(group_by)
    sql = """
        SELECT DATE_FORMAT(metric_date, %s) AS period,
               COALESCE(SUM(impressions_total), 0),
               COALESCE(SUM(clicks_total), 0),
               COALESCE(SUM(reactions_total), 0),
               COALESCE(SUM(comments_total), 0),
               COALESCE(SUM(shares_direct_total), 0)
        FROM linkedin_content_metrics
        WHERE metric_date BETWEEN %s AND %s
        GROUP BY period
        ORDER BY period
    """
    with connection.cursor() as c:
        rows = _safe(c, sql, [fmt, d_from, d_to])
    if not rows:
        return [], [], [], [], [], [], []

    labels, imps, clicks, reactions, comments, shares, eng_rate = [], [], [], [], [], [], []
    for r in rows:
        labels.append(r[0])
        imp = int(r[1] or 0)
        cli = int(r[2] or 0)
        rea = int(r[3] or 0)
        com = int(r[4] or 0)
        sha = int(r[5] or 0)
        imps.append(imp)
        clicks.append(cli)
        reactions.append(rea)
        comments.append(com)
        shares.append(sha)
        total_int = rea + com + sha
        eng_rate.append(round((total_int / imp * 100) if imp else 0, 2))

    return labels, imps, clicks, reactions, comments, shares, eng_rate


# ── KPI: immer letzter Stand ──
def _kpi_snapshot():
    kpi = {
        'total_followers': 0, 'followers_date': None,
        'total_posts': 0, 'posts_date': None,
        'total_impressions': 0, 'total_engagement': 0, 'metrics_date': None,
    }
    with connection.cursor() as c:
        # Followers
        rows = _safe(c, "SELECT followers_total, date FROM linkedin_followers ORDER BY date DESC LIMIT 1")
        if rows and rows[0][0] is not None:
            kpi['total_followers'] = rows[0][0]
            kpi['followers_date'] = rows[0][1]

        # Posts
        rows = _safe(c, """
            SELECT COUNT(*), MAX(COALESCE(pp.post_date, lp.post_date))
            FROM linkedin_posts lp
            LEFT JOIN linkedin_posts_posted pp ON lp.post_id = pp.post_id
        """)
        if rows:
            kpi['total_posts'] = rows[0][0] or 0
            kpi['posts_date'] = rows[0][1]

        # Impressions + Engagement aus linkedin_content_metrics (letztes metric_date)
        rows = _safe(c, """
            SELECT COALESCE(SUM(impressions_total), 0),
                   COALESCE(SUM(reactions_total), 0) + COALESCE(SUM(comments_total), 0) + COALESCE(SUM(shares_direct_total), 0),
                   MAX(metric_date)
            FROM linkedin_content_metrics
        """)
        if rows and rows[0]:
            kpi['total_impressions'] = rows[0][0] or 0
            kpi['total_engagement'] = rows[0][1] or 0
            kpi['metrics_date'] = rows[0][2]
    return kpi


# ── Top 5 Tabellen (aus linkedin_posts_metrics – post-level) ──
def _top5(cursor):
    base = """
        SELECT lp.post_id, COALESCE(lp.post_title, lp.post_id),
               COALESCE(pp.post_date, lp.post_date), lp.post_url,
               m.impressions, m.clicks, m.likes, m.comments, m.direct_shares
        FROM linkedin_posts lp
        LEFT JOIN linkedin_posts_posted pp ON lp.post_id = pp.post_id
        INNER JOIN linkedin_posts_metrics m ON lp.post_id = m.post_id
        WHERE m.metric_date = (
            SELECT MAX(m2.metric_date) FROM linkedin_posts_metrics m2
            WHERE m2.post_id = m.post_id)
    """
    def to_list(rows):
        return [{
            'title': r[1], 'post_date': r[2], 'link': r[3] or '',
            'impressions': r[4] or 0, 'clicks': r[5] or 0,
            'likes': r[6] or 0, 'comments': r[7] or 0, 'shares': r[8] or 0,
            'engagement': (r[6] or 0) + (r[7] or 0) + (r[8] or 0),
        } for r in (rows or [])]

    by_imp = _safe(cursor, base + " ORDER BY m.impressions DESC LIMIT 5")
    by_eng = _safe(cursor, base + " ORDER BY (m.likes+m.comments+m.direct_shares) DESC LIMIT 5")
    return to_list(by_imp), to_list(by_eng)


@login_required
def overview(request):
    df, dt = _defaults()
    d_from = request.GET.get('from', df)
    d_to = request.GET.get('to', dt)
    group_by = request.GET.get('group_by', 'month')

    kpi = _kpi_snapshot()
    with connection.cursor() as c:
        top_imp, top_eng = _top5(c)

    labels, imps, clicks, reactions, comments, shares, eng_rate = _chart_series(d_from, d_to, group_by)

    return render(request, 'linkedin_statistics/stat_overview.html', {
        'kpi': kpi,
        'top_posts_impressions': top_imp,
        'top_posts_engagement': top_eng,
        'date_from': d_from,
        'date_to': d_to,
        'tab': 'overview',
        'group_by': group_by,
        'agg_text': _agg_text(group_by),
        'chart_labels_json': json.dumps(labels),
        'chart_impressions_json': json.dumps(imps),
        'chart_engagement_json': json.dumps(eng_rate),
        'chart_clicks_json': json.dumps(clicks),
        'chart_reactions_json': json.dumps(reactions),
        'chart_comments_json': json.dumps(comments),
        'chart_shares_json': json.dumps(shares),
    })


@login_required
def timeline(request):
    df, dt = _defaults()
    d_from = request.GET.get('from', df)
    d_to = request.GET.get('to', dt)
    group_by = request.GET.get('group_by', 'month')

    posts = []
    with connection.cursor() as c:
        rows = _safe(c, """
            SELECT lp.post_id, COALESCE(lp.post_title, lp.post_id),
                   COALESCE(pp.post_date, lp.post_date),
                   lp.post_url, lp.content_type,
                   COALESCE(m.impressions,0), COALESCE(m.likes,0),
                   COALESCE(m.comments,0), COALESCE(m.direct_shares,0),
                   COALESCE(m.clicks,0)
            FROM linkedin_posts lp
            LEFT JOIN linkedin_posts_posted pp ON lp.post_id = pp.post_id
            LEFT JOIN linkedin_posts_metrics m ON lp.post_id = m.post_id
                AND m.metric_date = (
                    SELECT MAX(m2.metric_date) FROM linkedin_posts_metrics m2
                    WHERE m2.post_id = m.post_id)
            ORDER BY COALESCE(pp.post_date, lp.post_date) DESC
        """)
        if rows:
            for r in rows:
                posts.append({
                    'post_id': r[0], 'title': r[1], 'post_date': r[2],
                    'link': r[3] or '', 'content_type': r[4] or '',
                    'impressions': r[5], 'likes': r[6], 'comments': r[7],
                    'shares': r[8], 'clicks': r[9],
                })

    labels, imps, clicks, reactions, comments, shares, eng_rate = _chart_series(d_from, d_to, group_by)

    return render(request, 'linkedin_statistics/stat_timeline.html', {
        'posts': posts,
        'date_from': d_from, 'date_to': d_to,
        'tab': 'timeline', 'group_by': group_by,
        'agg_text': _agg_text(group_by),
        'chart_labels_json': json.dumps(labels),
        'chart_impressions_json': json.dumps(imps),
        'chart_engagement_json': json.dumps(eng_rate),
        'chart_clicks_json': json.dumps(clicks),
        'chart_reactions_json': json.dumps(reactions),
        'chart_comments_json': json.dumps(comments),
        'chart_shares_json': json.dumps(shares),
    })


@login_required
def timeline_detail(request, post_id):
    """Detail-Chart fuer einen einzelnen Post (Tagesverlauf)."""
    data = []
    with connection.cursor() as c:
        rows = _safe(c, """
            SELECT metric_date, impressions, clicks, likes, comments, direct_shares
            FROM linkedin_posts_metrics
            WHERE post_id = %s
            ORDER BY metric_date
        """, [post_id])
        if rows:
            for r in rows:
                data.append({
                    'date': r[0].isoformat() if r[0] else '',
                    'impressions': int(r[1] or 0),
                    'clicks': int(r[2] or 0),
                    'likes': int(r[3] or 0),
                    'comments': int(r[4] or 0),
                    'shares': int(r[5] or 0),
                })
    return JsonResponse({'series': data})
PYEOF

# ═══════════════════════════════════════════════
#  stat_overview.html
# ═══════════════════════════════════════════════
cat > linkedin_statistics/templates/linkedin_statistics/stat_overview.html << 'HTEOF'
{% extends "base.html" %}
{% block title %}Statistics – Overview{% endblock %}
{% block content %}
<style>
.sh{display:flex;justify-content:space-between;align-items:center;margin-bottom:1.5rem;flex-wrap:wrap;gap:1rem}
.sh h1{margin:0;font-size:1.5rem}
.df{display:flex;gap:.5rem;align-items:center;flex-wrap:wrap}
.df input[type=date],.df select{padding:.35rem .5rem;border:1px solid #ced4da;border-radius:.25rem;font-size:.85rem}
.df button{padding:.35rem .75rem;background:#0077B5;color:#fff;border:none;border-radius:.25rem;cursor:pointer;font-size:.85rem}
.tabs{display:flex;gap:0;margin-bottom:1.5rem;border-bottom:2px solid #dee2e6}
.tabs a{padding:.6rem 1.2rem;text-decoration:none;color:#6c757d;font-weight:500;border-bottom:2px solid transparent;margin-bottom:-2px}
.tabs a.on{color:#0077B5;border-bottom-color:#0077B5}
.kg{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:1rem;margin-bottom:2rem}
.kc{background:#fff;border-radius:.5rem;padding:1.25rem;box-shadow:0 1px 3px rgba(0,0,0,.1);text-align:center}
.ki{font-size:1.8rem;margin-bottom:.25rem}
.kl{font-size:.8rem;color:#6c757d;text-transform:uppercase;letter-spacing:.5px}
.kv{font-size:1.6rem;font-weight:700;color:#212529}
.ks{font-size:.75rem;color:#6c757d;margin-top:.25rem}
.cc{background:#fff;border-radius:.5rem;padding:1.5rem;box-shadow:0 1px 3px rgba(0,0,0,.1);margin-bottom:2rem}
.cc h2{font-size:1.1rem;margin-bottom:1rem}
.pt{width:100%;border-collapse:collapse;font-size:.85rem}
.pt th{text-align:left;padding:.5rem;border-bottom:2px solid #dee2e6;font-weight:600;color:#495057}
.pt td{padding:.5rem;border-bottom:1px solid #f0f0f0}
.agg-note{color:#6c757d;font-size:.8rem;margin-top:.5rem}
</style>

<!-- 1. KPI-Kacheln: IMMER aktueller Stand -->
<div class="kg">
  <div class="kc"><div class="ki">👥</div><div class="kl">Followers</div>
    <div class="kv">{{ kpi.total_followers }}</div>
    <div class="ks">Stand: {{ kpi.followers_date|date:"d.m.Y"|default:"—" }}</div></div>
  <div class="kc"><div class="ki">📝</div><div class="kl">Posts</div>
    <div class="kv">{{ kpi.total_posts }}</div>
    <div class="ks">letzter Post: {{ kpi.posts_date|date:"d.m.Y"|default:"—" }}</div></div>
  <div class="kc"><div class="ki">👁️</div><div class="kl">Impressions</div>
    <div class="kv">{{ kpi.total_impressions }}</div>
    <div class="ks">Stand: {{ kpi.metrics_date|date:"d.m.Y"|default:"—" }}</div></div>
  <div class="kc"><div class="ki">❤️</div><div class="kl">Engagement</div>
    <div class="kv">{{ kpi.total_engagement }}</div>
    <div class="ks">Likes+Comments+Shares · Stand: {{ kpi.metrics_date|date:"d.m.Y"|default:"—" }}</div></div>
</div>

<!-- 2. Von/Bis (nur fuer Charts) -->
<div class="sh">
  <h1>📊 Content Metriken über Zeit</h1>
  <form method="get" class="df">
    <label>Von</label><input type="date" name="from" value="{{ date_from }}">
    <label>Bis</label><input type="date" name="to" value="{{ date_to }}">
    <label>Aggregation</label>
    <select name="group_by">
      <option value="day" {% if group_by == 'day' %}selected{% endif %}>Tag</option>
      <option value="week" {% if group_by == 'week' %}selected{% endif %}>Woche</option>
      <option value="month" {% if group_by == 'month' %}selected{% endif %}>Monat</option>
    </select>
    <button type="submit">Anwenden</button>
  </form>
</div>

<div class="tabs">
  <a href="{% url 'linkedin_statistics:overview' %}" class="{% if tab == 'overview' %}on{% endif %}">Overview</a>
  <a href="{% url 'linkedin_statistics:timeline' %}" class="{% if tab == 'timeline' %}on{% endif %}">Timeline</a>
</div>

<!-- 3. Content Metrics: Impressions (Bar) + Engagement Rate (Line) -->
<div class="cc">
  <h2>📈 Content Metriken über Zeit</h2>
  <canvas id="contentMetrics" height="100"></canvas>
  <p class="agg-note">Impressions als Balken; Engagement Rate (%) als rote Linie. Daten aus <em>linkedin_content_metrics</em>, {{ agg_text }} summiert.</p>
</div>

<!-- 4. Interaktionen (absolut) -->
<div class="cc">
  <h2>📊 Interaktionen (absolut)</h2>
  <canvas id="interaktionen" height="120"></canvas>
  <p class="agg-note">Clicks, Reactions, Comments, Shares – {{ agg_text }} summiert.</p>
</div>

<!-- 5. Top 5 nach Impressions -->
<div class="cc" style="padding:0">
  <h2 style="padding:1rem 1.5rem .5rem">🏆 Top 5 Posts – nach Impressions</h2>
  {% if top_posts_impressions %}
  <table class="pt">
    <thead><tr><th>#</th><th>Post</th><th>Datum</th><th>Impressions</th><th>Clicks</th><th>Likes</th><th>Comments</th><th>Shares</th></tr></thead>
    <tbody>
    {% for p in top_posts_impressions %}
    <tr>
      <td>{{ forloop.counter }}</td>
      <td>{% if p.link %}<a href="{{ p.link }}" target="_blank">{{ p.title|truncatechars:50 }}</a>{% else %}{{ p.title|truncatechars:50 }}{% endif %}</td>
      <td>{{ p.post_date|date:"d.m.Y"|default:"—" }}</td>
      <td>{{ p.impressions }}</td><td>{{ p.clicks }}</td><td>{{ p.likes }}</td><td>{{ p.comments }}</td><td>{{ p.shares }}</td>
    </tr>
    {% endfor %}
    </tbody>
  </table>
  {% else %}<p style="padding:1.5rem;text-align:center;color:#6c757d">Keine Daten vorhanden.</p>{% endif %}
</div>

<!-- 6. Top 5 nach Engagement -->
<div class="cc" style="padding:0">
  <h2 style="padding:1rem 1.5rem .5rem">🔥 Top 5 Posts – nach Engagement</h2>
  {% if top_posts_engagement %}
  <table class="pt">
    <thead><tr><th>#</th><th>Post</th><th>Datum</th><th>Engagement</th><th>Likes</th><th>Comments</th><th>Shares</th><th>Impressions</th></tr></thead>
    <tbody>
    {% for p in top_posts_engagement %}
    <tr>
      <td>{{ forloop.counter }}</td>
      <td>{% if p.link %}<a href="{{ p.link }}" target="_blank">{{ p.title|truncatechars:50 }}</a>{% else %}{{ p.title|truncatechars:50 }}{% endif %}</td>
      <td>{{ p.post_date|date:"d.m.Y"|default:"—" }}</td>
      <td><strong>{{ p.engagement }}</strong></td><td>{{ p.likes }}</td><td>{{ p.comments }}</td><td>{{ p.shares }}</td><td>{{ p.impressions }}</td>
    </tr>
    {% endfor %}
    </tbody>
  </table>
  {% else %}<p style="padding:1.5rem;text-align:center;color:#6c757d">Keine Daten vorhanden.</p>{% endif %}
</div>

<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<script>
const labels = {{ chart_labels_json|safe }};
const impressionsData = {{ chart_impressions_json|safe }};
const engagementData = {{ chart_engagement_json|safe }};
const clicksData = {{ chart_clicks_json|safe }};
const reactionsData = {{ chart_reactions_json|safe }};
const commentsData = {{ chart_comments_json|safe }};
const sharesData = {{ chart_shares_json|safe }};

/* Content Metrics: Impressions (Bar, blau) + Engagement Rate (Line, rot) */
if (labels && labels.length) {
  const ctx1 = document.getElementById('contentMetrics').getContext('2d');
  new Chart(ctx1, {
    data: {
      labels: labels,
      datasets: [
        {
          type: 'bar',
          label: 'Impressions',
          data: impressionsData,
          backgroundColor: 'rgba(0,119,181,0.5)',
          borderColor: 'rgba(0,119,181,1)',
          borderWidth: 1,
          yAxisID: 'y',
          order: 2
        },
        {
          type: 'line',
          label: 'Engagement Rate (%)',
          data: engagementData,
          borderColor: 'rgba(220,53,69,1)',
          backgroundColor: 'rgba(220,53,69,0.1)',
          borderWidth: 2,
          pointRadius: 4,
          pointBackgroundColor: 'rgba(220,53,69,1)',
          tension: 0.3,
          fill: false,
          yAxisID: 'y1',
          order: 1,
          datalabels: { display: true }
        }
      ]
    },
    options: {
      responsive: true,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { position: 'bottom' },
        tooltip: {
          callbacks: {
            label: function(ctx) {
              if (ctx.dataset.yAxisID === 'y1') return ctx.dataset.label + ': ' + ctx.parsed.y + '%';
              return ctx.dataset.label + ': ' + ctx.parsed.y;
            }
          }
        }
      },
      scales: {
        x: { ticks: { maxRotation: 45, minRotation: 0 } },
        y:  { title: { display: true, text: 'Impressions' }, beginAtZero: true, position: 'left' },
        y1: { title: { display: true, text: 'Engagement Rate %', color: 'rgba(220,53,69,1)' },
              beginAtZero: true, max: 50, position: 'right',
              grid: { drawOnChartArea: false },
              ticks: { callback: function(v) { return v + '%'; } } }
      }
    }
  });
} else {
  document.getElementById('contentMetrics').parentElement.innerHTML +=
    '<p style="text-align:center;color:#6c757d">Keine Daten im gewählten Zeitraum.</p>';
}

/* Interaktionen (absolut): Grouped Bar */
if (labels && labels.length) {
  new Chart(document.getElementById('interaktionen').getContext('2d'), {
    type: 'bar',
    data: {
      labels: labels,
      datasets: [
        { label: 'Clicks',    data: clicksData,    backgroundColor: 'rgba(54,162,235,0.7)',  borderWidth: 0 },
        { label: 'Reactions',  data: reactionsData, backgroundColor: 'rgba(255,99,132,0.7)',  borderWidth: 0 },
        { label: 'Comments',   data: commentsData,  backgroundColor: 'rgba(75,192,192,0.7)',  borderWidth: 0 },
        { label: 'Shares',     data: sharesData,    backgroundColor: 'rgba(255,205,86,0.7)',  borderWidth: 0 }
      ]
    },
    options: {
      responsive: true,
      interaction: { mode: 'index', intersect: false },
      plugins: { legend: { position: 'top' } },
      scales: {
        x: { ticks: { maxRotation: 45, minRotation: 0 } },
        y: { title: { display: true, text: 'Anzahl' }, beginAtZero: true }
      }
    }
  });
} else {
  document.getElementById('interaktionen').parentElement.innerHTML +=
    '<p style="text-align:center;color:#6c757d">Keine Daten im gewählten Zeitraum.</p>';
}
</script>
{% endblock %}
HTEOF

echo "=== Git commit + push ==="
git add linkedin_statistics/stat_views.py
git add linkedin_statistics/templates/linkedin_statistics/stat_overview.html
git commit -m "fix: charts from linkedin_content_metrics + KPI snapshot + top5"
git push

echo ""
echo "FERTIG! Render deployt automatisch."
