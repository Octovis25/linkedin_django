#!/usr/bin/env python3
"""
write_statistics_files.py
Erzeugt die korrigierten Dateien fuer das Statistik-Modul.

WICHTIG:
  - View-Datei heisst: stat_views.py  (NICHT views.py!)
  - urls.py importiert: from . import stat_views
  - DB: MySQL (DATE_FORMAT, DATE_SUB etc.)
  - Verzeichnis: linkedin_statistics/
"""
import os

BASE = "linkedin_statistics"

def write(path, content):
    full = os.path.join(BASE, path) if not path.startswith(BASE) else path
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, 'w') as f:
        f.write(content)
    print(f"  OK  {full}")

# ═══════════════════════════════════════════════════════════════
# 1. stat_views.py
# ═══════════════════════════════════════════════════════════════
write("stat_views.py", r'''"""
linkedin_statistics/stat_views.py
MySQL-basierte Views fuer das Statistik-Modul.
Alle KPIs: letzter Snapshot pro Post (MAX metric_date), dann aggregieren.
"""
from datetime import date, timedelta
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.db import connection
import json


def _default_from():
    return (date.today() - timedelta(days=365)).isoformat()

def _default_to():
    return date.today().isoformat()


def _get_overview_data(d_from, d_to):
    data = {
        'total_followers': 0,
        'followers_change': '—',
        'total_posts': 0,
        'total_impressions': 0,
        'total_engagement': 0,
        'top_posts': [],
        'content_chart_labels': [],
        'content_chart_impressions': [],
        'content_chart_engagement': [],
    }

    with connection.cursor() as cur:

        # ── Follower (aktuell + Aenderung im Zeitraum) ────────────
        try:
            cur.execute("""
                SELECT followers_total
                FROM linkedin_followers
                ORDER BY date DESC LIMIT 1
            """)
            row = cur.fetchone()
            if row:
                data['total_followers'] = row[0]

            cur.execute("""
                SELECT
                    MAX(CASE WHEN date <= %s THEN followers_total END) AS f_end,
                    MAX(CASE WHEN date <= %s THEN followers_total END) AS f_start
                FROM linkedin_followers
                WHERE date BETWEEN DATE_SUB(%s, INTERVAL 7 DAY) AND %s
            """, [d_to, d_from, d_from, d_to])
            row = cur.fetchone()
            if row and row[0] and row[1]:
                delta = row[0] - row[1]
                data['followers_change'] = f"+{delta}" if delta >= 0 else str(delta)
        except Exception:
            pass

        # ── Posts im Zeitraum ─────────────────────────────────────
        try:
            cur.execute("""
                SELECT COUNT(*) FROM linkedin_posts lp
                LEFT JOIN linkedin_posts_posted pp ON lp.post_id = pp.post_id
                WHERE COALESCE(pp.post_date, lp.post_date) BETWEEN %s AND %s
            """, [d_from, d_to])
            row = cur.fetchone()
            data['total_posts'] = row[0] if row else 0
        except Exception:
            try:
                cur.execute("SELECT COUNT(*) FROM linkedin_posts")
                row = cur.fetchone()
                data['total_posts'] = row[0] if row else 0
            except Exception:
                pass

        # ── Impressions: LETZTER STAND pro Post, dann SUM ─────────
        try:
            cur.execute("""
                SELECT COALESCE(SUM(m.impressions), 0)
                FROM linkedin_posts_metrics m
                INNER JOIN (
                    SELECT post_id, MAX(metric_date) AS max_date
                    FROM linkedin_posts_metrics
                    GROUP BY post_id
                ) latest ON m.post_id = latest.post_id
                       AND m.metric_date = latest.max_date
            """)
            row = cur.fetchone()
            data['total_impressions'] = row[0] if row else 0
        except Exception:
            pass

        # ── Engagement: LETZTER STAND pro Post, dann SUM ──────────
        try:
            cur.execute("""
                SELECT COALESCE(SUM(m.likes + m.comments + m.direct_shares), 0)
                FROM linkedin_posts_metrics m
                INNER JOIN (
                    SELECT post_id, MAX(metric_date) AS max_date
                    FROM linkedin_posts_metrics
                    GROUP BY post_id
                ) latest ON m.post_id = latest.post_id
                       AND m.metric_date = latest.max_date
            """)
            row = cur.fetchone()
            data['total_engagement'] = row[0] if row else 0
        except Exception:
            pass

        # ── Top 5 Posts (letzter Stand pro Post) ──────────────────
        try:
            cur.execute("""
                SELECT lp.post_id,
                       COALESCE(lp.post_title, lp.post_id) AS title,
                       COALESCE(pp.post_date, lp.post_date) AS pdate,
                       lp.post_url,
                       COALESCE(m.impressions, 0) AS impressions,
                       COALESCE(m.likes, 0) AS likes,
                       COALESCE(m.comments, 0) AS comments,
                       COALESCE(m.direct_shares, 0) AS shares
                FROM linkedin_posts lp
                LEFT JOIN linkedin_posts_posted pp ON lp.post_id = pp.post_id
                INNER JOIN linkedin_posts_metrics m ON lp.post_id = m.post_id
                INNER JOIN (
                    SELECT post_id, MAX(metric_date) AS max_date
                    FROM linkedin_posts_metrics
                    GROUP BY post_id
                ) latest ON m.post_id = latest.post_id
                       AND m.metric_date = latest.max_date
                ORDER BY impressions DESC
                LIMIT 5
            """)
            rows = cur.fetchall()
            data['top_posts'] = [{
                'post_id': r[0], 'post_title': r[1], 'post_date': r[2],
                'post_link': r[3] or '', 'impressions': r[4],
                'likes': r[5], 'comments': r[6], 'shares': r[7],
            } for r in rows]
        except Exception:
            data['top_posts'] = []

        # ── Content Chart: pro Monat letzter Stand pro Post ───────
        try:
            cur.execute("""
                SELECT
                    DATE_FORMAT(m.metric_date, '%%Y-%%m') AS monat,
                    COALESCE(SUM(m.impressions), 0) AS imp,
                    COALESCE(AVG(m.engagement_rate) * 100, 0) AS eng
                FROM linkedin_posts_metrics m
                INNER JOIN (
                    SELECT post_id,
                           DATE_FORMAT(metric_date, '%%Y-%%m') AS md_month,
                           MAX(metric_date) AS max_date
                    FROM linkedin_posts_metrics
                    WHERE metric_date IS NOT NULL
                    GROUP BY post_id, DATE_FORMAT(metric_date, '%%Y-%%m')
                ) latest ON m.post_id = latest.post_id
                       AND m.metric_date = latest.max_date
                GROUP BY monat
                ORDER BY monat ASC
            """)
            rows = cur.fetchall()
            data['content_chart_labels'] = [r[0] for r in rows]
            data['content_chart_impressions'] = [int(r[1]) for r in rows]
            data['content_chart_engagement'] = [round(float(r[2]), 2) for r in rows]
        except Exception:
            pass

    return data


@login_required
def overview(request):
    d_from = request.GET.get('from', _default_from())
    d_to = request.GET.get('to', _default_to())
    data = _get_overview_data(d_from, d_to)
    return render(request, 'linkedin_statistics/overview.html', {
        'data': data,
        'date_from': d_from,
        'date_to': d_to,
        'active_tab': 'overview',
    })


def _get_timeline_data(d_from, d_to):
    posts = []
    with connection.cursor() as cur:
        try:
            cur.execute("""
                SELECT lp.post_id,
                       COALESCE(lp.post_title, lp.post_id) AS title,
                       COALESCE(pp.post_date, lp.post_date) AS pdate,
                       lp.post_url,
                       lp.content_type,
                       COALESCE(m.impressions, 0) AS impressions,
                       COALESCE(m.likes, 0) AS likes,
                       COALESCE(m.comments, 0) AS comments,
                       COALESCE(m.direct_shares, 0) AS shares,
                       COALESCE(m.clicks, 0) AS clicks
                FROM linkedin_posts lp
                LEFT JOIN linkedin_posts_posted pp ON lp.post_id = pp.post_id
                LEFT JOIN linkedin_posts_metrics m ON lp.post_id = m.post_id
                LEFT JOIN (
                    SELECT post_id, MAX(metric_date) AS max_date
                    FROM linkedin_posts_metrics
                    GROUP BY post_id
                ) latest ON m.post_id = latest.post_id
                       AND m.metric_date = latest.max_date
                WHERE latest.max_date IS NOT NULL OR m.id IS NULL
                ORDER BY COALESCE(pp.post_date, lp.post_date) DESC
            """)
            rows = cur.fetchall()
            posts = [{
                'post_id': r[0], 'post_title': r[1], 'post_date': r[2],
                'post_link': r[3] or '', 'content_type': r[4] or '',
                'impressions': r[5], 'likes': r[6], 'comments': r[7],
                'shares': r[8], 'clicks': r[9],
                'engagement': r[6] + r[7] + r[8],
            } for r in rows]
        except Exception:
            posts = []
    return posts


@login_required
def timeline(request):
    d_from = request.GET.get('from', _default_from())
    d_to = request.GET.get('to', _default_to())
    posts = _get_timeline_data(d_from, d_to)
    return render(request, 'linkedin_statistics/timeline.html', {
        'posts': posts,
        'date_from': d_from,
        'date_to': d_to,
        'active_tab': 'timeline',
    })


@login_required
def timeline_detail(request, post_id):
    return render(request, 'linkedin_statistics/timeline.html', {
        'posts': [],
        'active_tab': 'timeline',
    })
''')

# ═══════════════════════════════════════════════════════════════
# 2. urls.py  –  importiert stat_views (NICHT views!)
# ═══════════════════════════════════════════════════════════════
write("urls.py", '''from django.urls import path
from . import stat_views

app_name = 'linkedin_statistics'

urlpatterns = [
    path('',                        stat_views.overview,         name='overview'),
    path('timeline/',               stat_views.timeline,         name='timeline'),
    path('timeline/<str:post_id>/', stat_views.timeline_detail,  name='timeline_detail'),
]
''')

# ═══════════════════════════════════════════════════════════════
# 3. overview.html
# ═══════════════════════════════════════════════════════════════
write("templates/linkedin_statistics/overview.html", r'''{% extends "base.html" %}
{% block title %}Statistics – Overview{% endblock %}

{% block content %}
<style>
  .stat-header { display:flex; justify-content:space-between; align-items:center; margin-bottom:1.5rem; flex-wrap:wrap; gap:1rem; }
  .stat-header h1 { margin:0; font-size:1.5rem; }
  .date-filter { display:flex; gap:.5rem; align-items:center; }
  .date-filter input[type=date] { padding:.35rem .5rem; border:1px solid #ced4da; border-radius:.25rem; font-size:.85rem; }
  .date-filter button { padding:.35rem .75rem; background:#0077B5; color:#fff; border:none; border-radius:.25rem; cursor:pointer; font-size:.85rem; }
  .stat-tabs { display:flex; gap:0; margin-bottom:1.5rem; border-bottom:2px solid #dee2e6; }
  .stat-tabs a { padding:.6rem 1.2rem; text-decoration:none; color:#6c757d; font-weight:500; border-bottom:2px solid transparent; margin-bottom:-2px; }
  .stat-tabs a.active { color:#0077B5; border-bottom-color:#0077B5; }
  .kpi-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:1rem; margin-bottom:2rem; }
  .kpi-card { background:#fff; border-radius:.5rem; padding:1.25rem; box-shadow:0 1px 3px rgba(0,0,0,.1); text-align:center; }
  .kpi-icon { font-size:1.8rem; margin-bottom:.25rem; }
  .kpi-label { font-size:.8rem; color:#6c757d; text-transform:uppercase; letter-spacing:.5px; }
  .kpi-value { font-size:1.6rem; font-weight:700; color:#212529; }
  .kpi-sub { font-size:.75rem; color:#6c757d; margin-top:.25rem; }
  .kpi-sub.positive { color:#28a745; }
  .kpi-sub.negative { color:#dc3545; }
  .chart-container { background:#fff; border-radius:.5rem; padding:1.5rem; box-shadow:0 1px 3px rgba(0,0,0,.1); margin-bottom:2rem; }
  .chart-container h2 { font-size:1.1rem; margin-bottom:1rem; }
  .posts-table { width:100%; border-collapse:collapse; font-size:.85rem; }
  .posts-table th { text-align:left; padding:.5rem; border-bottom:2px solid #dee2e6; font-weight:600; color:#495057; }
  .posts-table td { padding:.5rem; border-bottom:1px solid #f0f0f0; }
  .stat-section { margin-bottom:2rem; }
  .stat-section h2 { font-size:1.1rem; margin-bottom:1rem; }
</style>

<div class="stat-header">
  <h1>📊 LinkedIn Statistics</h1>
  <form method="get" class="date-filter">
    <label>From</label>
    <input type="date" name="from" value="{{ date_from }}">
    <label>To</label>
    <input type="date" name="to" value="{{ date_to }}">
    <button type="submit">Apply</button>
  </form>
</div>

<div class="stat-tabs">
  <a href="{% url 'linkedin_statistics:overview' %}" class="{% if active_tab == 'overview' %}active{% endif %}">Overview</a>
  <a href="{% url 'linkedin_statistics:timeline' %}" class="{% if active_tab == 'timeline' %}active{% endif %}">Timeline</a>
</div>

<!-- KPI Cards -->
<div class="kpi-grid">
  <div class="kpi-card">
    <div class="kpi-icon">👥</div>
    <div class="kpi-label">Total Followers</div>
    <div class="kpi-value">{{ data.total_followers }}</div>
    <div class="kpi-sub">{{ data.followers_change }} in period</div>
  </div>
  <div class="kpi-card">
    <div class="kpi-icon">📝</div>
    <div class="kpi-label">Posts</div>
    <div class="kpi-value">{{ data.total_posts }}</div>
    <div class="kpi-sub">in selected period</div>
  </div>
  <div class="kpi-card">
    <div class="kpi-icon">👁️</div>
    <div class="kpi-label">Total Impressions</div>
    <div class="kpi-value">{{ data.total_impressions }}</div>
    <div class="kpi-sub">latest snapshot per post</div>
  </div>
  <div class="kpi-card">
    <div class="kpi-icon">❤️</div>
    <div class="kpi-label">Total Engagement</div>
    <div class="kpi-value">{{ data.total_engagement }}</div>
    <div class="kpi-sub">Likes + Comments + Shares</div>
  </div>
</div>

<!-- Content Metrics Chart -->
<div class="chart-container">
  <h2>📈 Content Metrics over Time</h2>
  <canvas id="contentChart" height="100"></canvas>
</div>

<!-- Top 5 Posts -->
<div class="stat-section">
  <h2>🏆 Top 5 Posts by Impressions</h2>
  <div class="chart-container" style="padding:0;">
    {% if data.top_posts %}
    <table class="posts-table">
      <thead>
        <tr><th>#</th><th>Post</th><th>Date</th><th>Impressions</th><th>Likes</th><th>Comments</th><th>Shares</th></tr>
      </thead>
      <tbody>
        {% for post in data.top_posts %}
        <tr>
          <td>{{ forloop.counter }}</td>
          <td>
            {% if post.post_link %}<a href="{{ post.post_link }}" target="_blank">{{ post.post_title|truncatechars:50 }}</a>
            {% else %}{{ post.post_title|truncatechars:50 }}{% endif %}
          </td>
          <td>{{ post.post_date|date:"d.m.Y"|default:"—" }}</td>
          <td>{{ post.impressions }}</td>
          <td>{{ post.likes }}</td>
          <td>{{ post.comments }}</td>
          <td>{{ post.shares }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    {% else %}
    <p style="padding:1.5rem; text-align:center; color:#6c757d;">No post data available.</p>
    {% endif %}
  </div>
</div>

<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<script>
{% if data.content_chart_labels %}
const ctx = document.getElementById('contentChart').getContext('2d');
new Chart(ctx, {
  type: 'line',
  data: {
    labels: {{ data.content_chart_labels|safe }},
    datasets: [
      {
        label: 'Impressions',
        data: {{ data.content_chart_impressions|safe }},
        borderColor: '#2196F3',
        backgroundColor: 'rgba(33,150,243,0.05)',
        borderWidth: 2,
        tension: 0.3,
        fill: false,
        yAxisID: 'y',
        pointBackgroundColor: '#2196F3',
      },
      {
        label: 'Engagement Rate %',
        data: {{ data.content_chart_engagement|safe }},
        borderColor: '#e53935',
        borderWidth: 2,
        borderDash: [5, 5],
        tension: 0.3,
        fill: false,
        yAxisID: 'y1',
        pointBackgroundColor: '#e53935',
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
          label: function(context) {
            if (context.dataset.yAxisID === 'y1')
              return context.dataset.label + ': ' + context.parsed.y.toFixed(2) + '%';
            return context.dataset.label + ': ' + context.parsed.y.toLocaleString('de-DE');
          }
        }
      }
    },
    scales: {
      y:  { type: 'linear', position: 'left',  title: { display: true, text: 'Impressions' },  grid: { color: '#f0f0f0' }, beginAtZero: true },
      y1: { type: 'linear', position: 'right', title: { display: true, text: 'Engagement Rate %' }, grid: { drawOnChartArea: false }, beginAtZero: true }
    }
  }
});
{% else %}
document.getElementById('contentChart').parentElement.innerHTML += '<p style="text-align:center;color:#6c757d;">No chart data available.</p>';
{% endif %}
</script>
{% endblock %}
''')

# ═══════════════════════════════════════════════════════════════
# 4. timeline.html
# ═══════════════════════════════════════════════════════════════
write("templates/linkedin_statistics/timeline.html", r'''{% extends "base.html" %}
{% block title %}Statistics – Timeline{% endblock %}

{% block content %}
<style>
  .stat-header { display:flex; justify-content:space-between; align-items:center; margin-bottom:1.5rem; flex-wrap:wrap; gap:1rem; }
  .stat-header h1 { margin:0; font-size:1.5rem; }
  .stat-tabs { display:flex; gap:0; margin-bottom:1.5rem; border-bottom:2px solid #dee2e6; }
  .stat-tabs a { padding:.6rem 1.2rem; text-decoration:none; color:#6c757d; font-weight:500; border-bottom:2px solid transparent; margin-bottom:-2px; }
  .stat-tabs a.active { color:#0077B5; border-bottom-color:#0077B5; }
  .chart-container { background:#fff; border-radius:.5rem; padding:1.5rem; box-shadow:0 1px 3px rgba(0,0,0,.1); }
  .posts-table { width:100%; border-collapse:collapse; font-size:.85rem; }
  .posts-table th { text-align:left; padding:.5rem; border-bottom:2px solid #dee2e6; font-weight:600; color:#495057; }
  .posts-table td { padding:.5rem; border-bottom:1px solid #f0f0f0; }
</style>

<div class="stat-header">
  <h1>📊 LinkedIn Statistics</h1>
</div>

<div class="stat-tabs">
  <a href="{% url 'linkedin_statistics:overview' %}" class="{% if active_tab == 'overview' %}active{% endif %}">Overview</a>
  <a href="{% url 'linkedin_statistics:timeline' %}" class="{% if active_tab == 'timeline' %}active{% endif %}">Timeline</a>
</div>

<div class="chart-container">
  <h2>📊 Post Timeline – All Posts</h2>
  {% if posts %}
  <table class="posts-table">
    <thead>
      <tr><th>Post</th><th>Date</th><th>Type</th><th>Impressions</th><th>Engagement</th><th>Link</th></tr>
    </thead>
    <tbody>
      {% for post in posts %}
      <tr>
        <td><small>{{ post.post_title|truncatechars:60 }}</small></td>
        <td>{{ post.post_date|date:"d.m.Y"|default:"—" }}</td>
        <td>{{ post.content_type|default:"—" }}</td>
        <td>{{ post.impressions }}</td>
        <td>{{ post.engagement }}</td>
        <td>{% if post.post_link %}<a href="{{ post.post_link }}" target="_blank">🔗</a>{% else %}—{% endif %}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  {% else %}
  <p style="text-align:center; color:#6c757d; padding:2rem;">No post data found.</p>
  {% endif %}
</div>
{% endblock %}
''')

# ═══════════════════════════════════════════════════════════════
# 5. __init__.py + apps.py
# ═══════════════════════════════════════════════════════════════
write("__init__.py", "")
write("apps.py", '''from django.apps import AppConfig

class LinkedinStatisticsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'linkedin_statistics'
    verbose_name = 'LinkedIn Statistics'
''')

print()
print("=" * 60)
print("FERTIG! Erzeugte Dateien:")
print("  linkedin_statistics/stat_views.py   <-- NICHT views.py!")
print("  linkedin_statistics/urls.py          <-- importiert stat_views")
print("  linkedin_statistics/__init__.py")
print("  linkedin_statistics/apps.py")
print("  linkedin_statistics/templates/linkedin_statistics/overview.html")
print("  linkedin_statistics/templates/linkedin_statistics/timeline.html")
print()
print("Im Codespace ausfuehren:")
print("  python write_statistics_files.py")
print("  git add -A")
print('  git commit -m "fix: stat_views.py statt views.py + MySQL queries"')
print("  git push")
