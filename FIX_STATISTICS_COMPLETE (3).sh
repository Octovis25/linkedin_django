#!/bin/bash
set -e
echo "=== STATISTIK-MODUL KOMPLETT-FIX ==="

# 1. views.py
echo "1. Schreibe views.py..."
cat > linkedin_statistics/views.py << 'VIEWS'
from datetime import date
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.db import connection
import json

@login_required
def overview(request):
    d_from = request.GET.get('date_from', '2024-01-01')
    d_to   = request.GET.get('date_to', date.today().isoformat())
    
    data = {
        'total_followers': 0,
        'total_posts': 0,
        'total_impressions': 0,
        'total_engagement': 0,
        'top_posts': [],
        'content_chart_labels': [],
        'content_chart_impressions': [],
        'content_chart_engagement': [],
    }
    
    with connection.cursor() as cur:
        # Followers
        cur.execute("SELECT followers_total FROM linkedin_followers ORDER BY date DESC LIMIT 1")
        row = cur.fetchone()
        if row: data['total_followers'] = row[0]
        
        # Posts
        cur.execute("SELECT COUNT(*) FROM linkedin_posts")
        row = cur.fetchone()
        if row: data['total_posts'] = row[0]
        
        # Impressionen
        cur.execute("SELECT COALESCE(SUM(impressions),0) FROM linkedin_posts_metrics WHERE metric_date BETWEEN %s AND %s", [d_from, d_to])
        row = cur.fetchone()
        if row: data['total_impressions'] = row[0]
        
        # Engagement
        cur.execute("SELECT COALESCE(SUM(likes+comments+direct_shares),0) FROM linkedin_posts_metrics WHERE metric_date BETWEEN %s AND %s", [d_from, d_to])
        row = cur.fetchone()
        if row: data['total_engagement'] = row[0]
        
        # Top Posts
        cur.execute("""
            SELECT lp.post_id, 
                   COALESCE(lp.post_title, lp.post_id) AS title,
                   lp.post_date,
                   lp.post_url,
                   COALESCE(SUM(m.impressions),0) AS impressions,
                   COALESCE(SUM(m.likes),0) AS likes,
                   COALESCE(SUM(m.comments),0) AS comments,
                   COALESCE(SUM(m.direct_shares),0) AS shares
            FROM linkedin_posts lp
            LEFT JOIN linkedin_posts_metrics m ON lp.post_id = m.post_id
            GROUP BY lp.post_id, lp.post_title, lp.post_date, lp.post_url
            ORDER BY impressions DESC LIMIT 5
        """)
        cols = [c[0] for c in cur.description]
        data['top_posts'] = [dict(zip(cols, r)) for r in cur.fetchall()]
        
        # Chart
        cur.execute("""
            SELECT DATE_FORMAT(metric_date,'%Y-%m') AS month,
                   COALESCE(SUM(impressions),0) AS impressions,
                   COALESCE(SUM(likes+comments+direct_shares),0) AS engagement
            FROM linkedin_posts_metrics
            WHERE metric_date IS NOT NULL
            GROUP BY month ORDER BY month ASC
        """)
        rows = cur.fetchall()
        data['content_chart_labels'] = [r[0] for r in rows]
        data['content_chart_impressions'] = [int(r[1]) for r in rows]
        data['content_chart_engagement'] = [int(r[2]) for r in rows]
    
    return render(request, 'linkedin_statistics/overview.html', {
        'date_from': d_from,
        'date_to': d_to,
        'data': data,
        'chart_json': json.dumps({
            'labels': data['content_chart_labels'],
            'impressions': data['content_chart_impressions'],
            'engagement': data['content_chart_engagement'],
        }),
    })

@login_required
def timeline(request):
    posts = []
    with connection.cursor() as cur:
        cur.execute("""
            SELECT lp.post_id, 
                   COALESCE(lp.post_title, lp.post_id) AS title,
                   COALESCE(pp.post_date, lp.post_date) AS post_date,
                   lp.post_url
            FROM linkedin_posts lp
            LEFT JOIN linkedin_posts_posted pp ON lp.post_id = pp.post_id
            ORDER BY COALESCE(pp.post_date, lp.post_date) DESC
        """)
        cols = [c[0] for c in cur.description]
        posts = [dict(zip(cols, r)) for r in cur.fetchall()]
    
    return render(request, 'linkedin_statistics/timeline.html', {'posts': posts})

@login_required
def timeline_detail(request, post_id):
    post = None
    chart_data = None
    
    with connection.cursor() as cur:
        cur.execute("""
            SELECT lp.post_id, COALESCE(lp.post_title,lp.post_id) AS title,
                   lp.post_date, lp.post_url
            FROM linkedin_posts lp WHERE lp.post_id=%s
        """, [post_id])
        cols = [c[0] for c in cur.description]
        row = cur.fetchone()
        if row: post = dict(zip(cols, row))
        
        cur.execute("""
            SELECT DATE_FORMAT(metric_date,'%Y-%m') AS month,
                   COALESCE(SUM(impressions),0) AS impressions,
                   COALESCE(SUM(clicks),0) AS clicks,
                   COALESCE(SUM(likes),0) AS likes
            FROM linkedin_posts_metrics WHERE post_id=%s AND metric_date IS NOT NULL
            GROUP BY month ORDER BY month ASC
        """, [post_id])
        cols = [c[0] for c in cur.description]
        rows = [dict(zip(cols,r)) for r in cur.fetchall()]
        if rows:
            chart_data = {
                'labels': [r['month'] for r in rows],
                'impressions': [r['impressions'] for r in rows],
                'clicks': [r['clicks'] for r in rows],
                'likes': [r['likes'] for r in rows],
            }
    
    return render(request, 'linkedin_statistics/timeline_detail.html', {
        'post': post,
        'chart_json': json.dumps(chart_data) if chart_data else 'null',
    })
VIEWS

# 2. overview.html
echo "2. Schreibe overview.html..."
mkdir -p linkedin_statistics/templates/linkedin_statistics
cat > linkedin_statistics/templates/linkedin_statistics/overview.html << 'TMPL'
{% extends "core/base.html" %}
{% block content %}
<div class="container mt-4">
    <h1>LinkedIn Statistics – Overview</h1>
    
    <div class="row mt-4">
        <div class="col-md-3">
            <div class="card">
                <div class="card-body">
                    <h5>Followers</h5>
                    <h2>{{ data.total_followers|default:"0" }}</h2>
                </div>
            </div>
        </div>
        <div class="col-md-3">
            <div class="card">
                <div class="card-body">
                    <h5>Posts</h5>
                    <h2>{{ data.total_posts|default:"0" }}</h2>
                </div>
            </div>
        </div>
        <div class="col-md-3">
            <div class="card">
                <div class="card-body">
                    <h5>Impressions</h5>
                    <h2>{{ data.total_impressions|default:"0" }}</h2>
                </div>
            </div>
        </div>
        <div class="col-md-3">
            <div class="card">
                <div class="card-body">
                    <h5>Engagement</h5>
                    <h2>{{ data.total_engagement|default:"0" }}</h2>
                </div>
            </div>
        </div>
    </div>
    
    <div class="row mt-4">
        <div class="col-12">
            <h3>Top 5 Posts</h3>
            <table class="table">
                <thead><tr><th>Post</th><th>Date</th><th>Impressions</th><th>Likes</th></tr></thead>
                <tbody>
                {% for post in data.top_posts %}
                <tr>
                    <td><a href="{{ post.post_url }}" target="_blank">{{ post.title }}</a></td>
                    <td>{{ post.post_date|date:"d.m.Y" }}</td>
                    <td>{{ post.impressions }}</td>
                    <td>{{ post.likes }}</td>
                </tr>
                {% empty %}
                <tr><td colspan="4">Keine Daten</td></tr>
                {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
    
    <div class="row mt-4">
        <div class="col-12">
            <h3>Impressions pro Monat</h3>
            <canvas id="chart" width="400" height="100"></canvas>
        </div>
    </div>
</div>

<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<script>
const chartData = {{ chart_json|safe }};
new Chart(document.getElementById('chart'), {
    type: 'line',
    data: {
        labels: chartData.labels,
        datasets: [{
            label: 'Impressions',
            data: chartData.impressions,
            borderColor: '#0077b5',
            fill: false
        }]
    }
});
</script>
{% endblock %}
TMPL

# 3. timeline.html
echo "3. Schreibe timeline.html..."
cat > linkedin_statistics/templates/linkedin_statistics/timeline.html << 'TMPL2'
{% extends "core/base.html" %}
{% block content %}
<div class="container mt-4">
    <h1>LinkedIn Statistics – Timeline</h1>
    
    <table class="table mt-4">
        <thead><tr><th>Post</th><th>Date</th><th>Link</th></tr></thead>
        <tbody>
        {% for post in posts %}
        <tr>
            <td>{{ post.title }}</td>
            <td>{{ post.post_date|date:"d.m.Y" }}</td>
            <td><a href="{{ post.post_url }}" target="_blank">View</a></td>
        </tr>
        {% empty %}
        <tr><td colspan="3">Keine Posts</td></tr>
        {% endfor %}
        </tbody>
    </table>
</div>
{% endblock %}
TMPL2

# 4. timeline_detail.html
echo "4. Schreibe timeline_detail.html..."
cat > linkedin_statistics/templates/linkedin_statistics/timeline_detail.html << 'TMPL3'
{% extends "core/base.html" %}
{% block content %}
<div class="container mt-4">
    <h1>Post Details</h1>
    {% if post %}
    <h3>{{ post.title }}</h3>
    <p>Date: {{ post.post_date|date:"d.m.Y" }}</p>
    <p><a href="{{ post.post_url }}" target="_blank">View on LinkedIn</a></p>
    
    <canvas id="chart" width="400" height="100"></canvas>
    
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script>
    const chartData = {{ chart_json|safe }};
    if (chartData) {
        new Chart(document.getElementById('chart'), {
            type: 'line',
            data: {
                labels: chartData.labels,
                datasets: [{
                    label: 'Impressions',
                    data: chartData.impressions,
                    borderColor: '#0077b5'
                }]
            }
        });
    }
    </script>
    {% else %}
    <p>Post nicht gefunden.</p>
    {% endif %}
</div>
{% endblock %}
TMPL3

echo ""
echo "=== COMMIT & PUSH ==="
git add linkedin_statistics/
git commit -m "fix: statistics komplett neu - views + templates"
git push

echo ""
echo "✅ FERTIG - Server neu starten und /statistics/ aufrufen"
