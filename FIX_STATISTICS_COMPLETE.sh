#!/bin/bash
echo "=========================================="
echo "  STATISTICS MODULE - COMPLETE FIX"
echo "=========================================="

# ─── STEP 1: Fix duplicate in settings.py ─────────────────────────
echo ""
echo "Step 1: Fixing duplicate in settings.py..."
python3 - << 'PYEOF'
with open('dashboard/settings.py', 'r') as f:
    content = f.read()

# Remove old plain "statistics" entry and any duplicates
lines = content.split('\n')
seen = False
new_lines = []
for line in lines:
    stripped = line.strip().strip(',').strip('"').strip("'")
    if stripped == 'statistics':
        continue  # remove plain python stdlib conflict
    if 'linkedin_statistics' in line:
        if seen:
            continue  # skip duplicate
        seen = True
    new_lines.append(line)

with open('dashboard/settings.py', 'w') as f:
    f.write('\n'.join(new_lines))

print("  ✅ settings.py fixed!")
PYEOF

# Verify
COUNT=$(grep -c "linkedin_statistics" dashboard/settings.py)
echo "  linkedin_statistics appears $COUNT time(s) in settings.py"

# ─── STEP 2: Create folder structure ──────────────────────────────
echo ""
echo "Step 2: Creating folder structure..."
mkdir -p linkedin_statistics/reports
mkdir -p linkedin_statistics/templates/linkedin_statistics
echo "  ✅ Folders created!"

# ─── STEP 3: Create all Python files ──────────────────────────────
echo ""
echo "Step 3: Creating Python files..."

# __init__.py
cat > linkedin_statistics/__init__.py << 'EOF'
"""
LinkedIn Statistics Module
Fully encapsulated, uses existing database tables
"""
EOF

# stat_apps.py
cat > linkedin_statistics/stat_apps.py << 'EOF'
from django.apps import AppConfig

class LinkedinStatisticsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'linkedin_statistics'
    verbose_name = 'LinkedIn Statistics'
EOF

# Fix apps.py to point to correct config
cat > linkedin_statistics/apps.py << 'EOF'
from django.apps import AppConfig

class LinkedinStatisticsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'linkedin_statistics'
    verbose_name = 'LinkedIn Statistics'
EOF

# stat_utils.py
cat > linkedin_statistics/stat_utils.py << 'EOF'
"""
Shared utility functions for all statistics reports
Defined once - reused by all report modules
"""
from datetime import datetime, timedelta
from django.utils import timezone


def get_date_range(request):
    """
    Extract date range from GET parameters.
    Default: last 30 days.
    Returns (date_from, date_to) as date strings 'YYYY-MM-DD'
    """
    date_to = datetime.today().date()
    date_from = date_to - timedelta(days=30)

    from_param = request.GET.get('from')
    to_param = request.GET.get('to')

    if from_param:
        try:
            date_from = datetime.strptime(from_param, '%Y-%m-%d').date()
        except ValueError:
            pass

    if to_param:
        try:
            date_to = datetime.strptime(to_param, '%Y-%m-%d').date()
        except ValueError:
            pass

    return date_from, date_to


def format_number(num):
    """Format large numbers: 1500 -> 1.5K, 1500000 -> 1.5M"""
    if num is None:
        return '—'
    num = int(num)
    if num >= 1_000_000:
        return f"{num / 1_000_000:.1f}M"
    elif num >= 1_000:
        return f"{num / 1_000:.1f}K"
    return str(num)
EOF

# reports/__init__.py
cat > linkedin_statistics/reports/__init__.py << 'EOF'
"""
Statistics Reports
Each report = one separate file
"""
EOF

# reports/stat_overview.py - reads real DB tables
cat > linkedin_statistics/reports/stat_overview.py << 'EOF'
"""
Overview Report
Reads directly from existing DB tables via raw SQL
Tables used:
  - linkedin_followers
  - linkedin_visitors
  - linkedin_posts
  - linkedin_posts_posted
"""
from django.db import connection


def get_overview_data(date_from=None, date_to=None):
    """
    Returns dict with KPI card data from existing database tables
    """
    data = {}

    with connection.cursor() as cur:

        # ── Card 1: Latest total followers ──────────────────────────
        try:
            cur.execute("""
                SELECT follower_count
                FROM linkedin_followers
                ORDER BY date DESC
                LIMIT 1
            """)
            row = cur.fetchone()
            data['total_followers'] = row[0] if row else '—'
        except Exception:
            data['total_followers'] = '—'

        # ── Follower growth (first vs last in range) ─────────────────
        try:
            cur.execute("""
                SELECT follower_count FROM linkedin_followers
                WHERE date >= %s ORDER BY date ASC LIMIT 1
            """, [date_from])
            first = cur.fetchone()

            cur.execute("""
                SELECT follower_count FROM linkedin_followers
                WHERE date <= %s ORDER BY date DESC LIMIT 1
            """, [date_to])
            last = cur.fetchone()

            if first and last and first[0] and first[0] > 0:
                growth = round(((last[0] - first[0]) / first[0]) * 100, 1)
                data['follower_growth'] = growth
            else:
                data['follower_growth'] = 0
        except Exception:
            data['follower_growth'] = 0

        # ── Card 2: Total posts ──────────────────────────────────────
        try:
            cur.execute("SELECT COUNT(*) FROM linkedin_posts_posted")
            row = cur.fetchone()
            data['total_posts'] = row[0] if row else 0
        except Exception:
            data['total_posts'] = '—'

        # ── Card 3: Total impressions ────────────────────────────────
        try:
            cur.execute("""
                SELECT SUM(impressions)
                FROM linkedin_posts
                WHERE date >= %s AND date <= %s
            """, [date_from, date_to])
            row = cur.fetchone()
            data['total_impressions'] = row[0] if row and row[0] else 0
        except Exception:
            # Fallback: try without date filter
            try:
                cur.execute("SELECT SUM(impressions) FROM linkedin_posts")
                row = cur.fetchone()
                data['total_impressions'] = row[0] if row and row[0] else '—'
            except Exception:
                data['total_impressions'] = '—'

        # ── Card 4: Total engagement ─────────────────────────────────
        try:
            cur.execute("""
                SELECT SUM(likes + comments + shares)
                FROM linkedin_posts
                WHERE date >= %s AND date <= %s
            """, [date_from, date_to])
            row = cur.fetchone()
            data['total_engagement'] = row[0] if row and row[0] else 0
        except Exception:
            try:
                cur.execute("""
                    SELECT SUM(likes + comments + shares)
                    FROM linkedin_posts
                """)
                row = cur.fetchone()
                data['total_engagement'] = row[0] if row and row[0] else '—'
            except Exception:
                data['total_engagement'] = '—'

        # ── Top 5 posts by impressions ───────────────────────────────
        try:
            cur.execute("""
                SELECT p.post_id, p.impressions, p.likes, p.comments, p.shares,
                       pp.post_link, pp.post_date
                FROM linkedin_posts p
                LEFT JOIN linkedin_posts_posted pp ON p.post_id = pp.post_id
                ORDER BY p.impressions DESC
                LIMIT 5
            """)
            rows = cur.fetchall()
            data['top_posts'] = [
                {
                    'post_id': r[0],
                    'impressions': r[1] or 0,
                    'likes': r[2] or 0,
                    'comments': r[3] or 0,
                    'shares': r[4] or 0,
                    'post_link': r[5] or '',
                    'post_date': r[6],
                }
                for r in rows
            ]
        except Exception:
            data['top_posts'] = []

        # ── Follower chart data (last 12 months) ─────────────────────
        try:
            cur.execute("""
                SELECT DATE_FORMAT(date, '%Y-%m') as month,
                       MAX(follower_count) as count
                FROM linkedin_followers
                WHERE date >= DATE_SUB(NOW(), INTERVAL 12 MONTH)
                GROUP BY month
                ORDER BY month ASC
            """)
            rows = cur.fetchall()
            data['follower_chart_labels'] = [r[0] for r in rows]
            data['follower_chart_values'] = [r[1] for r in rows]
        except Exception:
            data['follower_chart_labels'] = []
            data['follower_chart_values'] = []

    return data
EOF

# reports/stat_timeline.py - per-post timeline data
cat > linkedin_statistics/reports/stat_timeline.py << 'EOF'
"""
Post Timeline Report
Shows per-post performance metrics
Step 2 of statistics module
"""
from django.db import connection


def get_all_posts(date_from=None, date_to=None):
    """
    Returns list of all posts with their metrics
    """
    posts = []
    with connection.cursor() as cur:
        try:
            query = """
                SELECT p.post_id, p.impressions, p.likes, p.comments,
                       p.shares, p.clicks, p.date,
                       pp.post_link, pp.post_date
                FROM linkedin_posts p
                LEFT JOIN linkedin_posts_posted pp ON p.post_id = pp.post_id
                ORDER BY p.impressions DESC
            """
            cur.execute(query)
            rows = cur.fetchall()
            posts = [
                {
                    'post_id': r[0],
                    'impressions': r[1] or 0,
                    'likes': r[2] or 0,
                    'comments': r[3] or 0,
                    'shares': r[4] or 0,
                    'clicks': r[5] or 0,
                    'date': r[6],
                    'post_link': r[7] or '',
                    'post_date': r[8],
                    'engagement': (r[2] or 0) + (r[3] or 0) + (r[4] or 0),
                }
                for r in rows
            ]
        except Exception as e:
            posts = []
    return posts
EOF

echo "  ✅ Python files created!"

# ─── STEP 4: Create HTML templates ────────────────────────────────
echo ""
echo "Step 4: Creating HTML templates..."

# stat_base.html
cat > linkedin_statistics/templates/linkedin_statistics/stat_base.html << 'HTMLEOF'
{% extends "core/base.html" %}

{% block content %}
<div class="stat-wrapper">

  <!-- Sub-navigation tabs -->
  <div class="stat-tabs">
    <a href="/statistics/" class="stat-tab {% if active_tab == 'overview' %}active{% endif %}">
      📊 Overview
    </a>
    <a href="/statistics/timeline/" class="stat-tab {% if active_tab == 'timeline' %}active{% endif %}">
      📈 Post Timeline
    </a>
  </div>

  <!-- Date range filter -->
  <div class="stat-filter-bar">
    <form method="get" class="filter-form">
      <span>Date range:</span>
      <input type="date" name="from" value="{{ date_from }}">
      <span>to</span>
      <input type="date" name="to" value="{{ date_to }}">
      <button type="submit" class="btn btn-primary btn-sm">Apply</button>
      <a href="?from={{ default_from }}&to={{ default_to }}" class="btn btn-secondary btn-sm">Last 30 days</a>
    </form>
  </div>

  <!-- Page content -->
  <div class="stat-content">
    {% block stat_content %}{% endblock %}
  </div>

</div>

<style>
  .stat-wrapper { padding: 0.5rem 0; }

  .stat-tabs {
    display: flex;
    gap: 0;
    border-bottom: 2px solid var(--octo-petrol);
    margin-bottom: 1.5rem;
  }

  .stat-tab {
    padding: 0.6rem 1.5rem;
    text-decoration: none;
    color: var(--octo-petrol);
    font-weight: 500;
    border-bottom: 3px solid transparent;
    margin-bottom: -2px;
    transition: all 0.2s;
  }

  .stat-tab:hover {
    color: var(--octo-orange);
    border-bottom-color: var(--octo-orange);
  }

  .stat-tab.active {
    color: var(--octo-orange);
    border-bottom-color: var(--octo-orange);
  }

  .stat-filter-bar {
    background: var(--octo-light-gray);
    padding: 0.75rem 1rem;
    border-radius: 6px;
    margin-bottom: 1.5rem;
  }

  .filter-form {
    display: flex;
    gap: 0.75rem;
    align-items: center;
    font-size: 0.9rem;
  }

  .filter-form input[type="date"] {
    padding: 0.35rem 0.5rem;
    border: 2px solid var(--octo-light-gray);
    border-radius: 4px;
    font-size: 0.85rem;
    width: 145px;
  }

  .kpi-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: 1.25rem;
    margin-bottom: 2rem;
  }

  .kpi-card {
    background: var(--octo-white);
    border: 2px solid var(--octo-light-gray);
    border-radius: 8px;
    padding: 1.25rem 1.5rem;
    box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    transition: all 0.25s;
  }

  .kpi-card:hover {
    border-color: var(--octo-petrol);
    transform: translateY(-2px);
    box-shadow: 0 4px 12px rgba(0,133,145,0.15);
  }

  .kpi-icon { font-size: 1.5rem; margin-bottom: 0.5rem; }
  .kpi-label { font-size: 0.78rem; color: var(--octo-dark-petrol); font-weight: 600; text-transform: uppercase; letter-spacing: 0.6px; margin-bottom: 0.35rem; }
  .kpi-value { font-size: 2.2rem; font-weight: 700; color: var(--octo-petrol); line-height: 1; margin-bottom: 0.4rem; }
  .kpi-sub { font-size: 0.82rem; color: #6c757d; }
  .kpi-sub.positive { color: #28a745; font-weight: 600; }
  .kpi-sub.negative { color: #dc3545; font-weight: 600; }

  .stat-section { margin-bottom: 2rem; }
  .stat-section h2 { color: var(--octo-petrol); font-size: 1.1rem; margin-bottom: 1rem; padding-bottom: 0.4rem; border-bottom: 2px solid var(--octo-light-gray); }

  .chart-container { background: var(--octo-white); border: 2px solid var(--octo-light-gray); border-radius: 8px; padding: 1.25rem; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }

  .posts-table { width: 100%; border-collapse: collapse; font-size: 0.88rem; }
  .posts-table thead { background: var(--octo-petrol); color: white; }
  .posts-table th, .posts-table td { padding: 0.6rem 0.8rem; text-align: left; border-bottom: 1px solid var(--octo-light-gray); }
  .posts-table tr:hover td { background: var(--octo-light-gray); }
  .posts-table a { color: var(--octo-petrol); text-decoration: none; }
  .posts-table a:hover { color: var(--octo-orange); }

  .badge { display: inline-block; padding: 0.2rem 0.6rem; border-radius: 20px; font-size: 0.78rem; font-weight: 600; }
  .badge-impressions { background: #e3f2fd; color: #1565c0; }
  .badge-engagement { background: #e8f5e9; color: #2e7d32; }
</style>
{% endblock %}
HTMLEOF

# stat_overview.html
cat > linkedin_statistics/templates/linkedin_statistics/stat_overview.html << 'HTMLEOF'
{% extends "linkedin_statistics/stat_base.html" %}

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
    <div class="kpi-sub">Selected period</div>
  </div>

  <div class="kpi-card">
    <div class="kpi-icon">❤️</div>
    <div class="kpi-label">Total Engagement</div>
    <div class="kpi-value">{{ data.total_engagement }}</div>
    <div class="kpi-sub">Likes + Comments + Shares</div>
  </div>

</div>

<!-- Follower Chart -->
{% if data.follower_chart_labels %}
<div class="stat-section">
  <h2>📈 Follower Growth</h2>
  <div class="chart-container">
    <canvas id="followerChart" height="80"></canvas>
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
        <tr>
          <th>Post ID</th>
          <th>Date</th>
          <th>Impressions</th>
          <th>Likes</th>
          <th>Comments</th>
          <th>Shares</th>
          <th>Link</th>
        </tr>
      </thead>
      <tbody>
        {% for post in data.top_posts %}
        <tr>
          <td><small>{{ post.post_id }}</small></td>
          <td>{{ post.post_date|default:"—" }}</td>
          <td><span class="badge badge-impressions">{{ post.impressions }}</span></td>
          <td>{{ post.likes }}</td>
          <td>{{ post.comments }}</td>
          <td>{{ post.shares }}</td>
          <td>
            {% if post.post_link %}
            <a href="{{ post.post_link }}" target="_blank">🔗 Open</a>
            {% else %}—{% endif %}
          </td>
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

<div style="padding: 1rem; background: var(--octo-light-gray); border-radius: 6px; font-size: 0.88rem; color: var(--octo-dark-petrol);">
  <strong>🔜 Coming next:</strong> Post Timeline – click any post to see its performance over time.
</div>

<!-- Chart.js -->
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<script>
{% if data.follower_chart_labels %}
const ctx = document.getElementById('followerChart').getContext('2d');
new Chart(ctx, {
  type: 'line',
  data: {
    labels: {{ data.follower_chart_labels|safe }},
    datasets: [{
      label: 'Followers',
      data: {{ data.follower_chart_values|safe }},
      borderColor: '#008591',
      backgroundColor: 'rgba(0,133,145,0.08)',
      borderWidth: 2,
      tension: 0.4,
      fill: true,
      pointBackgroundColor: '#008591',
    }]
  },
  options: {
    responsive: true,
    plugins: { legend: { display: false } },
    scales: {
      y: { beginAtZero: false, grid: { color: '#F9F7F0' } },
      x: { grid: { display: false } }
    }
  }
});
{% endif %}
</script>
{% endblock %}
HTMLEOF

# stat_timeline.html
cat > linkedin_statistics/templates/linkedin_statistics/stat_timeline.html << 'HTMLEOF'
{% extends "linkedin_statistics/stat_base.html" %}

{% block stat_content %}

<div class="stat-section">
  <h2>📈 Post Timeline – All Posts</h2>
  {% if posts %}
  <div class="chart-container">
    <table class="posts-table">
      <thead>
        <tr>
          <th>#</th>
          <th>Post Date</th>
          <th>Impressions</th>
          <th>Likes</th>
          <th>Comments</th>
          <th>Shares</th>
          <th>Clicks</th>
          <th>Engagement</th>
          <th>Link</th>
        </tr>
      </thead>
      <tbody>
        {% for post in posts %}
        <tr>
          <td style="color:#6c757d;">{{ forloop.counter }}</td>
          <td>{{ post.post_date|default:post.date|default:"—" }}</td>
          <td><span class="badge badge-impressions">{{ post.impressions }}</span></td>
          <td>{{ post.likes }}</td>
          <td>{{ post.comments }}</td>
          <td>{{ post.shares }}</td>
          <td>{{ post.clicks }}</td>
          <td><span class="badge badge-engagement">{{ post.engagement }}</span></td>
          <td>
            {% if post.post_link %}
            <a href="{{ post.post_link }}" target="_blank">🔗</a>
            {% else %}—{% endif %}
          </td>
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
HTMLEOF

echo "  ✅ HTML templates created!"

# ─── STEP 5: Create views and urls ────────────────────────────────
echo ""
echo "Step 5: Creating stat_views.py and stat_urls.py..."

cat > linkedin_statistics/stat_views.py << 'EOF'
"""
Statistics Module Views
"""
from datetime import datetime, timedelta
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from .reports.stat_overview import get_overview_data
from .reports.stat_timeline import get_all_posts
from .stat_utils import get_date_range


@login_required
def overview(request):
    date_from, date_to = get_date_range(request)
    data = get_overview_data(date_from, date_to)

    default_from = (datetime.today().date() - timedelta(days=30)).strftime('%Y-%m-%d')
    default_to = datetime.today().date().strftime('%Y-%m-%d')

    return render(request, 'linkedin_statistics/stat_overview.html', {
        'data': data,
        'date_from': date_from.strftime('%Y-%m-%d'),
        'date_to': date_to.strftime('%Y-%m-%d'),
        'default_from': default_from,
        'default_to': default_to,
        'active_tab': 'overview',
    })


@login_required
def timeline(request):
    date_from, date_to = get_date_range(request)
    posts = get_all_posts(date_from, date_to)

    default_from = (datetime.today().date() - timedelta(days=30)).strftime('%Y-%m-%d')
    default_to = datetime.today().date().strftime('%Y-%m-%d')

    return render(request, 'linkedin_statistics/stat_timeline.html', {
        'posts': posts,
        'date_from': date_from.strftime('%Y-%m-%d'),
        'date_to': date_to.strftime('%Y-%m-%d'),
        'default_from': default_from,
        'default_to': default_to,
        'active_tab': 'timeline',
    })
EOF

cat > linkedin_statistics/stat_urls.py << 'EOF'
"""
Statistics Module URLs
"""
from django.urls import path
from . import stat_views

app_name = 'linkedin_statistics'

urlpatterns = [
    path('', stat_views.overview, name='overview'),
    path('timeline/', stat_views.timeline, name='timeline'),
]
EOF

echo "  ✅ Views and URLs created!"

# ─── STEP 6: Ensure urls.py has statistics route ──────────────────
echo ""
echo "Step 6: Checking dashboard/urls.py..."

if ! grep -q "linkedin_statistics" dashboard/urls.py; then
    sed -i "/include(\"collectives.urls\")/a\    path(\"statistics/\", include(\"linkedin_statistics.stat_urls\")),  # Statistics" dashboard/urls.py
    echo "  ✅ Added statistics route to urls.py"
else
    echo "  ✅ Statistics route already in urls.py"
fi

# ─── STEP 7: Ensure nav link exists in base.html ──────────────────
echo ""
echo "Step 7: Checking navigation in base.html..."

if ! grep -q "/statistics/" core/templates/core/base.html; then
    sed -i 's|<a href="/collectives/"|<a href="/statistics/" {% if '"'"'/statistics/'"'"' in request.path %}class="active"{% endif %}>Statistics</a>\n        <a href="/collectives/"|' core/templates/core/base.html
    echo "  ✅ Statistics tab added to navigation!"
else
    echo "  ✅ Statistics tab already in navigation"
fi

# ─── STEP 8: Final verification ───────────────────────────────────
echo ""
echo "=========================================="
echo "  VERIFICATION"
echo "=========================================="
echo ""
echo "INSTALLED_APPS check:"
grep "statistics" dashboard/settings.py
echo ""
echo "URL check:"
grep "statistics" dashboard/urls.py
echo ""
echo "Files created:"
find linkedin_statistics/ -type f | sort
echo ""
echo "=========================================="
echo "  ✅ ALL DONE!"
echo "=========================================="
echo ""
echo "Now run:"
echo "  python manage.py runserver 0.0.0.0:8000"
echo ""
echo "Then visit: http://localhost:8000/statistics/"

