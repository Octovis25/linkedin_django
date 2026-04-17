from django.apps import AppConfig

class LinkedinStatisticsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'linkedin_statistics'
    label = 'linkedin_statistics'          # explizit – verhindert Kollision
    verbose_name = 'LinkedIn Statistics'
