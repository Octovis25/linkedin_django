from django.apps import AppConfig


class AuditConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'audit'
    verbose_name = 'Audit trail'

    def ready(self):
        # Sign-ins and sign-outs are not requests the middleware can read
        # well (the login POST carries a password), so they come in as signals.
        from . import signals  # noqa: F401
