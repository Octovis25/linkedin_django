from django.urls import path
from . import views

app_name = 'collectives'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('api/config/', views.api_config, name='api_config'),
    path('api/test-connection/', views.test_connection, name='test_connection'),
    path('api/status/', views.get_status, name='get_status'),
    path('api/status/set/', views.set_status, name='set_status'),
    path('api/pages/', views.get_pages, name='get_pages'),
    path('api/export-excel/', views.export_excel, name='export_excel'),
]
