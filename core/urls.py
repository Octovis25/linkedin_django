from django.urls import path
from . import views

urlpatterns = [
    path('', views.home_view, name='home'),
    path('upload/', views.upload_view, name='upload'),
    path('analyze/', views.analyze_view, name='analyze'),
    path('delete/<str:filename>/', views.delete_file_view, name='delete_file'),
]
