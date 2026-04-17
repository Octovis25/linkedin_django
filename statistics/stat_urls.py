"""
Statistics Module URLs
All routes for the statistics module
"""
from django.urls import path
from . import stat_views

app_name = 'statistics'

urlpatterns = [
    path('', stat_views.overview, name='overview'),
]
