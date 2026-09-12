# Backend-Tests

Bis September 2026 hatte das Backend keinen einzigen Test. Die beiden großen
`views.py` sind zusammen über 270 KB und wurden ausschließlich von Hand geprüft
— während das Frontend längst 225 automatische Tests hatte. Die Fehler, die in
dieser Zeit aufgetreten sind, waren fast alle von einer Sorte:

> Die Ansicht tut etwas, sieht nicht hin, ob es geklappt hat, und meldet Erfolg.

Löschen, das nichts löschte. Ein Proxy, der Videos als Bilder auslieferte. Eine
Liste, die die Hälfte ihrer Einträge nicht fand. Keiner dieser Fälle lässt sich
durch Ausprobieren zuverlässig herstellen — man braucht eine Nextcloud, die sich
**auf Kommando weigert**. Genau das ist hier gebaut.

## Starten

```
python _tests/backend/lauf.py                 # alles
python _tests/backend/lauf.py test_loeschen   # nur ein Teil
```

Gebraucht wird eine MySQL- oder MariaDB-Datenbank, in die geschrieben werden
darf. Django legt sich daraus eine eigene Testdatenbank an (`test_<name>`) und
wirft sie am Ende weg. **Die echten Daten werden nicht angefasst**, und mit
Nextcloud spricht der Testlauf überhaupt nicht.

Abweichende Zugänge über Umgebungsvariablen: `PRUEF_DB_HOST`, `PRUEF_DB_PORT`,
`PRUEF_DB_USER`, `PRUEF_DB_PASS`, `PRUEF_DB`.

Ohne lokale Datenbank läuft das hier nicht. Die Tests in `_tests/*.py` eine
Ebene höher brauchen keine — die prüfen reine Rechenlogik und laufen überall.

## Was drin ist

| Datei | prüft |
|---|---|
| `test_loeschen.py` | Löschen von Ausgaben, Bibliotheksbildern, Uploads — beide Richtungen: gelingt und gelingt nicht |
| `test_medien.py` | Medien-Proxy (Medientyp, Bereichsanfragen, Pfadschranke), Vorschaubilder, Ausgabenliste |
| `test_schema.py` | Nachrüsten fehlender Spalten gegen eine echte Datenbank |

## Wie die Attrappe funktioniert

`basis.py` stellt `WolkeAttrappe` bereit: ein Nextcloud im Arbeitsspeicher.

```python
def test_abgelehntes_loeschen_laesst_die_datenbank_in_ruhe(self):
    with self.wolke() as w:
        w.dateien[PFAD] = b'bild'
        w.loeschen_scheitert_mit = 'The file is locked in Nextcloud (423)'
        self.client.post(self.URL, {'nc_path': PFAD})
    self.assertEqual(1, self.zahl(
        "SELECT COUNT(*) FROM studio_images WHERE nc_path=%s", PFAD))
```

Was sie kann:

- `w.dateien[pfad] = b'...'` — eine Datei hinlegen
- `w.typen[pfad] = '...'` — den Medientyp, den „Nextcloud" meldet (für `.webm`
  gern mal `application/octet-stream` — daran ist die Videowiedergabe gescheitert)
- `w.loeschen_scheitert_mit = 'Grund'` — jede Löschung schlägt fehl
- `w.holen_scheitert = True` — nichts lässt sich mehr herunterladen
- `w.geloescht` — Liste aller Löschaufträge, auch der gescheiterten

Die Bereichsanfragen (`Range`) beantwortet sie wie die echte Wolke mit 206 und
`Content-Range` — sonst ließe sich die Videoauslieferung nicht prüfen.

## Einen Test dazuschreiben

Eine Regel, und sie ist wichtiger als alles andere:

> **Prüfe beide Richtungen.** Dass etwas gelingt, wenn alles gutgeht, hätte
> keinen der Fehler dieser App gefunden — die traten ja genau dann auf, wenn
> etwas *nicht* gutging.

Und danach: **Nimm die Reparatur testweise zurück und sieh nach, ob der Test
anschlägt.** Ein Test, der auch ohne die Reparatur durchläuft, prüft nichts.
Bei den vier Reparaturen vom September 2026 wurde jede so gegengeprüft.

Gerüst für eine neue Datei:

```python
from .basis import BackendTest


class MeinEndpunkt(BackendTest):
    URL = '/library/…/'

    def test_normalfall(self):
        with self.wolke() as w:
            w.dateien['Marketing & Design/…/x.png'] = b'…'
            antwort = self.client.post(self.URL, {'…': '…'})
        self.assertEqual(200, antwort.status_code)

    def test_wenn_es_schiefgeht(self):
        with self.wolke() as w:
            w.loeschen_scheitert_mit = 'kaputt'
            antwort = self.client.post(self.URL, {'…': '…'})
        self.assertEqual(502, antwort.status_code)
        self.assertIn('kaputt', antwort.json()['error'])
```

`self.zahl("SELECT COUNT(*) …", wert)` und `self.zeile(…)` sind da, um ohne
Umstände in die Datenbank zu schauen.

## Zwei Fallen, in die schon getreten wurde

**Der Vorschau-Cache liegt auf der Platte** und überlebt den Testlauf. Zwei
Tests mit demselben Pfad und demselben Zeitstempel bekommen dasselbe
Vorschaubild — der zweite prüft dann das Ergebnis des ersten. `basis.py` räumt
ihn vor jedem Test weg; wer daran vorbei baut, sollte es wissen.

**`ALTER TABLE` lässt sich in MySQL nicht zurückrollen** — jede
Schema-Änderung schließt die laufende Transaktion implizit ab, und in einem
gewöhnlichen `TestCase` läuft danach nichts mehr. `test_schema.py` benutzt
darum `TransactionTestCase`.

## Was noch fehlt

Abgedeckt sind die Endpunkte, an denen im September 2026 Fehler steckten. Nicht
abgedeckt ist der Rest — Speichern von Bildern und Videos, die Vorlagen, der
ganze `planner` mit LinkedIn und Buffer. Das Gerüst steht; jeder weitere Test
ist jetzt eine halbe Stunde statt eines Tages.
