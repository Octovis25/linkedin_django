"""
Statistics Module URLs
"""
from django.urls import path
from . import views

app_name = 'linkedin_statistics'

urlpatterns = [
    path('', views.overview, name='overview'),
    path('timeline/', views.timeline, name='timeline'),
]
