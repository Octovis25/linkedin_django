from django.db import models

class CollectivesConfig(models.Model):
    user = models.OneToOneField('auth.User', on_delete=models.CASCADE)
    nextcloud_url = models.URLField(max_length=500, blank=True)
    kollektive_name = models.CharField(max_length=200, blank=True)
    username = models.CharField(max_length=200, blank=True)
    app_password = models.CharField(max_length=200, blank=True)
    
    class Meta:
        db_table = 'collectives_config'
    
    def __str__(self):
        return f"Config for {self.user.username}"

class PageStatus(models.Model):
    user = models.ForeignKey('auth.User', on_delete=models.CASCADE)
    path = models.CharField(max_length=1000)
    status = models.CharField(max_length=100, blank=True)
    typ = models.CharField(max_length=50, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'collectives_page_status'
        unique_together = ['user', 'path']
    
    def __str__(self):
        return f"{self.path} - {self.status}"
