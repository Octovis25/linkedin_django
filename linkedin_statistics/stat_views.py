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
