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
