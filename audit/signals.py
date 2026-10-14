"""Sign-ins, sign-outs and failed sign-ins in the audit trail.

The password never reaches this code: Django passes failed attempts with the
credentials already cleansed, and only the user name is kept.
"""
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver

from . import store


def _path(request):
    return getattr(request, 'path', '') if request is not None else ''


@receiver(user_logged_in)
def logged_in(sender, request, user, **kwargs):
    store.write(user.get_username(), 'POST', _path(request), view='auth:login',
                action='login', status=200, user_id=user.pk)


@receiver(user_logged_out)
def logged_out(sender, request, user, **kwargs):
    if user is None:
        return
    store.write(user.get_username(), 'POST', _path(request), view='auth:logout',
                action='logout', status=200, user_id=user.pk)


@receiver(user_login_failed)
def login_failed(sender, credentials, request=None, **kwargs):
    name = str((credentials or {}).get('username', ''))[:150]
    store.write(name or '(unknown)', 'POST', _path(request), view='auth:login',
                action='login failed', status=401)
