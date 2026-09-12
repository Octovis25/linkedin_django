"""Medien-Auslieferung: Proxy, Vorschaubilder, Ausgabenliste.

Der Proxy war für Bilder gebaut und wurde für Video mitbenutzt. Was dabei
schiefging, sieht man erst an der echten Antwort - am Medientyp, am Statuscode,
an den Kopfzeilen. Genau die prüft dieser Teil, durch den vollen Django-Weg
hindurch.
"""
import os

from django.db import connection
from django.test import override_settings

from .basis import BackendTest

ORDNER = 'Marketing & Design/Octotrial_Assets/Studio_Work/Output'
VIDEO = ORDNER + '/Videos/clip.webm'
BILD = ORDNER + '/Images/bericht.png'

# Ein winziges, gültiges PNG (1x1, durchsichtig) - Pillow kann es lesen.
PNG_1x1 = bytes.fromhex(
    '89504e470d0a1a0a0000000d4948445200000001000000010806000000'
    '1f15c4890000000d49444154789c6360606060000000050001a5f64540'
    '0000000049454e44ae426082')


class MedienProxy(BackendTest):
    """GET /library/studio/nc-image/?p=..."""

    URL = '/library/studio/nc-image/'

    def test_video_bekommt_einen_video_medientyp(self):
        # DER Fehler: Nextcloud meldet für .webm oft application/octet-stream,
        # und damit spielt ein <video> in Chrome gar nicht erst an.
        with self.wolke() as w:
            w.dateien[VIDEO] = b'\x1a\x45\xdf\xa3' + b'x' * 200
            w.typen[VIDEO] = 'application/octet-stream'
            antwort = self.client.get(self.URL, {'p': VIDEO})
        self.assertEqual(antwort.status_code, 200)
        self.assertEqual('video/webm', antwort['Content-Type'])

    def test_auch_eine_falsche_serverangabe_setzt_sich_nicht_durch(self):
        with self.wolke() as w:
            w.dateien[VIDEO] = b'x' * 50
            w.typen[VIDEO] = 'image/png'
            antwort = self.client.get(self.URL, {'p': VIDEO})
        self.assertEqual('video/webm', antwort['Content-Type'])

    def test_bereichsanfrage_wird_mit_206_beantwortet(self):
        # Ohne 206 lässt sich im Video nicht springen, und größere Dateien
        # starten in Chrome oft überhaupt nicht.
        with self.wolke() as w:
            w.dateien[VIDEO] = bytes(range(256)) * 4      # 1024 Bytes
            antwort = self.client.get(self.URL, {'p': VIDEO}, HTTP_RANGE='bytes=100-199')
        self.assertEqual(antwort.status_code, 206)
        self.assertEqual('bytes 100-199/1024', antwort['Content-Range'])
        self.assertEqual('bytes', antwort['Accept-Ranges'])
        self.assertEqual(100, len(b''.join(antwort.streaming_content)))

    def test_ohne_bereichsanfrage_kommt_die_ganze_datei(self):
        with self.wolke() as w:
            w.dateien[VIDEO] = b'y' * 512
            antwort = self.client.get(self.URL, {'p': VIDEO})
        self.assertEqual(antwort.status_code, 200)
        self.assertEqual(512, len(b''.join(antwort.streaming_content)))
        self.assertEqual('bytes', antwort['Accept-Ranges'])

    def test_pfad_ausserhalb_der_app_ordner_wird_nicht_ausgeliefert(self):
        # Vorher ließ sich mit ?p= jede Datei des Nextcloud-Kontos lesen.
        with self.wolke() as w:
            w.dateien['Privat/Steuern/2025.pdf'] = b'geheim'
            antwort = self.client.get(self.URL, {'p': 'Privat/Steuern/2025.pdf'})
        self.assertEqual(antwort.status_code, 404)

    def test_nicht_vorhandene_datei_gibt_404(self):
        with self.wolke():
            self.assertEqual(404, self.client.get(self.URL, {'p': BILD}).status_code)

    def test_ohne_pfad_gibt_404(self):
        with self.wolke():
            self.assertEqual(404, self.client.get(self.URL).status_code)

    def test_svg_wird_nicht_als_png_ausgeliefert(self):
        pfad = ORDNER + '/Images/logo.svg'
        with self.wolke() as w:
            w.dateien[pfad] = b'<svg/>'
            w.typen[pfad] = 'image/png'
            antwort = self.client.get(self.URL, {'p': pfad})
        self.assertEqual('image/svg+xml', antwort['Content-Type'])

    def test_bilder_werden_weiterhin_nicht_zwischengespeichert(self):
        # Ein Bild kann sich unter demselben Pfad ändern (bearbeiten und neu
        # speichern) - das darf nie aus dem Cache kommen.
        with self.wolke() as w:
            w.dateien[BILD] = PNG_1x1
            antwort = self.client.get(self.URL, {'p': BILD})
        self.assertIn('no-store', antwort['Cache-Control'])

    def test_ohne_anmeldung_kein_zugriff(self):
        self.client.logout()
        with self.wolke() as w:
            w.dateien[BILD] = PNG_1x1
            antwort = self.client.get(self.URL, {'p': BILD})
        self.assertIn(antwort.status_code, (302, 403))


class Vorschaubilder(BackendTest):
    """GET /library/studio/thumb/?p=...&t=...&w=240"""

    URL = '/library/studio/thumb/'

    def test_ein_grosses_bild_wird_klein(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest('Pillow nicht installiert')
        import io as _io
        gross = Image.new('RGB', (1080, 1080), (10, 20, 30))
        puffer = _io.BytesIO()
        gross.save(puffer, 'PNG')
        rohdaten = puffer.getvalue()

        with self.wolke() as w:
            w.dateien[BILD] = rohdaten
            antwort = self.client.get(self.URL, {'p': BILD, 't': '1700000000', 'w': '240'})
        self.assertEqual(antwort.status_code, 200)
        klein = b''.join(antwort.streaming_content)
        self.assertLess(len(klein), len(rohdaten))
        self.assertEqual((240, 240), Image.open(_io.BytesIO(klein)).size)

    def test_die_adresse_darf_dauerhaft_zwischengespeichert_werden(self):
        # Weil der Änderungszeitpunkt in der Adresse steht, meint dieselbe
        # Adresse immer dasselbe Bild.
        with self.wolke() as w:
            w.dateien[BILD] = PNG_1x1
            antwort = self.client.get(self.URL, {'p': BILD, 't': '1700000000'})
        self.assertEqual(antwort.status_code, 200)
        self.assertIn('immutable', antwort['Cache-Control'])

    def test_beim_zweiten_mal_wird_nextcloud_nicht_mehr_gefragt(self):
        with self.wolke() as w:
            w.dateien[BILD] = PNG_1x1
            self.client.get(self.URL, {'p': BILD, 't': '1700000042'})
            w.holen_scheitert = True     # ab jetzt liefert die Wolke nichts mehr
            antwort = self.client.get(self.URL, {'p': BILD, 't': '1700000042'})
        self.assertEqual(antwort.status_code, 200)

    def test_ein_geaendertes_bild_bekommt_ein_neues_vorschaubild(self):
        # Der ganze Zweck des Zeitstempels im Schlüssel.
        with self.wolke() as w:
            w.dateien[BILD] = PNG_1x1
            self.client.get(self.URL, {'p': BILD, 't': '1700000000'})
            w.holen_scheitert = True
            antwort = self.client.get(self.URL, {'p': BILD, 't': '1700000999'})
        self.assertEqual(404, antwort.status_code)

    def test_video_geht_unveraendert_den_normalen_weg(self):
        with self.wolke() as w:
            w.dateien[VIDEO] = b'z' * 100
            antwort = self.client.get(self.URL, {'p': VIDEO, 't': '1'})
        self.assertEqual(antwort.status_code, 200)
        self.assertEqual('video/webm', antwort['Content-Type'])

    def test_pfad_ausserhalb_der_app_ordner_wird_abgelehnt(self):
        with self.wolke() as w:
            w.dateien['Privat/x.png'] = PNG_1x1
            self.assertEqual(404, self.client.get(
                self.URL, {'p': 'Privat/x.png', 't': '1'}).status_code)


class Ausgabenliste(BackendTest):
    """GET /library/studio/api/outputs/?kind=Images

    Hängt eine Ausgabe an einem Post, liegt ihre Datei im Planner-Ordner, nicht
    mehr im Studio-Ordner. Die Liste muss beide lesen - sonst ist jede Ausgabe,
    die je an einem Beitrag hing, aus dem Medien-Bereich verschwunden.
    """

    URL = '/library/studio/api/outputs/'

    def test_unbekannte_art_wird_abgelehnt(self):
        antwort = self.client.get(self.URL, {'kind': 'Poster'})
        self.assertEqual(antwort.status_code, 400)
        self.assertFalse(antwort.json()['ok'])

    def test_die_drei_bekannten_arten_antworten(self):
        from unittest import mock
        with mock.patch('media_library.views._nc_dateien', return_value=[]):
            for art in ('Images', 'GIFs', 'Videos'):
                antwort = self.client.get(self.URL, {'kind': art})
                self.assertEqual(antwort.status_code, 200, art)
                self.assertTrue(antwort.json()['ok'], art)

    def test_beide_ordner_werden_gelesen_und_zusammengefuehrt(self):
        from unittest import mock

        def gelesen(ordner, endungen=None):
            if ordner.startswith('Marketing & Design/LinkedIn/Planner'):
                return [{'name': 'b.png', 'title': 'b', 'nc_path': 'planner/b.png',
                         'url': '/u/b', 'mtime': 200}]
            return [{'name': 'a.png', 'title': 'a', 'nc_path': 'studio/a.png',
                     'url': '/u/a', 'mtime': 100},
                    {'name': 'b.png', 'title': 'b', 'nc_path': 'studio/b.png',
                     'url': '/u/b', 'mtime': 50}]

        with mock.patch('media_library.views._nc_dateien', side_effect=gelesen):
            daten = self.client.get(self.URL, {'kind': 'Images'}).json()

        namen = [x['name'] for x in daten['items']]
        self.assertEqual(['b.png', 'a.png'], namen)          # neueste zuerst
        b = [x for x in daten['items'] if x['name'] == 'b.png'][0]
        self.assertEqual('planner/b.png', b['nc_path'])       # die verschobene gewinnt
        self.assertTrue(b['am_post'])
        a = [x for x in daten['items'] if x['name'] == 'a.png'][0]
        self.assertFalse(a['am_post'])

    def test_ohne_anmeldung_keine_liste(self):
        self.client.logout()
        antwort = self.client.get(self.URL, {'kind': 'Images'})
        self.assertIn(antwort.status_code, (302, 403))
