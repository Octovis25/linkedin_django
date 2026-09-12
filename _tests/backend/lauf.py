"""Startet die Backend-Tests.

    python _tests/backend/lauf.py                 # alles
    python _tests/backend/lauf.py test_loeschen   # nur ein Teil

Gebraucht wird eine MySQL- oder MariaDB-Datenbank, in die geschrieben werden
darf. Django legt sich daraus eine eigene Testdatenbank an (test_<name>) und
wirft sie am Ende weg - die echten Daten werden nicht angefasst.

Voreinstellung ist eine lokale Datenbank; abweichende Zugaenge ueber
Umgebungsvariablen::

    PRUEF_DB_HOST   (Vorgabe 127.0.0.1)
    PRUEF_DB_PORT   (3306)
    PRUEF_DB_USER   (pruef)
    PRUEF_DB_PASS   (pruef)
    PRUEF_DB        (pruef_db)

Die Tests sprechen NICHT mit Nextcloud. basis.py setzt an dessen Stelle eine
Attrappe, die sich auf Kommando weigert - genau das laesst sich mit der echten
Wolke nicht herstellen, und genau daran sind die Fehler dieser App entstanden.
"""
import os
import sys

WURZEL = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, WURZEL)

os.environ['DJANGO_SETTINGS_MODULE'] = '_tests.backend.settings'

import django                                     # noqa: E402
from django.test.utils import get_runner          # noqa: E402
from django.conf import settings                  # noqa: E402

django.setup()

teile = sys.argv[1:] or ['']
ziele = ['_tests.backend' + ('.' + t if t else '') for t in teile]

Laeufer = get_runner(settings)
fehler = Laeufer(verbosity=1, interactive=False).run_tests(ziele)
sys.exit(bool(fehler))
