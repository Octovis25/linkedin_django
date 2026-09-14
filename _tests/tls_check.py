"""Does the database connection really run encrypted - and verified?

It uses the app's own settings, so it tests exactly what the app does:

    python _tests/tls_check.py

Three outcomes, and each means something different:

  * a cipher name - encrypted, and under VERIFY_IDENTITY also verified
  * an empty cipher - PLAIN TEXT, whatever the settings claim
  * "certificate verify failed" - the certificate does not carry the name in
    MYSQL_HOST. Correct that name. Do not switch the check off.
"""
import os
import sys

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HIER))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dashboard.settings')

import django

django.setup()

from django.conf import settings          # noqa: E402
from django.db import connection          # noqa: E402

konfiguration = settings.DATABASES['default']
optionen = konfiguration['OPTIONS']
modus = str(optionen.get('ssl_mode', ''))

print('Host      : %s' % konfiguration['HOST'])
print('ssl_mode  : %s' % (modus or '(not set - the driver falls back to PREFERRED)'))
print('CA bundle : %s' % (optionen.get('ssl') or {}).get('ca', '-'))
print()

try:
    with connection.cursor() as zeiger:
        zeiger.execute("SHOW STATUS LIKE 'Ssl_cipher'")
        verfahren = (zeiger.fetchone() or ['', ''])[1]
        zeiger.execute("SHOW STATUS LIKE 'Ssl_version'")
        fassung = (zeiger.fetchone() or ['', ''])[1]
except Exception as fehler:
    text = str(fehler)
    print('Connection REFUSED: %s' % text[:200])
    if 'certificate verify failed' in text:
        print()
        print('The certificate does not cover the host in MYSQL_HOST.')
        print('Check the name against what the provider states.')
    sys.exit(1)

if not verfahren:
    print('Ssl_cipher : (empty)')
    print()
    print('PLAIN TEXT. This connection will be rejected from 15 September 2026.')
    sys.exit(1)

print('Ssl_cipher : %s' % verfahren)
print('Ssl_version: %s' % fassung)
print()
print('Encrypted.' + ('  And verified against the certificate.'
                      if modus.startswith('VERIFY') else
                      '  But NOT verified - ssl_mode does not check anything.'))
sys.exit(0)
