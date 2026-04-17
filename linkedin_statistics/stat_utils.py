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
