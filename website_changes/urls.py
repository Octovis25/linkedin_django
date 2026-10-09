from django.urls import path

from . import views

app_name = 'website_changes'

urlpatterns = [
    path('check/', views.check, name='check'),
]
