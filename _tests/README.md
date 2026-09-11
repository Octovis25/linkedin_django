# Frontend-Test für das Image Studio

Django lässt sich in der Sandbox nicht starten, das Frontend aber schon.
Der Test rendert `studio.html` zu statischem HTML, legt die Module und Fabric
daneben, startet einen Mini-Webserver und fährt alles mit Playwright durch.
Kein Login, keine Datenbank, kein Nextcloud.

## Einrichten (einmalig)

    npm init -y
    npm i fabric@5.3.0
    npm i -D playwright@1.47.0

Dann `app/` anlegen mit:
- allen `.js` aus `media_library/static/media_library/studio/`
- `studio.css` aus demselben Ordner
- `fabric.min.js` aus `node_modules/fabric/dist/`
- `gif.js` und `gif.worker.js` aus `…/studio/vendor/` — **sowohl in `app/`
  als auch in `app/vendor/`**, sonst fällt der GIF-Export-Test aus
- `index.html` = `studio.html` ohne Django-Tags (Post-Block raus,
  `{% static %}` → `./`, Import-Map raus, `studio-config` als echtes JSON,
  `window.STUDIO_VENDOR = "./"`)

Wichtig beim `studio-config`: die Schlüssel unter `urls` müssen **genau so
heißen wie in `views.py`** (`save`, `saveVideoFile`, `ncImage`, …), nur auf
`/api/…` gelenkt. Sonst liest der Code eine undefinierte Adresse, `fetch`
holt die eigene Seite, und der Fehler bleibt unsichtbar. Abschnitt 16 des
Tests prüft genau das.

## Laufen lassen

    node run.mjs

Wichtig: In diesem Container ist das alte Headless-Chrome entfernt. Playwright
muss deshalb auf die Headless-Shell zeigen:
`/opt/pw-browsers/chromium_headless_shell-1194/chrome-linux/headless_shell`

## Was geprüft wird (Stand 2026-09-11, 189 Tests)

**Grundlagen (1–10):** Start ohne Fehlerbanner, Modus-Rail, Bild auf dem
Canvas, Image-Panel wird mit Bild aktiv, Erase startet auf „Klick-Fläche",
Klick macht die Fläche wirklich transparent (Pixel-Alpha wird gemessen),
Wechsel auf Pinsel schaltet das Werkzeug um, Rechteck-Auswahl, Leisten
zu- und aufklappen (auch der Klapp-Knopf selbst bleibt erreichbar),
Remove background inklusive Weißschutz, Pinselgröße, Strg+Mausrad-Zoom,
Hilfe-Knopf im Rail.

**Animation (11):** Start-Verzögerung gilt für Bewegung *und* Effekt;
Schleifen-Bewegungen ruhen vor ihrer Startzeit; drei gleiche Elemente mit
verschiedenen Startzeiten laufen versetzt statt im Gleichschritt.

**Video-Vorschau (12):** eine Kachel, deren Datei fehlt, graut aus statt ein
rotes Fehlerbanner zu werfen.

**Rundgang (13):** alle vier Modi, alle 16 Einfüge-Werkzeuge, Ebenenliste,
Kontextleiste, zehn Ausrichten-Aktionen, Duplizieren/Löschen/Undo/Redo,
Hintergrundfarben, Canvas-Format, alle drei Medien-Reiter, Speichern-Dialog,
Alles-leeren.

**Fehler statt Absturz (14):** absichtlich ausgelöste Fehler — Retusche auf
verunreinigtem Canvas, Bild verschwindet mitten im Ziehen, Badge ohne
Beschriftung, blockierter Browser-Speicher. Jeder muss als Meldung ankommen,
keiner als rotes Banner.

**Speichern und Wiederöffnen (15):** Canvas → JSON → leer → zurück. Geprüft
wird, dass Bewegung, Effekt, Effekt-Startzeit, Bildherkunft, Freistell-Merker,
Textblock-Überschrift und Checklisten-Zeilen die Runde überleben. Dazu:
unlesbarer Entwurf setzt den Überschreib-Schutz, ein unbekanntes Objekt wird
aussortiert ohne den Rest mitzureißen.

**Server-Adressen (16):** jede im Code benutzte `URLS.*` ist auch
konfiguriert.

**Export (17):** GIF und WebM werden erzeugt und enthalten wirklich Daten
(Größe und MIME-Typ werden geprüft). Der Video-Test wiederholt einmal, falls
MediaRecorder kopflos einen leeren Container liefert.

**Krankes Backend (18):** Speichern gegen 500, gegen HTML statt JSON
(abgelaufene Sitzung) und gegen 413. Jedes Mal: Misserfolg wird gemeldet, der
Nutzer bekommt Text, kein rotes Banner — und der nächste Versuch gelingt
wieder (kein hängendes „speichert gerade"-Flag).

## Nach jedem Abschnitt

Der Lauf prüft automatisch, ob seit dem letzten Abschnitt irgendein
JavaScript-Fehler aufgelaufen ist oder das rote Banner steht. Ein Test kann
also nicht grün sein, während die Seite darunter kracht.

## Was der Test NICHT abdeckt

Alles hinter Django: echtes Speichern nach Nextcloud, die Views selbst,
Rechte, Login, Datenbank. Der Prüfstand fährt nur das Frontend gegen einen
Attrappen-Server. Diesen Teil muss weiterhin ein Mensch gegen die laufende
Instanz testen.
