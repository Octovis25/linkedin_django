"""A prepared design attached straight to a planner post (studio/api/post-draft/).

Claude builds the draft in the Studio page and hands it over; the next time
the Studio opens for the post, that design is on the canvas. Earlier designs
of the post stay in the table.
"""
import json
import re
from unittest import mock

from django.db import connection

from .test_studio_listen import BackendTest

URL = '/library/studio/api/post-draft/'
OPT = 'media_library.views._optimize_canvas_json'


def _entwurf(text):
    return json.dumps({'version': 2, 'width': 1080, 'height': 1080, 'objects': [],
                       'fabric': {'version': '5.3.0', 'objects': [{'type': 'textbox', 'text': text}]}})


class PostEntwurf(BackendTest):

    def _post(self, titel='Post', bild='', video=''):
        with connection.cursor() as c:
            c.execute("INSERT INTO planner_posts (title, content, image, video_nc_path) VALUES (%s, 'x', %s, %s)",
                      [titel, bild, video])
            return c.lastrowid

    def _haengen(self, post_id, text, **mehr):
        with mock.patch(OPT, side_effect=lambda j, ordner, titel: j) as opt:
            antwort = self.client.post(URL, json.dumps({'post_id': post_id, 'canvas_json': _entwurf(text), **mehr}),
                                       content_type='application/json')
        return antwort, opt

    def _im_studio(self, post_id):
        seite = self.client.get('/library/studio/?post_id=%d' % post_id).content.decode()
        m = re.search(r'<script id="studio-config" type="application/json">(.*?)</script>', seite, re.S)
        return json.loads(m.group(1))['postData']

    def _zeilen(self, post_id):
        with connection.cursor() as c:
            c.execute("SELECT nc_path, title FROM studio_images WHERE post_id=%s ORDER BY id", [post_id])
            return c.fetchall()

    def test_der_entwurf_haengt_am_post_und_oeffnet_sich_im_studio(self):
        pid = self._post('Hidden workload', video='Marketing & Design/LinkedIn/Planner/Videos/v.mp4')
        antwort, opt = self._haengen(pid, 'Neu')
        self.assertEqual(antwort.status_code, 200, antwort.content)
        self.assertTrue(antwort.json()['ok'])
        self.assertEqual(antwort.json()['nc_path'], 'Marketing & Design/LinkedIn/Planner/Videos/v.mp4')
        daten = self._im_studio(pid)
        self.assertIn('"Neu"', daten['canvas_json'])
        # Embedded images go to the Studio's library folder, from the server.
        from media_library.views import NC_STUDIO_LIBRARY_FOLDER
        self.assertEqual(opt.call_args[0][1], NC_STUDIO_LIBRARY_FOLDER)

    def test_er_schlaegt_ein_aelteres_design_derselben_datei(self):
        bild = 'Marketing & Design/LinkedIn/Planner/Images/b.png'
        pid = self._post('Mit Bild', bild=bild)
        with connection.cursor() as c:   # the design saved with the image earlier
            c.execute("INSERT INTO studio_images (nc_path, title, canvas_json, post_id) VALUES (%s,'Alt',%s,%s)",
                      [bild, _entwurf('Alt'), pid])
        self._haengen(pid, 'Vorbereitet')
        self.assertIn('"Vorbereitet"', self._im_studio(pid)['canvas_json'])
        # ... and the earlier one is still there
        self.assertEqual([t for _, t in self._zeilen(pid)], ['Alt', 'Mit Bild'])

    def test_post_ohne_datei(self):
        pid = self._post('Leer')
        antwort, _ = self._haengen(pid, 'Nur Entwurf', title='Eigener Titel')
        self.assertEqual(antwort.json()['nc_path'], '')
        self.assertEqual(self._zeilen(pid), (('', 'Eigener Titel'),))
        self.assertIn('"Nur Entwurf"', self._im_studio(pid)['canvas_json'])

    def test_was_abgewiesen_wird(self):
        pid = self._post()
        self.assertEqual(self.client.get(URL).status_code, 405)
        schick = lambda d: self.client.post(URL, json.dumps(d), content_type='application/json')
        self.assertEqual(schick({'post_id': 999999, 'canvas_json': _entwurf('x')}).status_code, 404)
        self.assertEqual(schick({'canvas_json': _entwurf('x')}).status_code, 400)
        self.assertEqual(schick({'post_id': pid, 'canvas_json': '{kaputt'}).status_code, 400)
        self.assertEqual(schick({'post_id': pid, 'canvas_json': '{"version": 2}'}).status_code, 400)
        self.assertEqual(schick({'post_id': pid}).status_code, 400)
        self.assertEqual(self.client.post(URL, 'kein json', content_type='application/json').status_code, 400)
        self.assertEqual(self._zeilen(pid), ())

    def test_nur_angemeldet(self):
        pid = self._post()
        self.client.logout()
        antwort = self.client.post(URL, json.dumps({'post_id': pid, 'canvas_json': _entwurf('x')}),
                                   content_type='application/json')
        self.assertEqual(antwort.status_code, 302)
        self.assertEqual(self._zeilen(pid), ())
