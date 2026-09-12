"""Test fuer die Anzeigenamen der Status.

Der Zustand heisst 'Review' - in der Datenbank, im Auswahlfeld und seit
September 2026 auch in der Menueleiste. Dort stand vorher 'In Progress', und im
Auswahlfeld suchte man diesen Namen vergeblich. Aufgeloest wurde es ueber den
Menuenamen, weil 'In Progress' wie ein zweites Wort fuer 'Draft' klingt.

Damit ist die Anzeige-Zuordnung STATUS_ANZEIGE heute LEER - jeder Status wird
unter seinem gespeicherten Namen gezeigt. Der Weg dorthin bleibt aber gebaut,
und dieser Test haelt fest, dass er richtig gebaut ist.

Dabei gibt es eine Falle, in die man genau einmal tritt:

    <option>Review</option>          <!-- ohne value -->

Ein <option> ohne value schickt seinen TEXT ab. Haette man hier nur das Wort
getauscht, stuende ab sofort 'In Progress' in der Datenbank - und jede Abfrage,
die nach 'Review' sucht, faende nichts mehr. Dieser Test passt darauf auf.

    python _tests/status_namen_test.py
"""
import ast
import os
import re
import sys

HIER = os.path.dirname(os.path.abspath(__file__))


def suche(*teile):
    kandidaten = [os.path.join(HIER, '..', *teile), os.path.join(HIER, teile[-1])]
    p = next((k for k in kandidaten if os.path.exists(k)), None)
    if not p:
        print('Nicht gefunden: ' + os.path.join(*teile))
        for k in kandidaten:
            print('  gesucht in ' + os.path.abspath(k))
        sys.exit(2)
    return open(p, encoding='utf-8').read()


quelle = suche('planner', 'views.py')
baum = ast.parse(quelle)
teile = []
for knoten in baum.body:
    if isinstance(knoten, ast.FunctionDef) and knoten.name == 'status_anzeige':
        teile.append(ast.get_source_segment(quelle, knoten))
    elif isinstance(knoten, ast.Assign):
        for ziel in knoten.targets:
            if isinstance(ziel, ast.Name) and ziel.id == 'STATUS_ANZEIGE':
                teile.append(ast.get_source_segment(quelle, knoten))
if len(teile) < 2:
    print('STATUS_ANZEIGE / status_anzeige fehlen in planner/views.py.')
    print('Die Anzeigenamen wurden umgebaut - diesen Test nachziehen.')
    sys.exit(2)

raum = {}
exec('\n\n'.join(teile), raum)
STATUS_ANZEIGE = raum['STATUS_ANZEIGE']
status_anzeige = raum['status_anzeige']

planner_html = suche('planner', 'templates', 'planner', 'planner.html')
liste_html = suche('planner', 'templates', 'planner', '_post_list.html')

gut = schlecht = 0


def pruefe(name, bedingung, zusatz=''):
    global gut, schlecht
    if bedingung:
        gut += 1
        print('  ok   ' + name)
    else:
        schlecht += 1
        print('  FEHL ' + name + ('  -> ' + str(zusatz) if zusatz else ''))


print('\n=== Die Zuordnung selbst ===')
pruefe('jeder Status wird unter seinem gespeicherten Namen gezeigt',
       all(status_anzeige(s) == s for s in
           ('Planned', 'Draft', 'Review', 'Ready', 'Scheduled', 'Posted', 'Archive')))
pruefe('ein unbekannter Status stuerzt nicht ab',
       status_anzeige('Voellig Neu') == 'Voellig Neu')
pruefe('die Zuordnung ist leer - es gibt derzeit nichts umzubenennen',
       STATUS_ANZEIGE == {}, STATUS_ANZEIGE)
# Die Zuordnung koennte morgen wieder gefuellt sein. Was dann gelten MUSS,
# pruefen die Abschnitte darunter - unabhaengig davon, was drinsteht.

OPTION = re.compile(r'<option([^>]*)>(.*?)</option>', re.S)


def optionen(text):
    """(Attribute, sichtbarer Text) je <option>."""
    return [(m.group(1), re.sub(r'\s+', ' ', m.group(2)).strip())
            for m in OPTION.finditer(text)]


print('\n=== Die Falle: <option> ohne value ===')
# Ein <option> ohne value schickt seinen Text ab. Steht dort ein Anzeigename,
# landet der in der Datenbank.
for name, inhalt in (('planner.html', planner_html), ('_post_list.html', liste_html)):
    schlimm = []
    for attribute, text in optionen(inhalt):
        if 'value=' in attribute:
            continue
        if text in STATUS_ANZEIGE.values():
            schlimm.append(text)
        # Auch die Vorlagen-Schleifen zaehlen: {{ s.label }} ohne value ist
        # derselbe Fehler, nur eine Ebene spaeter.
        if '.label' in text or 's.label' in text:
            schlimm.append(text)
    pruefe('%-16s kein Anzeigename ohne value' % name, not schlimm, schlimm)

print('\n=== Anzeigename und gespeicherter Wert gehoeren zusammen ===')
for name, inhalt in (('planner.html', planner_html), ('_post_list.html', liste_html)):
    falsch = []
    for attribute, text in optionen(inhalt):
        w = re.search(r'value="([^"]*)"', attribute)
        if not w:
            continue
        wert, sichtbar = w.group(1), text
        # Wo 'In Progress' steht, muss 'Review' (oder 'review') gespeichert werden.
        if sichtbar == 'In Progress' and wert.lower() != 'review':
            falsch.append((wert, sichtbar))
        # Und umgekehrt darf nie ein Anzeigename als Wert dienen.
        if wert in STATUS_ANZEIGE.values():
            falsch.append((wert, sichtbar))
    pruefe('%-16s Wert und Anzeige passen' % name, not falsch, falsch)

print('\n=== "Review" ist Wert UND Anzeige ===')
for name, inhalt in (('planner.html', planner_html), ('_post_list.html', liste_html)):
    werte = {re.search(r'value="([^"]*)"', a).group(1).lower()
             for a, _t in optionen(inhalt) if 'value="' in a}
    pruefe('%-16s "review" ist ein Wert' % name, 'review' in werte, sorted(werte))
    sichtbar = [t for _a, t in optionen(inhalt) if t == 'Review']
    pruefe('%-16s "Review" steht auch lesbar da' % name, bool(sichtbar), sichtbar)

print('\n=== Menueleiste und Auswahlfeld sagen dasselbe ===')
# Der Auslöser der ganzen Sache: Oben stand "In Progress", unten "Review".
leiste = suche('core', 'templates', 'core', 'base.html')
pruefe('die Leiste nennt den Reiter "Review"',
       re.search(r'/planner/pipeline/[^>]*>\s*Review\s*</a>', leiste) is not None)
pruefe('die Leiste sagt NICHT mehr "In Progress"',
       'In Progress' not in leiste)
pruefe('das Filter-Auswahlfeld nennt ihn genauso',
       re.search(r'<option value="review"[^>]*>\s*Review\s*</option>',
                 planner_html) is not None)

print('\n%d ok, %d fehlgeschlagen' % (gut, schlecht))
sys.exit(1 if schlecht else 0)
