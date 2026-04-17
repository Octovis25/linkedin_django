#!/bin/bash
# This script creates the complete statistics module structure

echo "Creating statistics module structure..."

# Create directories
mkdir -p statistics/reports
mkdir -p statistics/templates/statistics

# 1. statistics/__init__.py
cat > statistics/__init__.py << 'EOF'
"""
Statistics Module for LinkedIn Dashboard
Fully encapsulated analytics module
"""
EOF

# 2. statistics/stat_apps.py
cat > statistics/stat_apps.py << 'EOF'
from django.apps import AppConfig

class StatisticsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'statistics'
    verbose_name = 'LinkedIn Statistics'
EOF

# 3. statistics/stat_utils.py
cat > statistics/stat_utils.py << 'EOF'
"""
Shared utility functions for all statistics reports
"""
from datetime import datetime, timedelta
from django.utils import timezone

def get_date_range(request):
    """
    Extract date range from request parameters
    Returns (date_from, date_to) as datetime objects
    """
    # Default: last 30 days
    default_days = 30
    date_to = timezone.now()
    date_from = date_to - timedelta(days=default_days)
    
    # Check if custom range provided
    from_param = request.GET.get('from')
    to_param = request.GET.get('to')
    
    if from_param:
        try:
            date_from = datetime.strptime(from_param, '%Y-%m-%d')
            date_from = timezone.make_aware(date_from)
        except ValueError:
            pass  # Keep default
    
    if to_param:
        try:
            date_to = datetime.strptime(to_param, '%Y-%m-%d')
            date_to = timezone.make_aware(date_to)
        except ValueError:
            pass  # Keep default
    
    return date_from, date_to


def format_number(num):
    """Format large numbers with K/M suffixes"""
    if num >= 1_000_000:
        return f"{num / 1_000_000:.1f}M"
    elif num >= 1_000:
        return f"{num / 1_000:.1f}K"
    return str(num)


def calculate_growth_percentage(current, previous):
    """Calculate percentage growth between two values"""
    if previous == 0:
        return 100 if current > 0 else 0
    return round(((current - previous) / previous) * 100, 1)
EOF

# 4. statistics/reports/__init__.py
cat > statistics/reports/__init__.py << 'EOF'
"""
Statistics Reports
Each report is a separate module for easy maintenance
"""
from .stat_overview import get_overview_data

__all__ = ['get_overview_data']
EOF

# 5. statistics/reports/stat_overview.py
cat > statistics/reports/stat_overview.py << 'EOF'
"""
Overview Report - Simple KPI cards
Step 1 of statistics module
"""
from django.db.models import Sum, Count, Max
from datetime import timedelta
from django.utils import timezone

# Import existing models from other apps
try:
    from posts_posted.models import Post
except ImportError:
    Post = None


def get_overview_data(date_from=None, date_to=None):
    """
    Calculate overview KPIs for the statistics dashboard
    Returns dict with all card data
    """
    data = {}
    
    # --- Card 1: Total Followers ---
    # TODO: Add once we verify the model structure
    data['total_followers'] = 0
    data['follower_growth'] = 0
    
    # --- Card 2: Total Posts ---
    if Post:
        data['total_posts'] = Post.objects.filter(status='Posted').count()
        data['posts_ready'] = Post.objects.filter(status='Ready to Post').count()
    else:
        data['total_posts'] = 0
        data['posts_ready'] = 0
    
    # --- Card 3: Total Impressions ---
    data['total_impressions'] = 0
    
    # --- Card 4: Engagement Rate ---
    data['total_engagement'] = 0
    
    # --- Card 5: Top 3 Posts ---
    if Post:
        data['top_posts'] = Post.objects.filter(
            status='Posted'
        ).order_by('-posted_date')[:3]
    else:
        data['top_posts'] = []
    
    return data
EOF

# 6. statistics/stat_views.py
cat > statistics/stat_views.py << 'EOF'
"""
Statistics Module Views
Entry point for all statistics pages
"""
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from .reports.stat_overview import get_overview_data
from .stat_utils import get_date_range


@login_required
def overview(request):
    """
    Main statistics overview page
    Shows KPI cards and basic metrics
    """
    date_from, date_to = get_date_range(request)
    data = get_overview_data(date_from, date_to)
    
    context = {
        'overview_data': data,
        'date_from': date_from,
        'date_to': date_to,
    }
    
    return render(request, 'statistics/stat_overview.html', context)
EOF

# 7. statistics/stat_urls.py
cat > statistics/stat_urls.py << 'EOF'
"""
Statistics Module URLs
All routes for the statistics module
"""
from django.urls import path
from . import stat_views

app_name = 'statistics'

urlpatterns = [
    path('', stat_views.overview, name='overview'),
    # Future routes:
    # path('timeline/', stat_views.timeline, name='timeline'),
    # path('followers/', stat_views.followers, name='followers'),
]
EOF

# 8. statistics/templates/statistics/stat_base.html
cat > statistics/templates/statistics/stat_base.html << 'HTMLEOF'
{% extends "core/base.html" %}

{% block content %}
<div class="statistics-wrapper">
    <div class="stats-header">
        <h1>{% block stats_title %}Statistics{% endblock %}</h1>
        
        <!-- Date Range Filter -->
        <div class="date-filter">
            <form method="get" class="filter-form">
                <label for="date-from">From:</label>
                <input type="date" id="date-from" name="from" value="{{ date_from|date:'Y-m-d' }}">
                
                <label for="date-to">To:</label>
                <input type="date" id="date-to" name="to" value="{{ date_to|date:'Y-m-d' }}">
                
                <button type="submit" class="btn btn-primary btn-sm">Apply</button>
            </form>
        </div>
    </div>
    
    {% block stats_content %}
    <!-- Content from child templates -->
    {% endblock %}
</div>

<style>
    .statistics-wrapper {
        padding: 1rem 0;
    }
    
    .stats-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 2rem;
    }
    
    .stats-header h1 {
        margin: 0;
    }
    
    .date-filter {
        display: flex;
        gap: 0.75rem;
        align-items: center;
    }
    
    .filter-form {
        display: flex;
        gap: 0.5rem;
        align-items: center;
    }
    
    .filter-form label {
        margin: 0;
        font-size: 0.9rem;
    }
    
    .filter-form input[type="date"] {
        padding: 0.4rem;
        font-size: 0.85rem;
        width: 140px;
    }
    
    .kpi-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
        gap: 1.5rem;
        margin-bottom: 2rem;
    }
    
    .kpi-card {
        background: var(--octo-white);
        border: 2px solid var(--octo-light-gray);
        border-radius: 8px;
        padding: 1.5rem;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        transition: all 0.3s;
    }
    
    .kpi-card:hover {
        border-color: var(--octo-petrol);
        box-shadow: 0 4px 8px rgba(0,133,145,0.1);
    }
    
    .kpi-label {
        font-size: 0.85rem;
        color: var(--octo-dark-petrol);
        font-weight: 500;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        margin-bottom: 0.5rem;
    }
    
    .kpi-value {
        font-size: 2rem;
        font-weight: 700;
        color: var(--octo-petrol);
        margin-bottom: 0.5rem;
    }
    
    .kpi-change {
        font-size: 0.85rem;
        font-weight: 500;
    }
    
    .kpi-change.positive {
        color: #28a745;
    }
    
    .kpi-change.negative {
        color: #dc3545;
    }
    
    .kpi-change.neutral {
        color: #6c757d;
    }
    
    .top-posts-list {
        list-style: none;
        padding: 0;
    }
    
    .top-posts-list li {
        padding: 0.75rem;
        border-bottom: 1px solid var(--octo-light-gray);
    }
    
    .top-posts-list li:last-child {
        border-bottom: none;
    }
    
    .post-title {
        font-weight: 500;
        color: var(--octo-petrol);
        margin-bottom: 0.25rem;
    }
    
    .post-meta {
        font-size: 0.85rem;
        color: #6c757d;
    }
</style>
{% endblock %}
HTMLEOF

# 9. statistics/templates/statistics/stat_overview.html
cat > statistics/templates/statistics/stat_overview.html << 'HTMLEOF'
{% extends "statistics/stat_base.html" %}

{% block stats_title %}LinkedIn Statistics – Overview{% endblock %}

{% block stats_content %}
<div class="kpi-grid">
    <!-- Card 1: Total Followers -->
    <div class="kpi-card">
        <div class="kpi-label">Total Followers</div>
        <div class="kpi-value">{{ overview_data.total_followers|default:"—" }}</div>
        <div class="kpi-change {% if overview_data.follower_growth > 0 %}positive{% elif overview_data.follower_growth < 0 %}negative{% else %}neutral{% endif %}">
            {% if overview_data.follower_growth > 0 %}↑{% elif overview_data.follower_growth < 0 %}↓{% endif %}
            {{ overview_data.follower_growth|default:"0" }}%
        </div>
    </div>
    
    <!-- Card 2: Total Posts -->
    <div class="kpi-card">
        <div class="kpi-label">Posts Published</div>
        <div class="kpi-value">{{ overview_data.total_posts|default:"0" }}</div>
        <div class="kpi-change neutral">
            {{ overview_data.posts_ready|default:"0" }} ready to post
        </div>
    </div>
    
    <!-- Card 3: Total Impressions -->
    <div class="kpi-card">
        <div class="kpi-label">Total Impressions</div>
        <div class="kpi-value">{{ overview_data.total_impressions|default:"—" }}</div>
        <div class="kpi-change neutral">
            Last 30 days
        </div>
    </div>
    
    <!-- Card 4: Total Engagement -->
    <div class="kpi-card">
        <div class="kpi-label">Total Engagement</div>
        <div class="kpi-value">{{ overview_data.total_engagement|default:"—" }}</div>
        <div class="kpi-change neutral">
            Likes + Comments + Shares
        </div>
    </div>
</div>

<!-- Top Posts Section -->
{% if overview_data.top_posts %}
<div class="card">
    <h2>Top 3 Recent Posts</h2>
    <ul class="top-posts-list">
        {% for post in overview_data.top_posts %}
        <li>
            <div class="post-title">{{ post.title }}</div>
            <div class="post-meta">
                Posted: {{ post.posted_date|date:"d.m.Y" }}
                {% if post.linkedin_url %}
                | <a href="{{ post.linkedin_url }}" target="_blank">View on LinkedIn</a>
                {% endif %}
            </div>
        </li>
        {% endfor %}
    </ul>
</div>
{% else %}
<div class="card">
    <p style="color: #6c757d; text-align: center;">No posts found.</p>
</div>
{% endif %}

<div style="margin-top: 2rem; padding: 1rem; background: var(--octo-light-gray); border-radius: 6px;">
    <p style="margin: 0; color: var(--octo-dark-petrol); font-size: 0.9rem;">
        <strong>🔜 Coming soon:</strong> Clickable post timeline, follower growth charts, and competitor analysis.
    </p>
</div>
{% endblock %}
HTMLEOF

echo "✅ Statistics module created successfully!"
echo ""
echo "Files created:"
echo "  - statistics/__init__.py"
echo "  - statistics/stat_apps.py"
echo "  - statistics/stat_utils.py"
echo "  - statistics/stat_views.py"
echo "  - statistics/stat_urls.py"
echo "  - statistics/reports/__init__.py"
echo "  - statistics/reports/stat_overview.py"
echo "  - statistics/templates/statistics/stat_base.html"
echo "  - statistics/templates/statistics/stat_overview.html"
echo ""
echo "Next steps:"
echo "1. Add 'statistics' to INSTALLED_APPS in dashboard/settings.py"
echo "2. Add path('statistics/', include('statistics.stat_urls')) to dashboard/urls.py"
echo "3. Run: git add statistics/"
echo "4. Run: git commit -m 'Add statistics module'"
echo "5. Run: git push"

