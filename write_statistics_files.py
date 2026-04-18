#!/usr/bin/env python3
import os

BASE = "linkedin_statistics"

def write(path, content):
    full = os.path.join(BASE, path) if not path.startswith(BASE) else path
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, 'w') as f:
        f.write(content)
    print(f"  OK  {full}")

# ═══════════════════════════════════════════════════════════════
# 1. stat_utils.py
# ═══════════════════════════════════════════════════════════════
write("stat_utils.py", """from datetime import datetime, timedelta

def get_date_range(request):
    date_to = datetime.today().date()
    date_from = date_to - timedelta(days=365)
    from_param = request.GET.get('date_from') or request.GET.get('from')
    to_param = request.GET.get('date_to') or request.GET.get('to')
    if from_param:
        try: date_from = datetime.strptime(from_param, '%Y-%m-%d').date()
        except ValueError: pass
    if to_param:
        try: date_to = datetime.strptime(to_param, '%Y-%m-%d').date()
        except ValueError: pass
    return date_from, date_to
""")

# ═══════════════════════════════════════════════════════════════
# 2. reports/stat_overview.py
# ═══════════════════════════════════════════════════════════════
write("reports/__init__.py", "")
write("reports/stat_overview.py", '''from django.db import connection

def get_overview_data(date_from=None, date_to=None):
    data = {}
    with connection.cursor() as cur:
        # Followers - letzter bekannter Stand
        try:
            cur.execute("SELECT followers_total FROM linkedin_followers ORDER BY date DESC LIMIT 1")
            row = cur.fetchone()
            data['total_followers'] = row[0] if row else 0
        except:
            data['total_followers'] = 0

        # Follower growth
        try:
            cur.execute("SELECT followers_total FROM linkedin_followers WHERE date >= %s ORDER BY date ASC LIMIT 1", [date_from])
            first = cur.fetchone()
            cur.execute("SELECT followers_total FROM linkedin_followers WHERE date <= %s ORDER BY date DESC LIMIT 1", [date_to])
            last = cur.fetchone()
            if first and last and first[0] and first[0] > 0:
                data['follower_growth'] = round(((last[0] - first[0]) / first[0]) * 100, 1)
            else:
                data['follower_growth'] = 0
        except:
            data['follower_growth'] = 0

        # Total posts
        try:
            cur.execute("SELECT COUNT(*) FROM linkedin_posts")
            row = cur.fetchone()
            data['total_posts'] = row[0] if row else 0
        except:
            data['total_posts'] = 0

        # Impressions - LETZTER STAND pro Post, dann summieren (NICHT alle Snapshots addieren!)
        try:
            cur.execute("""
                SELECT COALESCE(SUM(m.impressions), 0)
                FROM linkedin_posts_metrics m
                INNER JOIN (
                    SELECT post_id, MAX(metric_date) AS max_date
                    FROM linkedin_posts_metrics
                    WHERE metric_date BETWEEN %s AND %s
                    GROUP BY post_id
                ) latest ON m.post_id = latest.post_id AND m.metric_date = latest.max_date
            """, [date_from, date_to])
            row = cur.fetchone()
            data['total_impressions'] = row[0] if row else 0
        except:
            data['total_impressions'] = 0

        # Engagement - LETZTER STAND pro Post, dann summieren
        try:
            cur.execute("""
                SELECT COALESCE(SUM(m.likes + m.comments + m.direct_shares), 0)
                FROM linkedin_posts_metrics m
                INNER JOIN (
                    SELECT post_id, MAX(metric_date) AS max_date
                    FROM linkedin_posts_metrics
                    WHERE metric_date BETWEEN %s AND %s
                    GROUP BY post_id
                ) latest ON m.post_id = latest.post_id AND m.metric_date = latest.max_date
            """, [date_from, date_to])
            row = cur.fetchone()
            data['total_engagement'] = row[0] if row else 0
        except:
            data['total_engagement'] = 0

        # Top 5 posts - letzter Stand pro Post
        try:
            cur.execute("""
                SELECT lp.post_id,
                       COALESCE(lp.post_title, lp.post_id) AS post_title,
                       lp.post_date,
                       lp.post_url,
                       COALESCE(m.impressions, 0) AS impressions,
                       COALESCE(m.likes, 0) AS likes,
                       COALESCE(m.comments, 0) AS comments,
                       COALESCE(m.direct_shares, 0) AS shares
                FROM linkedin_posts lp
                INNER JOIN linkedin_posts_metrics m ON lp.post_id = m.post_id
                INNER JOIN (
                    SELECT post_id, MAX(metric_date) AS max_date
                    FROM linkedin_posts_metrics
                    GROUP BY post_id
                ) latest ON m.post_id = latest.post_id AND m.metric_date = latest.max_date
                ORDER BY impressions DESC
                LIMIT 5
            """)
            rows = cur.fetchall()
            data['top_posts'] = [{
                'post_id': r[0], 'post_title': r[1], 'post_date': r[2],
                'post_link': r[3] or '', 'impressions': r[4],
                'likes': r[5], 'comments': r[6], 'shares': r[7],
            } for r in rows]
        except:
            data['top_posts'] = []

        # Content Metrics Chart - Impressions + Engagement Rate pro Monat
        # Pro Monat: Tageswerte summieren fuer Impressions, AVG fuer Engagement Rate
        try:
            cur.execute("""
                SELECT DATE_FORMAT(metric_date, '%%Y-%%m') AS month,
                       COALESCE(SUM(impressions), 0) AS impressions,
                       COALESCE(AVG(engagement_rate) * 100, 0) AS eng_rate
                FROM linkedin_posts_metrics
                WHERE metric_date IS NOT NULL
                GROUP BY month
                ORDER BY month ASC
            """)
            rows = cur.fetchall()
            data['content_chart_labels'] = [r[0] for r in rows]
            data['content_chart_impressions'] = [int(r[1]) for r in rows]
            data['content_chart_engagement'] = [round(float(r[2]), 2) for r in rows]
        except:
            data['content_chart_labels'] = []
            data['content_chart_impressions'] = []
            data['content_chart_engagement'] = []

    return data
''')

# ═══════════════════════════════════════════════════════════════
# 3. reports/stat_timeline.py
# ═══════════════════════════════════════════════════════════════
write("reports/stat_timeline.py", '''from django.db import connection

def get_all_posts(date_from=None, date_to=None):
    posts = []
    with connection.cursor() as cur:
        try:
            cur.execute("""
                SELECT lp.post_id,
                       COALESCE(lp.post_title, lp.post_id) AS post_title,
                       COALESCE(pp.post_date, lp.post_date) AS post_date,
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
                ) latest ON m.post_id = latest.post_id AND m.metric_date = latest.max_date
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
        except:
            posts = []
    return posts
''')

# ═══════════════════════════════════════════════════════════════
# 4. stat_overview.html
# ═══════════════════════════════════════════════════════════════
write("templates/linkedin_statistics/stat_overview.html", r'''{% extends "linkedin_statistics/stat_base.html" %}

{% block stat_content %}

<!-- KPI Cards -->
<div class="kpi-grid">
  <div class="kpi-card">
    <div class="kpi-icon">👥</div>
    <div class="kpi-label">Total Followers</div>
    <div class="kpi-value">{{ data.total_followers }}</div>
    <div class="kpi-sub {% if data.follower_growth > 0 %}positive{% elif data.follower_growth < 0 %}negative{% endif %}">
      {% if data.follower_growth > 0 %}▲{% elif data.follower_growth < 0 %}▼{% endif %}
      {{ data.follower_growth }}% in selected period
    </div>
  </div>
  <div class="kpi-card">
    <div class="kpi-icon">📝</div>
    <div class="kpi-label">Posts Published</div>
    <div class="kpi-value">{{ data.total_posts }}</div>
    <div class="kpi-sub">Total in database</div>
  </div>
  <div class="kpi-card">
    <div class="kpi-icon">👁️</div>
    <div class="kpi-label">Total Impressions</div>
    <div class="kpi-value">{{ data.total_impressions }}</div>
    <div class="kpi-sub">Selected period (latest per post)</div>
  </div>
  <div class="kpi-card">
    <div class="kpi-icon">❤️</div>
    <div class="kpi-label">Total Engagement</div>
    <div class="kpi-value">{{ data.total_engagement }}</div>
    <div class="kpi-sub">Likes + Comments + Shares</div>
  </div>
</div>

<!-- Content Metrics Chart: Impressions (blau, links) + Engagement Rate (rot, rechts) -->
{% if data.content_chart_labels %}
<div class="stat-section">
  <h2>📈 Content Metriken über Zeit</h2>
  <div class="chart-container">
    <canvas id="contentChart" height="80"></canvas>
  </div>
</div>
{% endif %}

<!-- Top Posts Table -->
<div class="stat-section">
  <h2>🏆 Top Posts by Impressions</h2>
  {% if data.top_posts %}
  <div class="chart-container">
    <table class="posts-table">
      <thead>
        <tr><th>Post</th><th>Date</th><th>Impressions</th><th>Likes</th><th>Comments</th><th>Shares</th><th>Link</th></tr>
      </thead>
      <tbody>
        {% for post in data.top_posts %}
        <tr>
          <td><small>{{ post.post_title|truncatechars:60 }}</small></td>
          <td>{{ post.post_date|date:"d.m.Y"|default:"—" }}</td>
          <td><span class="badge badge-impressions">{{ post.impressions }}</span></td>
          <td>{{ post.likes }}</td>
          <td>{{ post.comments }}</td>
          <td>{{ post.shares }}</td>
          <td>{% if post.post_link %}<a href="{{ post.post_link }}" target="_blank">🔗</a>{% else %}—{% endif %}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
  {% else %}
  <div class="chart-container" style="text-align:center; color:#6c757d; padding: 2rem;">
    No post data found.
  </div>
  {% endif %}
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
        pointStyle: 'circle',
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
            if (ctx.dataset.yAxisID === 'y1') return ctx.dataset.label + ': ' + ctx.parsed.y.toFixed(2) + '%';
            return ctx.dataset.label + ': ' + ctx.parsed.y.toLocaleString('de-DE');
          }
        }
      }
    },
    scales: {
      y:  { type: 'linear', position: 'left',  title: { display: true, text: 'Impressions' }, grid: { color: '#f0f0f0' }, beginAtZero: true },
      y1: { type: 'linear', position: 'right', title: { display: true, text: 'Engagement Rate %' }, grid: { drawOnChartArea: false }, beginAtZero: true, max: 50 }
    }
  }
});
{% endif %}
</script>
{% endblock %}
''')

# ═══════════════════════════════════════════════════════════════
# 5. stat_timeline.html
# ═══════════════════════════════════════════════════════════════
write("templates/linkedin_statistics/stat_timeline.html", r'''{% extends "linkedin_statistics/stat_base.html" %}

{% block stat_content %}
<div class="stat-section">
  <h2>📊 Post Timeline – All Posts</h2>

  {% if posts %}
  <div class="chart-container">
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
  </div>
  {% else %}
  <div class="chart-container" style="text-align:center; color:#6c757d; padding: 2rem;">
    No post data found. Please import LinkedIn CSV data first.
  </div>
  {% endif %}
</div>
{% endblock %}
''')

print("\n✅ Alle 5 Dateien geschrieben!")
print("Jetzt ausfuehren:")
print("  git add -A && git commit -m 'fix: statistics korrekte Spalten + letzter Stand' && git push")
