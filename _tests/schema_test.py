"""Test fuer die Schema-Pflege.

Die App legt fehlende Tabellen und Spalten selbst an. Das lief bisher bei JEDEM
Seitenaufruf: 17 ALTER-Versuche in planner/views.py, 11 in
media_library/views.py, allein "linkedin_posted" siebenmal. MySQL quittiert
jeden mit einem Fehler, den ein except schluckt - Zeit bei jedem Aufruf, und
echte Schemaprobleme gehen im Rauschen unter.

Geprueft werden die beiden Stellen, an denen das jetzt entschieden wird:

  * fehlende_spalten()  - welche Spalten ueberhaupt angelegt werden muessen.
    Eine falsche Auswahl hiesse: entweder ein ALTER auf eine Spalte, die es
    gibt (das alte Verhalten), oder eine fehlende Spalte bleibt fehlend.
  * einmal_pro_prozess() - dass die Pflege genau einmal laeuft, und dass ein
    Fehlschlag NICHT als erledigt gilt.

    python _tests/schema_test.py
"""
import ast
import functools
import os
import sys

HIER = os.path.dirname(os.path.abspath(__file__))


def hole(dateiname, unterordner, namen):
    """Benannte Funktionen/Zuweisungen aus einer Quelldatei herausschneiden."""
    kandidaten = [os.path.join(HIER, '..', unterordner, dateiname),
                  os.path.join(HIER, dateiname)]
    datei = next((p for p in kandidaten if os.path.exists(p)), None)
    if not datei:
        print('%s/%s nicht gefunden. Gesucht in:' % (unterordner, dateiname))
        for p in kandidaten:
            print('  ' + os.path.abspath(p))
        sys.exit(2)
    quelle = open(datei, encoding='utf-8').read()
    baum = ast.parse(quelle)
    teile = []
    gefunden = set()
    for knoten in baum.body:
        if isinstance(knoten, ast.FunctionDef) and knoten.name in namen:
            teile.append(ast.get_source_segment(quelle, knoten))
            gefunden.add(knoten.name)
        elif isinstance(knoten, ast.Assign):
            for ziel in knoten.targets:
                if isinstance(ziel, ast.Name) and ziel.id in namen:
                    teile.append(ast.get_source_segment(quelle, knoten))
                    gefunden.add(ziel.id)
    fehlt = set(namen) - gefunden
    if fehlt:
        print('In %s fehlen: %s' % (dateiname, ', '.join(sorted(fehlt))))
        print('Die Schema-Pflege wurde umgebaut - diesen Test nachziehen.')
        sys.exit(2)
    raum = {'os': os, 'functools': functools}
    exec('\n\n'.join(teile), raum)
    return raum


planner = hole('views.py', 'planner', ['fehlende_spalten', 'NACHGERUESTETE_SPALTEN'])
fehlende_spalten = planner['fehlende_spalten']
NACHGERUESTETE_SPALTEN = planner['NACHGERUESTETE_SPALTEN']

medien = hole('views.py', 'media_library', ['einmal_pro_prozess', '_SCHEMA_GEPRUEFT'])
einmal_pro_prozess = medien['einmal_pro_prozess']
_SCHEMA_GEPRUEFT = medien['_SCHEMA_GEPRUEFT']

gut = schlecht = 0


def pruefe(name, bedingung, zusatz=''):
    global gut, schlecht
    if bedingung:
        gut += 1
        print('  ok   ' + name)
    else:
        schlecht += 1
        print('  FEHL ' + name + ('  -> ' + str(zusatz) if zusatz else ''))


ERWARTET = (
    ('t1', 'a', 'INT'),
    ('t1', 'b', 'INT'),
    ('t2', 'c', 'INT'),
)

print('\n=== Welche Spalten fehlen ===')
pruefe('alles da -> nichts zu tun',
       fehlende_spalten({'t1': {'a', 'b'}, 't2': {'c'}}, ERWARTET) == [],
       fehlende_spalten({'t1': {'a', 'b'}, 't2': {'c'}}, ERWARTET))
pruefe('eine fehlt -> genau diese eine',
       fehlende_spalten({'t1': {'a'}, 't2': {'c'}}, ERWARTET) == [('t1', 'b', 'INT')],
       fehlende_spalten({'t1': {'a'}, 't2': {'c'}}, ERWARTET))
pruefe('leere Tabelle -> alle ihre Spalten',
       fehlende_spalten({'t1': set(), 't2': {'c'}}, ERWARTET)
       == [('t1', 'a', 'INT'), ('t1', 'b', 'INT')],
       fehlende_spalten({'t1': set(), 't2': {'c'}}, ERWARTET))

print('\n=== Unbekannte Tabellen werden in Ruhe gelassen ===')
# Wichtig: Wenn SHOW COLUMNS fuer eine Tabelle fehlschlaegt (gibt es nicht),
# darf nicht blind ein ALTER darauf abgesetzt werden.
pruefe('Tabelle nicht in der Auskunft -> kein ALTER darauf',
       fehlende_spalten({'t1': {'a', 'b'}}, ERWARTET) == [],
       fehlende_spalten({'t1': {'a', 'b'}}, ERWARTET))
pruefe('gar keine Auskunft -> gar nichts',
       fehlende_spalten({}, ERWARTET) == [],
       fehlende_spalten({}, ERWARTET))

print('\n=== Die echte Spaltenliste ===')
pruefe('jede Angabe ist ein Dreier aus Text',
       all(isinstance(z, tuple) and len(z) == 3 and all(isinstance(x, str) for x in z)
           for z in NACHGERUESTETE_SPALTEN),
       NACHGERUESTETE_SPALTEN)
paare = [(t, s) for t, s, _a in NACHGERUESTETE_SPALTEN]
pruefe('keine Spalte steht doppelt drin',
       len(paare) == len(set(paare)),
       [p for p in paare if paare.count(p) > 1])
pruefe('die Spalten, die frueher siebenmal einzeln kamen, sind dabei',
       {('planner_posts', 'linkedin_posted'),
        ('planner_posts', 'post_scheduled_at'),
        ('planner_posts', 'video_nc_path'),
        ('planner_posts', 'buffer_update_id')} <= set(paare),
       sorted(paare))
pruefe('keine Tabellen- oder Spaltennamen mit Sonderzeichen',
       all(t.replace('_', '').isalnum() and s.replace('_', '').isalnum()
           for t, s, _a in NACHGERUESTETE_SPALTEN))

print('\n=== Einmal pro Prozess ===')
_SCHEMA_GEPRUEFT.clear()
laeufe = []


@einmal_pro_prozess
def _pflege_a():
    laeufe.append('a')
    return 'fertig'


pruefe('erster Aufruf arbeitet', _pflege_a() == 'fertig' and laeufe == ['a'], laeufe)
_pflege_a()
_pflege_a()
_pflege_a()
pruefe('drei weitere Aufrufe arbeiten NICHT mehr', laeufe == ['a'], laeufe)

print('\n=== Jede Funktion hat ihr eigenes Gedaechtnis ===')
laeufe_b = []


@einmal_pro_prozess
def _pflege_b():
    laeufe_b.append('b')


_pflege_b()
pruefe('die zweite Funktion laeuft trotzdem', laeufe_b == ['b'], laeufe_b)
pruefe('und die erste bleibt still', laeufe == ['a'], laeufe)

print('\n=== Ein Fehlschlag gilt NICHT als erledigt ===')
# Das ist der heikle Teil: Waere die Datenbank beim ersten Aufruf kurz weg und
# wir merkten uns "erledigt", liefe die Schema-Pflege in diesem Prozess nie
# wieder - und eine fehlende Spalte bliebe fuer immer fehlend.
versuche = []


@einmal_pro_prozess
def _pflege_c():
    versuche.append(len(versuche))
    if len(versuche) < 3:
        raise RuntimeError('Datenbank nicht erreichbar')
    return 'endlich'


for _ in range(2):
    try:
        _pflege_c()
    except RuntimeError:
        pass
pruefe('nach zwei Fehlschlaegen wurde zweimal versucht', len(versuche) == 2, versuche)
pruefe('der dritte Versuch gelingt', _pflege_c() == 'endlich', versuche)
_pflege_c()
_pflege_c()
pruefe('danach ist Ruhe', len(versuche) == 3, versuche)

print('\n=== Der Name bleibt erhalten ===')
pruefe('functools.wraps ist gesetzt (Django und Logs brauchen den Namen)',
       _pflege_a.__name__ == '_pflege_a', _pflege_a.__name__)
pruefe('die ungepufferte Fassung ist erreichbar',
       callable(getattr(_pflege_a, 'ungepuffert', None)))

print('\n%d ok, %d fehlgeschlagen' % (gut, schlecht))
sys.exit(1 if schlecht else 0)
