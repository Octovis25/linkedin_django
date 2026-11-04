from django.urls import path

from . import views

app_name = 'website_changes'

urlpatterns = [
    path('', views.index, name='index'),
    path('detail/', views.detail, name='detail'),
    path('sync/', views.sync_now, name='sync'),
    path('note/', views.note, name='note'),
    path('author/', views.author, name='author'),
    path('check/', views.check, name='check'),
]
