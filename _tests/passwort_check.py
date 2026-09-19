"""Do the forgotten-password pages actually render?

A template that is missing, extends the wrong name, or points at a URL that no
longer exists only shows itself when somebody opens the page - and the person
opening it is somebody who is already locked out. So the four pages and the
mail are rendered here once, on purpose, before anyone needs them.

Nothing is sent and nothing is written: only rendering is exercised.

    python _tests/passwort_check.py
"""
import os
import sys

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HIER))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dashboard.settings')

import django                                        # noqa: E402

django.setup()

from django.contrib.auth.models import User          # noqa: E402
from django.contrib.auth.tokens import default_token_generator  # noqa: E402
from django.template.loader import render_to_string  # noqa: E402
from django.urls import reverse, NoReverseMatch      # noqa: E402
from django.utils.encoding import force_bytes        # noqa: E402
from django.utils.http import urlsafe_base64_encode  # noqa: E402

gut = 0
schlecht = 0


def pruefe(name, fn):
    global gut, schlecht
    try:
        text = fn()
    except Exception as fehler:
        schlecht += 1
        print('  FAIL %s\n         %s: %s' % (name, type(fehler).__name__, fehler))
        return None
    gut += 1
    print('  ok   %s  (%d characters)' % (name, len(text or '')))
    return text


print('\n=== The four pages ===')
pruefe('password_reset.html - asking for the address',
       lambda: render_to_string('core/password_reset.html', {}))
pruefe('password_reset_done.html - check your inbox',
       lambda: render_to_string('core/password_reset_done.html', {}))
pruefe('password_reset_confirm.html - a link that still works',
       lambda: render_to_string('core/password_reset_confirm.html', {'validlink': True}))
abgelaufen = pruefe('password_reset_confirm.html - a link that does not',
                    lambda: render_to_string('core/password_reset_confirm.html', {'validlink': False}))
pruefe('password_reset_complete.html - done',
       lambda: render_to_string('core/password_reset_complete.html', {}))

if abgelaufen and 'no longer works' not in abgelaufen:
    schlecht += 1
    print('  FAIL an expired link does not say so')
elif abgelaufen:
    gut += 1
    print('  ok   an expired link says so instead of showing an empty form')

print('\n=== The mail ===')
# A user object only in memory - nothing is saved and nothing is sent.
nutzer = User(username='pruefung', first_name='', email='pruefung@example.com')
mail = pruefe('password_reset_email.txt', lambda: render_to_string(
    'core/password_reset_email.txt', {
        'user': nutzer,
        'protocol': 'https',
        'domain': 'linkedin-django-wd7a.onrender.com',
        'uid': urlsafe_base64_encode(force_bytes(1)),
        'token': default_token_generator.make_token(nutzer),
    }))
pruefe('password_reset_subject.txt',
       lambda: render_to_string('core/password_reset_subject.txt', {}))

if mail:
    hat_link = 'https://linkedin-django-wd7a.onrender.com/reset/' in mail
    if hat_link:
        gut += 1
        print('  ok   the mail really carries a reset link')
    else:
        schlecht += 1
        print('  FAIL no usable link in the mail - it would be worthless')
        print('       ' + mail.replace('\n', ' ')[:160])

print('\n=== The addresses behind them ===')
for name, kwargs in [('login', {}), ('password_reset', {}), ('password_reset_done', {}),
                     ('password_reset_complete', {}),
                     ('password_reset_confirm', {'uidb64': 'MQ', 'token': 'set-password'})]:
    try:
        pfad = reverse(name, kwargs=kwargs)
        gut += 1
        print('  ok   %-24s -> %s' % (name, pfad))
    except NoReverseMatch as fehler:
        schlecht += 1
        print('  FAIL %-24s %s' % (name, fehler))

print('\n=== The way in from the login page ===')
anmeldung = pruefe('login.html', lambda: render_to_string('core/login.html', {}))
if anmeldung:
    if '/password-reset/' in anmeldung:
        gut += 1
        print('  ok   the login page links to it - otherwise nobody finds it')
    else:
        schlecht += 1
        print('  FAIL the login page has no link to the reset page')

print('\n=== Can mail be sent at all? ===')
from django.conf import settings                      # noqa: E402
fehlt = [n for n in ('EMAIL_HOST', 'EMAIL_HOST_USER', 'EMAIL_HOST_PASSWORD')
         if not getattr(settings, n, None)]
if fehlt:
    print('  Not configured here: %s' % ', '.join(fehlt))
    print('  The pages work, but no mail leaves this machine. On Render these')
    print('  are set as environment variables - the invitation mail uses them too.')
else:
    print('  ok   SMTP is configured (%s)' % settings.EMAIL_HOST)

print('\n%d ok, %d failed' % (gut, schlecht))
sys.exit(1 if schlecht else 0)
