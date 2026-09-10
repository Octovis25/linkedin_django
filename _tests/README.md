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
- `index.html` = `studio.html` ohne Django-Tags (Post-Block raus,
  `{% static %}` → `./`, Import-Map raus, `studio-config` als echtes JSON)

## Laufen lassen

    node run.mjs

Wichtig: In diesem Container ist das alte Headless-Chrome entfernt. Playwright
muss deshalb auf die Headless-Shell zeigen:
`/opt/pw-browsers/chromium_headless_shell-1194/chrome-linux/headless_shell`

## Was geprüft wird (Stand 2026-09-10, 16 Tests)

Start ohne Fehlerbanner, Modus-Rail, Bild auf dem Canvas, Image-Panel wird mit
Bild aktiv, Erase startet auf „Klick-Fläche", Klick macht die Fläche wirklich
transparent (Pixel-Alpha wird gemessen), der Rest bleibt stehen, Wechsel auf
Pinsel schaltet das Werkzeug um, Select blendet die richtigen Zeilen ein,
Rechteck-Ebene wird aktiv, Ziehen erzeugt eine Markierung, Löschen macht den
Bereich transparent.
