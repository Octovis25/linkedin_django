from django.urls import path
from . import views

urlpatterns = [
    path('', views.collectives_dashboard, name='collectives_dashboard'),
    path('api/config/', views.api_config, name='collectives_api_config'),
    path('api/test-connection/', views.api_test_connection, name='collectives_api_test'),
    path('api/pages/', views.api_pages, name='collectives_api_pages'),
    path('api/status/', views.api_status, name='collectives_api_status'),
    path('api/export-excel/', views.api_export_excel, name='collectives_api_export'),
]
