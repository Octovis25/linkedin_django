"""Test fuer _get_nc_credentials in posts_posted/nc_storage.py.

Diese eine Funktion entscheidet, ob Nextcloud in der ganzen App funktioniert -
jeder Upload, jeder Download, jede Loeschung fragt sie. Sie hatte einen
Fehler, den man nicht sieht, sondern nur an seiner Wirkung merkt:

Der Rueckfall auf die Umgebungsvariablen lief NUR bei einer Ausnahme.
CollectivesConfig.get_config() wirft aber keine - es ist ein
get_or_create(pk=1), und alle Felder haben '' als Vorgabe. Auf einer frischen
Datenbank legt der erste Aufruf also eine leere Zeile an und liefert
('', '', ''), waehrend daneben korrekt gesetzte Umgebungsvariablen nie
drankommen. Nextcloud ist dann tot, und nirgends steht ein Fehler.

Django laeuft hier nicht. Die Funktion wird aus nc_storage.py herausgeschnitten
und gegen eine nachgestellte collectives.models laufen gelassen - so lassen
sich die Faelle durchspielen, die in echt weh tun.

    python _tests/nc_zugang_test.py
"""
import ast
import os
import sys
import types

HIER = os.path.dirname(os.path.abspath(__file__))
KANDIDATEN = [
    os.path.join(HIER, '..', 'posts_posted', 'nc_storage.py'),
    os.path.join(HIER, 'nc_storage.py'),
]

datei = next((p for p in KANDIDATEN if os.path.exists(p)), None)
if not datei:
    print('posts_posted/nc_storage.py nicht gefunden. Gesucht in:')
    for p in KANDIDATEN:
        print('  ' + os.path.abspath(p))
    sys.exit(2)

quelle = open(datei, encoding='utf-8').read()
baum = ast.parse(quelle)
schnitt = None
for knoten in baum.body:
    if isinstance(knoten, ast.FunctionDef) and knoten.name == '_get_nc_credentials':
        schnitt = ast.get_source_segment(quelle, knoten)
if not schnitt:
    print('_get_nc_credentials nicht gefunden - nc_storage.py wurde umgebaut.')
    sys.exit(2)

raum = {'os': os}
exec(schnitt, raum)
hole = raum['_get_nc_credentials']

gut = schlecht = 0


def pruefe(name, bedingung, zusatz=''):
    global gut, schlecht
    if bedingung:
        gut += 1
        print('  ok   ' + name)
    else:
        schlecht += 1
        print('  FEHL ' + name + ('  -> ' + str(zusatz) if zusatz else ''))


class Zeile:
    def __init__(self, url='', user='', pw=''):
        self.nextcloud_url, self.username, self.app_password = url, user, pw


def stelle_db(zeile_oder_fehler):
    """collectives.models nachstellen. None = das Modul wirft beim Zugriff."""
    modul = types.ModuleType('collectives.models')

    class CollectivesConfig:
        @classmethod
        def get_config(cls):
            if zeile_oder_fehler is None:
                raise RuntimeError('keine Datenbank')
            return zeile_oder_fehler

    modul.CollectivesConfig = CollectivesConfig
    paket = types.ModuleType('collectives')
    paket.models = modul
    sys.modules['collectives'] = paket
    sys.modules['collectives.models'] = modul


def stelle_umgebung(url='', user='', pw=''):
    for schluessel, wert in (('NEXTCLOUD_URL', url),
                             ('NEXTCLOUD_USER', user),
                             ('NEXTCLOUD_APP_PASSWORD', pw)):
        if wert:
            os.environ[schluessel] = wert
        else:
            os.environ.pop(schluessel, None)


DB = ('https://wolke.example', 'ortrud', 'geheim-db')
UMG = ('https://umgebung.example', 'ortrud-umg', 'geheim-umg')

print('\n=== Die Datenbank ist vollstaendig: sie gewinnt ===')
stelle_db(Zeile(*DB))
stelle_umgebung(*UMG)
pruefe('vollstaendige DB-Zeile schlaegt die Umgebung', hole() == DB, hole())

print('\n=== Die leere Zeile - der eigentliche Fehler ===')
# get_or_create(pk=1) legt genau so eine Zeile an. Keine Ausnahme, nur leer.
stelle_db(Zeile('', '', ''))
stelle_umgebung(*UMG)
pruefe('leere DB-Zeile faellt auf die Umgebung zurueck', hole() == UMG, hole())

print('\n=== Halb gefuellt ist auch nicht brauchbar ===')
for fehlt, zeile in [('das Passwort', Zeile(DB[0], DB[1], '')),
                     ('der Benutzer', Zeile(DB[0], '', DB[2])),
                     ('die URL', Zeile('', DB[1], DB[2]))]:
    stelle_db(zeile)
    stelle_umgebung(*UMG)
    pruefe('es fehlt %-14s -> Umgebung' % fehlt, hole() == UMG, hole())

print('\n=== Leerzeichen sind kein Inhalt ===')
stelle_db(Zeile('   ', '  ', ' '))
stelle_umgebung(*UMG)
pruefe('nur Leerzeichen gilt als leer', hole() == UMG, hole())
stelle_db(Zeile('  %s  ' % DB[0], ' %s ' % DB[1], ' %s ' % DB[2]))
stelle_umgebung(*UMG)
pruefe('umgebende Leerzeichen werden abgeschnitten', hole() == DB, hole())

print('\n=== None statt leerem Text (aeltere Zeilen) ===')
stelle_db(Zeile(None, None, None))
stelle_umgebung(*UMG)
pruefe('None wirft nicht, sondern faellt zurueck', hole() == UMG, hole())

print('\n=== Gar keine Datenbank ===')
stelle_db(None)
stelle_umgebung(*UMG)
pruefe('Ausnahme faellt auf die Umgebung zurueck', hole() == UMG, hole())

print('\n=== Nichts konfiguriert ===')
stelle_db(Zeile('', '', ''))
stelle_umgebung()
pruefe('alles leer liefert drei leere Texte, keinen Absturz',
       hole() == ('', '', ''), hole())

print('\n=== Die Rueckgabe hat immer dieselbe Form ===')
for aufbau in [Zeile(*DB), Zeile('', '', ''), Zeile(None, None, None)]:
    stelle_db(aufbau)
    stelle_umgebung(*UMG)
    w = hole()
    if not (isinstance(w, tuple) and len(w) == 3 and all(isinstance(x, str) for x in w)):
        pruefe('immer drei Texte', False, w)
        break
else:
    pruefe('immer drei Texte', True)

print('\n%d ok, %d fehlgeschlagen' % (gut, schlecht))
sys.exit(1 if schlecht else 0)
