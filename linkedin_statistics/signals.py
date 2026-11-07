"""After a superuser logs in: one short note when the hourly Buffer fetch
has stopped or failed (07.11.2026). Nothing else; a login never fails
because of it."""
from django.contrib import messages
from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver


@receiver(user_logged_in)
def fetch_note(sender, request, user, **kwargs):
    if request is None or not getattr(user, 'is_superuser', False):
        return
    try:
        from . import buffer_metrics as bm
        text = bm.fetch_problem()
    except Exception:
        return
    if text:
        messages.warning(request, text, fail_silently=True)
