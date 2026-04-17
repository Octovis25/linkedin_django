"""
Overview Report - Simple KPI cards
Step 1 of statistics module
"""
from django.db.models import Sum, Count, Max
from datetime import timedelta
from django.utils import timezone

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
    
    data['total_followers'] = 0
    data['follower_growth'] = 0
    
    if Post:
        data['total_posts'] = Post.objects.filter(status='Posted').count()
        data['posts_ready'] = Post.objects.filter(status='Ready to Post').count()
    else:
        data['total_posts'] = 0
        data['posts_ready'] = 0
    
    data['total_impressions'] = 0
    data['total_engagement'] = 0
    
    if Post:
        data['top_posts'] = Post.objects.filter(
            status='Posted'
        ).order_by('-posted_date')[:3]
    else:
        data['top_posts'] = []
    
    return data
