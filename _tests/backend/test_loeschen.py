"""Löschen: Sagt die App die Wahrheit darüber, was passiert ist?

Das ist der Fehler, der im September 2026 dreimal an verschiedenen Knöpfen
auftrat: Die Ansicht löschte, sah nicht hin, und meldete Erfolg. Die Kachel
verschwand, die Datei blieb in Nextcloud liegen - und war beim nächsten Laden
wieder da, oder schlimmer: Der Datenbankeintrag war weg und die Datei über die
App nicht mehr erreichbar.

Jeder Test hier prüft beide Richtungen. Nur zu prüfen, dass Löschen gelingt,
hätte den Fehler nie gefunden - der trat ja genau dann auf, wenn es NICHT
gelang.
"""
from django.db import connection

from .basis import BackendTest

ORDNER = 'Marketing & Design/Octotrial_Assets/Studio_Work/Output/Images'
PFAD = ORDNER + '/bericht.png'
GESPERRT = 'The file is locked in Nextcloud (423)'


class AusgabeLoeschen(BackendTest):
    """POST /library/studio/api/output/delete/"""

    URL = '/library/studio/api/output/delete/'

    def _eintraege_anlegen(self, nc_path=PFAD):
        with connection.cursor() as c:
            c.execute("INSERT INTO studio_images (nc_path, title) VALUES (%s, %s)",
                      [nc_path, 'Bericht'])
            c.execute("INSERT INTO media_library_items (nc_path, title) VALUES (%s, %s)",
                      [nc_path, 'Bericht'])

    def test_gelungenes_loeschen_raeumt_auch_die_datenbank(self):
        self._eintraege_anlegen()
        with self.wolke() as w:
            w.dateien[PFAD] = b'bild'
            antwort = self.client.post(self.URL, {'nc_path': PFAD})
        self.assertEqual(antwort.status_code, 200)
        self.assertTrue(antwort.json()['ok'])
        self.assertNotIn(PFAD, w.dateien)
        self.assertEqual(
            0, self.zahl("SELECT COUNT(*) FROM studio_images WHERE nc_path=%s", PFAD))
        self.assertEqual(
            0, self.zahl("SELECT COUNT(*) FROM media_library_items WHERE nc_path=%s", PFAD))

    def test_abgelehntes_loeschen_meldet_den_grund(self):
        with self.wolke() as w:
            w.dateien[PFAD] = b'bild'
            w.loeschen_scheitert_mit = GESPERRT
            antwort = self.client.post(self.URL, {'nc_path': PFAD})
        self.assertEqual(antwort.status_code, 502)
        daten = antwort.json()
        self.assertFalse(daten['ok'])
        self.assertIn('423', daten['error'])

    def test_abgelehntes_loeschen_laesst_die_datenbank_in_ruhe(self):
        # Der eigentliche Schaden: Die Zeile war weg, die Datei noch da.
        self._eintraege_anlegen()
        with self.wolke() as w:
            w.dateien[PFAD] = b'bild'
            w.loeschen_scheitert_mit = GESPERRT
            self.client.post(self.URL, {'nc_path': PFAD})
        self.assertEqual(
            1, self.zahl("SELECT COUNT(*) FROM studio_images WHERE nc_path=%s", PFAD))
        self.assertEqual(
            1, self.zahl("SELECT COUNT(*) FROM media_library_items WHERE nc_path=%s", PFAD))

    def test_pfad_ausserhalb_der_app_ordner_wird_abgelehnt(self):
        with self.wolke() as w:
            antwort = self.client.post(self.URL, {'nc_path': 'Privat/Steuern/2025.pdf'})
        self.assertEqual(antwort.status_code, 400)
        self.assertEqual([], w.geloescht)

    def test_pfadwechsel_nach_oben_wird_abgelehnt(self):
        with self.wolke() as w:
            antwort = self.client.post(
                self.URL, {'nc_path': 'Marketing & Design/../../etc/passwd'})
        self.assertEqual(antwort.status_code, 400)
        self.assertEqual([], w.geloescht)

    def test_doppelpunkt_im_dateinamen_ist_erlaubt(self):
        # Gegenprobe zum vorigen: ".." als eigener Pfadteil ist verboten,
        # zwei Punkte IM Namen sind harmlos und dürfen nicht mitverboten werden.
        pfad = ORDNER + '/bericht..png'
        with self.wolke() as w:
            w.dateien[pfad] = b'x'
            antwort = self.client.post(self.URL, {'nc_path': pfad})
        self.assertEqual(antwort.status_code, 200)

    def test_get_statt_post_wird_abgelehnt(self):
        self.assertEqual(405, self.client.get(self.URL).status_code)

    def test_ohne_anmeldung_kein_loeschen(self):
        self.client.logout()
        with self.wolke() as w:
            antwort = self.client.post(self.URL, {'nc_path': PFAD})
        self.assertIn(antwort.status_code, (302, 403))
        self.assertEqual([], w.geloescht)

    def test_vorschaudatei_wird_mitgeloescht(self):
        with self.wolke() as w:
            w.dateien[PFAD] = b'bild'
            w.dateien[ORDNER + '/bericht_preview.png'] = b'klein'
            self.client.post(self.URL, {'nc_path': PFAD})
        self.assertIn(ORDNER + '/bericht_preview.png', w.geloescht)

    def test_fehlende_vorschaudatei_macht_die_loeschung_nicht_ungueltig(self):
        with self.wolke() as w:
            w.dateien[PFAD] = b'bild'      # ohne _preview
            antwort = self.client.post(self.URL, {'nc_path': PFAD})
        self.assertEqual(antwort.status_code, 200)


class BibliotheksbildLoeschen(BackendTest):
    """POST /library/delete/<id>/ - hier war der Schaden am größten: Die
    Datenbankzeile fiel, die Datei blieb, und damit war sie über die App
    überhaupt nicht mehr erreichbar."""

    def _bild_anlegen(self):
        with connection.cursor() as c:
            c.execute("INSERT INTO media_library_items (nc_path, title) VALUES (%s, %s)",
                      [PFAD, 'Bericht'])
            c.execute("SELECT LAST_INSERT_ID()")
            return c.fetchone()[0]

    def _url(self, item_id):
        return '/library/delete/%d/' % item_id

    def test_gelingt_dann_ist_die_zeile_weg(self):
        nr = self._bild_anlegen()
        with self.wolke() as w:
            w.dateien[PFAD] = b'bild'
            antwort = self.client.post(self._url(nr),
                                       HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(antwort.status_code, 200)
        self.assertTrue(antwort.json()['ok'])
        self.assertEqual(0, self.zahl(
            "SELECT COUNT(*) FROM media_library_items WHERE id=%s", nr))

    def test_scheitert_dann_bleibt_die_zeile(self):
        nr = self._bild_anlegen()
        with self.wolke() as w:
            w.dateien[PFAD] = b'bild'
            w.loeschen_scheitert_mit = GESPERRT
            antwort = self.client.post(self._url(nr),
                                       HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(antwort.status_code, 502)
        self.assertIn('423', antwort.json()['error'])
        self.assertEqual(1, self.zahl(
            "SELECT COUNT(*) FROM media_library_items WHERE id=%s", nr))

    def test_ohne_ajax_bleibt_die_zeile_ebenfalls(self):
        # Derselbe Fall aus dem normalen Formular heraus: Weiterleitung statt
        # JSON, aber die Zeile darf genauso wenig verschwinden.
        nr = self._bild_anlegen()
        with self.wolke() as w:
            w.dateien[PFAD] = b'bild'
            w.loeschen_scheitert_mit = GESPERRT
            antwort = self.client.post(self._url(nr))
        self.assertEqual(antwort.status_code, 302)
        self.assertEqual(1, self.zahl(
            "SELECT COUNT(*) FROM media_library_items WHERE id=%s", nr))


class UploadLoeschen(BackendTest):
    """POST /library/studio/upload/delete/ - darf nur im Upload-Ordner wirken."""

    URL = '/library/studio/upload/delete/'
    UPLOAD = 'Marketing & Design/Octotrial_Assets/Studio_Work/Upload/roh.png'

    def test_gelingt(self):
        with self.wolke() as w:
            w.dateien[self.UPLOAD] = b'x'
            antwort = self.client.post(self.URL, {'nc_path': self.UPLOAD})
        self.assertEqual(antwort.status_code, 200)
        self.assertTrue(antwort.json()['ok'])

    def test_scheitert_mit_grund(self):
        with self.wolke() as w:
            w.dateien[self.UPLOAD] = b'x'
            w.loeschen_scheitert_mit = GESPERRT
            antwort = self.client.post(self.URL, {'nc_path': self.UPLOAD})
        self.assertEqual(antwort.status_code, 502)
        self.assertIn('423', antwort.json()['error'])

    def test_ausserhalb_des_upload_ordners_wird_abgelehnt(self):
        # Eine Ausgabe ist eine App-Datei, aber NICHT über diesen Knopf löschbar.
        with self.wolke() as w:
            antwort = self.client.post(self.URL, {'nc_path': PFAD})
        self.assertEqual(antwort.status_code, 400)
        self.assertEqual([], w.geloescht)
