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
        """Get or create singleton config"""
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

class PageStatus(models.Model):
    """Stores status and type per page (replaces status.json)"""
    path = models.CharField(max_length=512, unique=True, db_index=True)
    status = models.CharField(max_length=50, blank=True, default='')
    typ = models.CharField(max_length=20, blank=True, default='')
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'collectives_pagestatus'
        verbose_name_plural = 'Page Statuses'
    
    def __str__(self):
        return f"{self.path} - {self.status}"

