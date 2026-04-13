#!/bin/bash
# ══════════════════════════════════════════════════════════════
# SCHRITT 1: models.py ersetzen
# ══════════════════════════════════════════════════════════════
cat > collectives/models.py << 'EOF'
from django.db import models

class CollectivesConfig(models.Model):
    """Stores Nextcloud connection settings (replaces config.json)"""
    nextcloud_url = models.CharField(max_length=255, blank=True, default='')
    kollektive_name = models.CharField(max_length=100, blank=True, default='')
    username = models.CharField(max_length=100, blank=True, default='')
    app_password = models.CharField(max_length=255, blank=True, default='')
    connected = models.BooleanField(default=False)

    class Meta:
        db_table = 'collectives_config'

    @classmethod
    def get_config(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

class PageStatus(models.Model):
    """Stores status and type per page — folder = eindeutige ID"""
    path = models.CharField(max_length=512, unique=True, db_index=True)
    status = models.CharField(max_length=50, blank=True, default='')
    typ = models.CharField(max_length=20, blank=True, default='')
    planned_date = models.DateField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'collectives_pagestatus'
        verbose_name_plural = 'Page Statuses'

    def __str__(self):
        return f"{self.path} - {self.status}"
EOF
echo "✅ models.py ersetzt"

# ══════════════════════════════════════════════════════════════
# SCHRITT 2: urls.py ersetzen
# ══════════════════════════════════════════════════════════════
cat > collectives/urls.py << 'EOF'
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
    path('api/sync/', views.sync_collective_posts, name='sync'),
]
EOF
echo "✅ urls.py ersetzt"

# ══════════════════════════════════════════════════════════════
# SCHRITT 3: Migration ausführen
# ══════════════════════════════════════════════════════════════
python manage.py makemigrations
python manage.py migrate
echo "✅ Migration done"
