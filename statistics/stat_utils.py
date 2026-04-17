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
    default_days = 30
    date_to = timezone.now()
    date_from = date_to - timedelta(days=default_days)
    
    from_param = request.GET.get('from')
    to_param = request.GET.get('to')
    
    if from_param:
        try:
            date_from = datetime.strptime(from_param, '%Y-%m-%d')
            date_from = timezone.make_aware(date_from)
        except ValueError:
            pass
    
    if to_param:
        try:
            date_to = datetime.strptime(to_param, '%Y-%m-%d')
            date_to = timezone.make_aware(date_to)
        except ValueError:
            pass
    
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
