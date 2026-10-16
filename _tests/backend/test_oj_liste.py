"""The OJ list (16.10.2026): post number, four tabs, medium, and the time and
link fields in the editor - like the company planner."""
import json
import re

from django.contrib.auth.models import User
from django.db import connection
from django.test import TransactionTestCase

from .basis import schema_aufbauen
from .test_sortieren import WEITERE_SPALTEN

BLOG = 'https://octotrial.com/insights/can-ai-write-clinical-research-sops/'


class OjListe(TransactionTestCase):

    def setUp(self):
        super().setUp()
        schema_aufbauen()
        with connection.cursor() as c:
            for s in WEITERE_SPALTEN + ["link VARCHAR(500) NULL", "comment TEXT NULL"]:
                try:
                    c.execute("ALTER TABLE planner_posts ADD COLUMN " + s)
                except Exception:
                    pass
            c.execute("""CREATE TABLE IF NOT EXISTS planner_topics (
                             id INT AUTO_INCREMENT PRIMARY KEY, name VARCHAR(100), color VARCHAR(20))""")
            c.execute("INSERT INTO planner_topics (name, color) VALUES ('SOP', 'green')")
            self.sop = c.lastrowid
        self.client.force_login(User.objects.create_superuser('oj', password='oj'))

    def post(self, status='Draft', image='', video='', oj=1, title='T'):
        with connection.cursor() as c:
            c.execute("""INSERT INTO planner_posts (title, content, status, is_oj, image, video_nc_path, topic_id)
                         VALUES (%s, 'C', %s, %s, %s, %s, %s)""", [title, status, oj, image, video, self.sop])
            return c.lastrowid

    def seite(self):
        antwort = self.client.get('/planner/oj/')
        self.assertEqual(antwort.status_code, 200)
        return antwort.content.decode()

    def zeile(self, html, pid):
        return re.search(r'<tr class="post-row" id="prow-%d".*?</tr>' % pid, html, re.S).group(0)

    def test_number_before_the_title(self):
        pid = self.post(title='AI is a great SOP writer.')
        z = self.zeile(self.seite(), pid)
        self.assertIn('<span class="oj-nr" title="Post number">#%d</span>AI is a great SOP writer.' % pid, z)

    def test_four_tabs_and_where_a_post_goes(self):
        d, r, s, p, a = (self.post('Draft'), self.post('Review'), self.post('Scheduled'),
                         self.post('Posted'), self.post('Archive'))
        self.post('Draft', oj=0)                          # company post: not in this list
        html = self.seite()
        tabs = re.findall(r'data-tab="(\w+)" onclick="ojShowTab[^>]*>\w+<span class="n">(\d+)</span>', html)
        self.assertEqual(tabs, [('Draft', '2'), ('Scheduled', '1'), ('Posted', '1'), ('Archive', '1')])
        for pid, tab in ((d, 'Draft'), (r, 'Draft'), (s, 'Scheduled'), (p, 'Posted'), (a, 'Archive')):
            self.assertIn('data-tab="%s"' % tab, self.zeile(html, pid))
        self.assertNotIn('>Review<span', html)
        self.assertNotIn('>Ready<span', html)

    def test_medium_column(self):
        bild = self.post(image='Marketing & Design/LinkedIn/Planner/Images/b.png')
        gif = self.post(video='Marketing & Design/x/a.gif')
        film = self.post(video='Marketing & Design/x/a.mp4')
        entwurf = self.post()
        nichts = self.post()
        with connection.cursor() as c:
            c.execute("INSERT INTO studio_images (nc_path, title, canvas_json, post_id) VALUES ('', 'E', '{}', %s)",
                      [entwurf])
        html = self.seite()
        self.assertIn('🖼 Picture', self.zeile(html, bild))
        self.assertIn('>GIF<', self.zeile(html, gif))
        self.assertIn('🎬 Video', self.zeile(html, film))
        self.assertIn('🎨 Draft', self.zeile(html, entwurf))
        self.assertIn('oj-medium fehlt">– missing', self.zeile(html, nichts))

    def test_studio_button_in_the_row_does_not_open_the_editor(self):
        pid = self.post()
        z = self.zeile(self.seite(), pid)
        self.assertIn('href="/library/studio/?post_id=%d" target="_blank"\n          onclick="event.stopPropagation()"' % pid, z)

    def test_editor_has_number_time_and_link_with_tag(self):
        html = self.seite()
        for teil in ('id="e-num"', 'id="e-time"', 'id="e-link"', 'onclick="ojTagLink()"', 'onclick="ojCopyLink()"',
                     'id="n-time"', 'id="n-link"'):
            self.assertIn(teil, html)

    def test_time_and_link_reach_the_page_data(self):
        pid = self.post()
        with connection.cursor() as c:
            c.execute("UPDATE planner_posts SET planned_date='2026-10-21', planned_time='08:30:00', link=%s WHERE id=%s",
                      [BLOG, pid])
        html = self.seite()
        daten = json.loads(re.search(r'<script id="oj-data-raw" type="application/json">(.*?)</script>',
                                     html, re.S).group(1))
        eintrag = [d for d in daten if d['id'] == pid][0]
        self.assertEqual((eintrag['time'], eintrag['link']), ('08:30', BLOG))
        self.assertIn('21.10.2026 08:30', self.zeile(html, pid))

    def test_saving_keeps_time_and_link(self):
        pid = self.post()
        r = self.client.post('/planner/api/post/', json.dumps({
            'action': 'update', 'id': pid, 'title': 'T', 'content': 'C', 'status': 'Draft',
            'planned_date': '2026-10-21', 'planned_time': '08:30', 'link': BLOG, 'comment': None}),
            content_type='application/json')
        self.assertTrue(r.json()['ok'], r.content)
        with connection.cursor() as c:
            c.execute("SELECT planned_time, link FROM planner_posts WHERE id=%s", [pid])
            zeit, link = c.fetchone()
        self.assertEqual((str(zeit), link), ('08:30:00', BLOG))

    def test_new_post_with_time_and_link(self):
        r = self.client.post('/planner/api/post/', json.dumps({
            'action': 'create', 'title': 'Neu', 'content': 'C', 'status': 'Draft', 'is_oj': 1,
            'planned_date': '2026-10-21', 'planned_time': '08:30', 'link': BLOG}),
            content_type='application/json')
        pid = r.json()['id']
        with connection.cursor() as c:
            c.execute("SELECT planned_time, link, is_oj FROM planner_posts WHERE id=%s", [pid])
            zeit, link, oj = c.fetchone()
        self.assertEqual((str(zeit), link, oj), ('08:30:00', BLOG, 1))

    def test_tag_gives_the_personal_profile_link_with_the_number(self):
        pid = self.post()
        d = self.client.get('/planner/api/utm/', {'post_id': pid, 'url': BLOG}).json()
        self.assertTrue(d['ok'])
        self.assertEqual(d['channel'], 'personal_profile')
        self.assertIn('utm_content=post-%d' % pid, d['url'])
        self.assertIn('utm_term=personal_profile', d['url'])
