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
