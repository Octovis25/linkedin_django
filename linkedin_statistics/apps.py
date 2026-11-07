from django.apps import AppConfig


class LinkedinStatisticsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'linkedin_statistics'
    verbose_name = 'LinkedIn Statistics'

    def ready(self):
        # A short note after logging in when the hourly Buffer fetch stopped.
        from . import signals  # noqa: F401
