"""Test fuer die Medien-Auslieferung (studio_nc_image_proxy in media_library/views.py).

Django laeuft in diesem Pruefstand nicht, und es muss auch nicht: Die Stellen,
an denen es schiefgeht, sind reine Rechnerei -

  * welcher Medientyp zu einer Datei gehoert (ein .webm als
    application/octet-stream spielt in Chrome gar nicht erst an),
  * welches Byte-Stueck eine Range-Anfrage meint (ohne das kein Springen im
    Video, und groessere Dateien starten oft ueberhaupt nicht),
  * wie gross ein Vorschaubild wird und unter welchem Schluessel es liegt
    (ein Schluessel ohne Aenderungszeitpunkt zeigt fuer immer das alte Bild),
  * wie die beiden Fundorte einer Ausgabe zusammengefuehrt werden (eine an
    einen Post gehaengte Datei liegt im Planner-Ordner, nicht mehr im
    Studio-Ordner - wer nur einen liest, verliert sie).

Alles wird aus views.py herausgeschnitten und geprueft - die echten Zeilen,
keine Abschrift.

    python _tests/proxy_test.py
"""
import ast
import os
import sys

HIER = os.path.dirname(os.path.abspath(__file__))
KANDIDATEN = [
    os.path.join(HIER, '..', 'media_library', 'views.py'),
    os.path.join(HIER, 'views.py'),
]

datei = next((p for p in KANDIDATEN if os.path.exists(p)), None)
if not datei:
    print('media_library/views.py nicht gefunden. Gesucht in:')
    for p in KANDIDATEN:
        print('  ' + os.path.abspath(p))
    sys.exit(2)

quelle = open(datei, encoding='utf-8').read()
baum = ast.parse(quelle)

# Nur die beiden Funktionen und die Tabelle herausloesen - der Rest von views.py
# braucht Django und laesst sich hier nicht laden.
GEBRAUCHT = {'medientyp', 'bereich_lesen', 'vorschau_groesse', 'vorschau_schluessel',
             'ausgaben_zusammenfuehren'}
TABELLEN = {'MEDIENTYPEN', 'BEWEGTBILD', 'VORSCHAU_FAEHIG', 'VORSCHAU_BREITEN'}
teile = []
for knoten in baum.body:
    if isinstance(knoten, ast.FunctionDef) and knoten.name in GEBRAUCHT:
        teile.append(ast.get_source_segment(quelle, knoten))
    elif isinstance(knoten, ast.Assign):
        for ziel in knoten.targets:
            if isinstance(ziel, ast.Name) and ziel.id in TABELLEN:
                teile.append(ast.get_source_segment(quelle, knoten))

fehlend = GEBRAUCHT - {k.name for k in ast.walk(baum)
                       if isinstance(k, ast.FunctionDef) and k.name in GEBRAUCHT}
if fehlend:
    print('In views.py fehlen: ' + ', '.join(sorted(fehlend)))
    print('Der Proxy wurde umgebaut - diesen Test nachziehen.')
    sys.exit(2)

raum = {'os': os}
exec('\n\n'.join(teile), raum)
medientyp = raum['medientyp']
bereich_lesen = raum['bereich_lesen']
vorschau_groesse = raum['vorschau_groesse']
vorschau_schluessel = raum['vorschau_schluessel']
VORSCHAU_FAEHIG = raum['VORSCHAU_FAEHIG']
VORSCHAU_BREITEN = raum['VORSCHAU_BREITEN']
MEDIENTYPEN = raum['MEDIENTYPEN']
ausgaben_zusammenfuehren = raum['ausgaben_zusammenfuehren']

gut = schlecht = 0


def pruefe(name, bedingung, zusatz=''):
    global gut, schlecht
    if bedingung:
        gut += 1
        print('  ok   ' + name)
    else:
        schlecht += 1
        print('  FEHL ' + name + ('  -> ' + str(zusatz) if zusatz else ''))


print('\n=== Medientyp: die Endung entscheidet ===')
FAELLE = [
    ('clip.webm', '', 'video/webm'),
    ('clip.WEBM', '', 'video/webm'),
    ('clip.mp4', '', 'video/mp4'),
    ('clip.mov', '', 'video/quicktime'),
    ('bild.png', '', 'image/png'),
    ('bild.jpg', '', 'image/jpeg'),
    ('bild.jpeg', '', 'image/jpeg'),
    ('logo.svg', '', 'image/svg+xml'),
    ('bewegt.gif', '', 'image/gif'),
]
for pfad, server, erwartet in FAELLE:
    ist = medientyp('Marketing & Design/x/' + pfad, server)
    pruefe('%-14s -> %s' % (pfad, erwartet), ist == erwartet, ist)

print('\n=== Medientyp: die Serverangabe darf nicht schaden ===')
pruefe('octet-stream ueberschreibt .webm NICHT',
       medientyp('a/clip.webm', 'application/octet-stream') == 'video/webm',
       medientyp('a/clip.webm', 'application/octet-stream'))
pruefe('auch image/png ueberschreibt .webm nicht',
       medientyp('a/clip.webm', 'image/png') == 'video/webm',
       medientyp('a/clip.webm', 'image/png'))
pruefe('.svg wird nie als image/png ausgeliefert',
       medientyp('a/logo.svg', 'image/png') == 'image/svg+xml',
       medientyp('a/logo.svg', 'image/png'))
pruefe('unbekannte Endung nimmt die Serverangabe',
       medientyp('a/datei.xyz', 'text/plain') == 'text/plain',
       medientyp('a/datei.xyz', 'text/plain'))
pruefe('unbekannte Endung ohne Serverangabe -> octet-stream',
       medientyp('a/datei.xyz', '') == 'application/octet-stream',
       medientyp('a/datei.xyz', ''))
pruefe('Zusatz im Servertyp stoert nicht',
       medientyp('a/datei.xyz', 'text/plain; charset=utf-8') == 'text/plain',
       medientyp('a/datei.xyz', 'text/plain; charset=utf-8'))
pruefe('ohne Endung und ohne Angabe -> octet-stream',
       medientyp('a/datei', '') == 'application/octet-stream',
       medientyp('a/datei', ''))

print('\n=== Range: was der Browser wirklich schickt ===')
G = 1000
BEREICHE = [
    ('bytes=0-',       (0, 999),   'ganze Datei, so faengt jedes Video an'),
    ('bytes=0-499',    (0, 499),   'erstes Stueck'),
    ('bytes=500-999',  (500, 999), 'letztes Stueck'),
    ('bytes=500-',     (500, 999), 'ab der Mitte bis zum Ende'),
    ('bytes=-500',     (500, 999), 'die letzten 500 Bytes'),
    ('bytes=0-99999',  (0, 999),   'zu weit gefordert wird gekuerzt'),
    ('bytes = 0-499',  (0, 499),   'Leerzeichen stoeren nicht'),
]
for kopf, erwartet, warum in BEREICHE:
    ist = bereich_lesen(kopf, G)
    pruefe("%-16s -> %-11s (%s)" % (kopf, erwartet, warum), ist == erwartet, ist)

print('\n=== Range: Unsinn wird abgelehnt, nicht falsch geraten ===')
UNSINN = [
    ('', 'gar keine Kopfzeile'),
    (None, 'None'),
    ('items=0-10', 'falsche Einheit'),
    ('bytes=abc-def', 'keine Zahlen'),
    ('bytes=500-100', 'Ende vor Anfang'),
    ('bytes=0-10,20-30', 'mehrere Bereiche - koennen wir nicht'),
    ('bytes=-0', 'letzte 0 Bytes'),
    ('bytes=', 'leer'),
    ('bytes=-', 'nur der Strich'),
]
for kopf, warum in UNSINN:
    ist = bereich_lesen(kopf, G)
    pruefe('%-18s -> None (%s)' % (repr(kopf), warum), ist is None, ist)

print('\n=== Range: hinter dem Dateiende gehoert 416 ===')
pruefe('Anfang = Dateigroesse ist unerfuellbar',
       bereich_lesen('bytes=1000-', G) == ('unerfuellbar', G),
       bereich_lesen('bytes=1000-', G))
pruefe('Anfang hinter dem Ende ist unerfuellbar',
       bereich_lesen('bytes=5000-6000', G) == ('unerfuellbar', G),
       bereich_lesen('bytes=5000-6000', G))
pruefe('letztes gueltiges Byte ist noch erfuellbar',
       bereich_lesen('bytes=999-', G) == (999, 999),
       bereich_lesen('bytes=999-', G))

print('\n=== Range: leere Datei ===')
pruefe('Groesse 0 liefert None statt eines kaputten Bereichs',
       bereich_lesen('bytes=0-', 0) is None, bereich_lesen('bytes=0-', 0))

print('\n=== Kein Stueck ist je laenger als die Datei ===')
schieflagen = []
for kopf in ['bytes=0-', 'bytes=0-499', 'bytes=500-', 'bytes=-500',
             'bytes=0-99999', 'bytes=999-', 'bytes=-99999']:
    b = bereich_lesen(kopf, G)
    if not b or b[0] == 'unerfuellbar':
        continue
    a, e = b
    if not (0 <= a <= e <= G - 1):
        schieflagen.append((kopf, b))
pruefe('jeder gelieferte Bereich liegt in der Datei',
       not schieflagen, schieflagen)


print('\n=== Vorschaubild: Groesse ===')
pruefe('1080 -> 240 quadratisch bleibt quadratisch',
       vorschau_groesse(1080, 1080, 240) == (240, 240),
       vorschau_groesse(1080, 1080, 240))
pruefe('1920x1080 behaelt das Seitenverhaeltnis',
       vorschau_groesse(1920, 1080, 240) == (240, 135),
       vorschau_groesse(1920, 1080, 240))
pruefe('1080x1920 hochkant ebenso',
       vorschau_groesse(1080, 1920, 240) == (240, 427),
       vorschau_groesse(1080, 1920, 240))
pruefe('kleineres Bild wird NICHT vergroessert',
       vorschau_groesse(80, 80, 240) is None,
       vorschau_groesse(80, 80, 240))
pruefe('genau die Zielbreite bleibt unveraendert',
       vorschau_groesse(240, 300, 240) is None,
       vorschau_groesse(240, 300, 240))
pruefe('ein Pixel breiter wird schon verkleinert',
       vorschau_groesse(241, 300, 240) == (240, 299),
       vorschau_groesse(241, 300, 240))
pruefe('extrem breites Bild behaelt mindestens 1 Pixel Hoehe',
       vorschau_groesse(10000, 3, 240) == (240, 1),
       vorschau_groesse(10000, 3, 240))
pruefe('Nullmasse liefern None statt eines Absturzes',
       vorschau_groesse(0, 100, 240) is None and vorschau_groesse(100, 0, 240) is None)
pruefe('None-Masse liefern None',
       vorschau_groesse(None, None, 240) is None)

print('\n=== Vorschaubild: nie hoeher aufgeloest als das Original ===')
schieflagen = []
for b, h in [(1080, 1080), (1920, 1080), (300, 2000), (241, 241), (5000, 5000)]:
    for ziel in VORSCHAU_BREITEN:
        m = vorschau_groesse(b, h, ziel)
        if m and (m[0] > b or m[1] > h):
            schieflagen.append((b, h, ziel, m))
pruefe('keine Verkleinerung ist groesser als ihr Original', not schieflagen, schieflagen)

print('\n=== Vorschaubild: Cache-Schluessel ===')
a = vorschau_schluessel('Marketing & Design/x/bild.png', 1700000000, 240)
b = vorschau_schluessel('Marketing & Design/x/bild.png', 1700000000, 240)
pruefe('gleiche Eingabe, gleicher Schluessel', a == b)
pruefe('anderer Aenderungszeitpunkt -> anderer Schluessel',
       a != vorschau_schluessel('Marketing & Design/x/bild.png', 1700000099, 240))
pruefe('andere Breite -> anderer Schluessel',
       a != vorschau_schluessel('Marketing & Design/x/bild.png', 1700000000, 480))
pruefe('anderer Pfad -> anderer Schluessel',
       a != vorschau_schluessel('Marketing & Design/x/anderes.png', 1700000000, 240))
pruefe('der Schluessel ist ein sicherer Dateiname',
       a.isalnum() and 20 <= len(a) <= 64, a)
pruefe('Umlaute und Leerzeichen im Pfad stoeren nicht',
       vorschau_schluessel('Marketing & Design/Ordner mit Umlaut aeoeue/bild.png', 1, 240).isalnum())

# Die Unterscheidbarkeit ist der ganze Zweck: Ohne den Aenderungszeitpunkt
# zeigte ein neu gespeichertes Bild fuer immer seine alte Vorschau.
print('\n=== Vorschaubild: nichts kollidiert ===')
schluessel = set()
for pfad in ['a/b.png', 'a/c.png', 'a/b.jpg', 'b/a.png']:
    for stand in [0, 1700000000, 1700000001]:
        for breite in VORSCHAU_BREITEN:
            schluessel.add(vorschau_schluessel(pfad, stand, breite))
erwartet = 4 * 3 * len(VORSCHAU_BREITEN)
pruefe('%d verschiedene Eingaben -> %d verschiedene Schluessel' % (erwartet, erwartet),
       len(schluessel) == erwartet, len(schluessel))

print('\n=== Vorschaubild: welche Formate ueberhaupt ===')
pruefe('.png, .jpg, .webp, .gif werden verkleinert',
       {'.png', '.jpg', '.jpeg', '.webp', '.gif'} <= VORSCHAU_FAEHIG,
       sorted(VORSCHAU_FAEHIG))
pruefe('.svg wird NICHT verkleinert (Pillow liest es nicht)',
       '.svg' not in VORSCHAU_FAEHIG)
pruefe('Video wird NICHT verkleinert',
       not ({'.webm', '.mp4', '.mov'} & VORSCHAU_FAEHIG))
pruefe('jede Vorschau-Endung hat auch einen Medientyp',
       all(e in MEDIENTYPEN for e in VORSCHAU_FAEHIG),
       [e for e in VORSCHAU_FAEHIG if e not in MEDIENTYPEN])


print('\n=== Ausgaben: beide Fundorte zusammenfuehren ===')


def e(name, stand=0, ordner='studio'):
    return {'name': name, 'title': name.rsplit('.', 1)[0], 'mtime': stand,
            'nc_path': ordner + '/' + name}


# Der Normalfall: zwei im Studio-Ordner, eine davon inzwischen am Post.
zus = ausgaben_zusammenfuehren(
    [e('a.png', 300), e('b.png', 200)],
    [e('b.png', 250, 'planner')],
)
namen = [x['name'] for x in zus]
pruefe('jede Datei genau einmal', namen == ['a.png', 'b.png'], namen)
pruefe('die verschobene Fassung gewinnt',
       [x for x in zus if x['name'] == 'b.png'][0]['nc_path'].startswith('planner'),
       [x for x in zus if x['name'] == 'b.png'][0]['nc_path'])
pruefe('am Post wird als solches markiert',
       [x for x in zus if x['name'] == 'b.png'][0]['am_post'] is True)
pruefe('was nur im Studio liegt, ist nicht am Post',
       [x for x in zus if x['name'] == 'a.png'][0]['am_post'] is False)

print('\n=== Ausgaben: nichts geht verloren ===')
zus = ausgaben_zusammenfuehren([e('nur_studio.png')], [e('nur_planner.png', 1, 'planner')])
pruefe('beide Seiten kommen vor', len(zus) == 2, len(zus))
pruefe('nur der Planner-Ordner reicht auch',
       len(ausgaben_zusammenfuehren([], [e('x.png', 1, 'planner')])) == 1)
pruefe('nur der Studio-Ordner reicht auch',
       len(ausgaben_zusammenfuehren([e('x.png')], [])) == 1)
pruefe('beide leer ergibt leer', ausgaben_zusammenfuehren([], []) == [])

print('\n=== Ausgaben: Reihenfolge und Schreibweise ===')
zus = ausgaben_zusammenfuehren([e('alt.png', 100), e('neu.png', 900), e('mittel.png', 500)], [])
pruefe('neueste zuerst',
       [x['name'] for x in zus] == ['neu.png', 'mittel.png', 'alt.png'],
       [x['name'] for x in zus])
pruefe('fehlender Zeitstempel wirft nicht, sondern landet hinten',
       [x['name'] for x in ausgaben_zusammenfuehren(
           [{'name': 'ohne.png'}, e('mit.png', 5)], [])] == ['mit.png', 'ohne.png'])
pruefe('Gross- und Kleinschreibung gilt als dieselbe Datei',
       len(ausgaben_zusammenfuehren([e('Bild.PNG')], [e('bild.png', 1, 'planner')])) == 1)

# Die Eingabelisten duerfen nicht veraendert werden - sie kommen direkt aus den
# Ordnerabfragen und werden anderswo weiterverwendet.
print('\n=== Ausgaben: die Eingaben bleiben unberuehrt ===')
a_liste, p_liste = [e('x.png', 1)], [e('y.png', 2, 'planner')]
vorher = (str(a_liste), str(p_liste))
ausgaben_zusammenfuehren(a_liste, p_liste)
pruefe('kein am_post in die Eingabelisten geschrieben',
       (str(a_liste), str(p_liste)) == vorher)

print('\n%d ok, %d fehlgeschlagen' % (gut, schlecht))
sys.exit(1 if schlecht else 0)
