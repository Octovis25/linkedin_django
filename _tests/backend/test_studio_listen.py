"""Studio lists and re-saving: what the review of 27.09.2026 found.

  * The template list loaded every layout (canvas_json, base64 images and all)
    just to report THAT a template has one - and every tile then fetched the
    full template image.
  * The list of saved outputs parsed every layout in Python to look for the
    old "animType" key.
  * Saving a GIF or video again pulled it out of its library folder.
"""
import json
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection

from .basis import BackendTest as _Basis


class BackendTest(_Basis):
    """The views call the schema upkeep; its ALTERs would commit the test's
    transaction in MySQL. setUpClass has just built the schema, so mark it done."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from media_library import views
        views._SCHEMA_GEPRUEFT.update({'_ensure_table', '_ensure_studio_tables',
                                       '_ensure_video_template_table', '_ensure_brand_colors_table'})

VORLAGEN = 'Marketing & Design/LinkedIn/Studio/Templates'
GROSS = 'data:image/png;base64,' + 'A' * 200000   # a layout with an embedded image


def _layout(*objekte):
    return json.dumps({'version': '5.3.0', 'objects': list(objekte)})


class VorlagenListe(BackendTest):
    URL = '/library/studio/api/templates/'

    def _vorlage(self, titel, nc_path, canvas_json):
        with connection.cursor() as c:
            c.execute("INSERT INTO studio_templates (nc_path, title, width, height, canvas_json) "
                      "VALUES (%s, %s, 1080, 1080, %s)", [nc_path, titel, canvas_json])
            return c.lastrowid

    def test_meldet_das_layout_ohne_es_mitzuschicken(self):
        self._vorlage('Mit', VORLAGEN + '/mit.png', _layout({'type': 'image', 'src': GROSS}))
        self._vorlage('Ohne', VORLAGEN + '/ohne.png', None)
        antwort = self.client.get(self.URL)
        self.assertEqual(antwort.status_code, 200)
        # The answer stays small: none of the 200 KB layout travels along.
        self.assertLess(len(antwort.content), 5000)
        liste = {t['title']: t for t in antwort.json()['templates']}
        self.assertTrue(liste['Mit']['has_canvas'])
        self.assertFalse(liste['Ohne']['has_canvas'])

    def test_jede_kachel_bekommt_ein_vorschaubild(self):
        self._vorlage('Kachel', VORLAGEN + '/kachel.png', None)
        t = self.client.get(self.URL).json()['templates'][0]
        self.assertIn('/library/studio/thumb/?p=', t['thumb'])
        self.assertIn('&w=240', t['thumb'])
        # The full picture stays available for applying the template.
        self.assertTrue(t['url'].startswith('/library/studio/template/image/'))

    def test_neu_gespeichert_heisst_neue_vorschau_adresse(self):
        # Same file path, new content: the cached thumbnail must not stay.
        tid = self._vorlage('Stand', VORLAGEN + '/stand.png', _layout({'type': 'text', 'text': 'a'}))
        vorher = self.client.get(self.URL).json()['templates'][0]['thumb']
        with connection.cursor() as c:
            c.execute("UPDATE studio_templates SET canvas_json=%s WHERE id=%s",
                      [_layout({'type': 'text', 'text': 'b'}), tid])
        nachher = self.client.get(self.URL).json()['templates'][0]['thumb']
        self.assertNotEqual(vorher, nachher)

    def test_passive_vorlagen_fehlen(self):
        tid = self._vorlage('Passiv', VORLAGEN + '/passiv.png', None)
        with connection.cursor() as c:
            c.execute("UPDATE studio_templates SET active=0 WHERE id=%s", [tid])
        self.assertEqual([], self.client.get(self.URL).json()['templates'])


class GespeicherteAusgaben(BackendTest):
    URL = '/library/studio/api/saved/'

    def _bild(self, titel, canvas_json):
        nc = 'Marketing & Design/Octotrial_Assets/Studio_Work/Output/Images/%s.png' % titel
        with connection.cursor() as c:
            c.execute("INSERT INTO media_library_items (nc_path, title, series, tags) "
                      "VALUES (%s, %s, 'Studio', 'studio')", [nc, titel])
            c.execute("INSERT INTO studio_images (nc_path, title, canvas_json) VALUES (%s, %s, %s)",
                      [nc, titel, canvas_json])

    def test_alte_animierte_bilder_landen_bei_den_gifs(self):
        self._bild('Still', _layout({'type': 'text', 'animType': 'none'}, {'type': 'image', 'src': GROSS}))
        self._bild('Leer', _layout({'type': 'text', 'animType': ''}))
        self._bild('Bewegt', _layout({'type': 'text', 'animType': 'fadeIn'}))
        # Python writes JSON with a space after the colon - both spellings count.
        self._bild('MitLeerzeichen', json.dumps({'objects': [{'animType': 'slideUp'}]}, separators=(', ', ': ')))
        self._bild('Neu', _layout({'type': 'text', 'anim': {'type': 'fadeIn', 'dur': 800}}))
        self._bild('OhneLayout', None)
        d = self.client.get(self.URL).json()
        bilder = {b['title'] for b in d['images']}
        bewegt = {b['title'] for b in d['anim_images']}
        self.assertEqual({'Still', 'Leer', 'Neu', 'OhneLayout'}, bilder)
        self.assertEqual({'Bewegt', 'MitLeerzeichen'}, bewegt)

    def test_suche_funktioniert_weiter(self):
        self._bild('Bericht_Q3', None)
        self._bild('Anderes', None)
        d = self.client.get(self.URL, {'q': 'Q3'}).json()
        self.assertEqual(['Bericht_Q3'], [b['title'] for b in d['images']])


class ErneutSpeichern(BackendTest):
    URL = '/library/studio/save-video/'

    def test_gif_bleibt_in_seinem_ordner(self):
        with connection.cursor() as c:
            c.execute("INSERT INTO media_library_items (nc_path, title, series, tags, folder_id) "
                      "VALUES ('Marketing & Design/x/Alt.gif', 'Alt', 'Studio', 'gif', 7)")
            lib_id = c.lastrowid
        with mock.patch('media_library.views._nc_upload', side_effect=lambda inhalt, pfad, typ: pfad):
            antwort = self.client.post(self.URL, {
                'title': 'Alt', 'lib_item_id': str(lib_id),
                'video': SimpleUploadedFile('Alt.gif', b'GIF89a' + b'x' * 20, content_type='image/gif'),
            })
        self.assertEqual(antwort.status_code, 200, antwort.content[:300])
        self.assertEqual(7, self.zahl("SELECT folder_id FROM media_library_items WHERE id=%s", lib_id))

    def test_ein_mitgeschickter_ordner_gilt_weiterhin(self):
        with connection.cursor() as c:
            c.execute("INSERT INTO media_library_items (nc_path, title, series, tags, folder_id) "
                      "VALUES ('Marketing & Design/x/Clip.webm', 'Clip', 'Studio', 'video', 7)")
            lib_id = c.lastrowid
        with mock.patch('media_library.views._nc_upload', side_effect=lambda inhalt, pfad, typ: pfad):
            self.client.post(self.URL, {
                'title': 'Clip', 'lib_item_id': str(lib_id), 'folder_id': '9',
                'video': SimpleUploadedFile('Clip.webm', b'\x1a\x45\xdf\xa3' + b'x' * 20, content_type='video/webm'),
            })
        self.assertEqual(9, self.zahl("SELECT folder_id FROM media_library_items WHERE id=%s", lib_id))


PNG_1x1 = bytes.fromhex(
    '89504e470d0a1a0a0000000d4948445200000001000000010806000000'
    '1f15c4890000000d49444154789c6360606060000000050001a5f64540'
    '0000000049454e44ae426082')


class BildSpeichern(BackendTest):
    """The Studio now sends the PNG as a file; the old JSON way stays open."""
    URL = '/library/studio/save/'

    def _hochladen(self):
        self.pfade = []

        def hoch(inhalt, pfad, typ):
            self.pfade.append((pfad, len(inhalt)))
            return pfad
        return mock.patch('media_library.views._nc_upload', side_effect=hoch)

    def test_als_formular_mit_datei(self):
        layout = _layout({'type': 'text', 'text': 'Hallo'})
        with self._hochladen(), self.wolke():
            antwort = self.client.post(self.URL, {
                'title': 'Formular_Bild', 'post_id': '',
                'image': SimpleUploadedFile('studio.png', PNG_1x1, content_type='image/png'),
                'canvasJson': SimpleUploadedFile('layout.json', layout.encode(), content_type='application/json'),
            })
        self.assertEqual(antwort.status_code, 200, antwort.content[:300])
        self.assertTrue(antwort.json()['ok'])
        # The PNG arrived byte for byte, and the layout was stored.
        self.assertIn(('Marketing & Design/Octotrial_Assets/Studio_Work/Output/Images/Formular_Bild.png', len(PNG_1x1)),
                      [(p, n) for p, n in self.pfade if p.endswith('Formular_Bild.png')])
        gespeichert = self.zeile("SELECT canvas_json FROM studio_images WHERE title=%s ORDER BY id DESC LIMIT 1",
                                 'Formular_Bild')[0]
        self.assertIn('Hallo', gespeichert)

    def test_ohne_bilddatei_gibt_es_eine_klare_absage(self):
        antwort = self.client.post(self.URL, {'title': 'Nichts'})
        self.assertEqual(antwort.status_code, 400)
        self.assertEqual('No image file', antwort.json()['error'])

    def test_der_alte_json_weg_geht_weiter(self):
        import base64
        with self._hochladen(), self.wolke():
            antwort = self.client.post(self.URL, json.dumps({
                'title': 'Json_Bild', 'dataUrl': 'data:image/png;base64,' + base64.b64encode(PNG_1x1).decode(),
                'canvasJson': _layout({'type': 'text', 'text': 'Alt'}),
            }), content_type='application/json')
        self.assertEqual(antwort.status_code, 200, antwort.content[:300])
        self.assertTrue(any(p.endswith('Json_Bild.png') and n == len(PNG_1x1) for p, n in self.pfade))
