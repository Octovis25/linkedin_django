"""The OJ list: post number, four tabs, medium, time and link (16.10.2026) -
since 21.10.2026 in the same list and editor as the other tabs."""
import json
import re
from unittest import mock

from django.contrib.auth.models import User
from django.db import connection
from django.test import TransactionTestCase

from planner import views as pv

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
        """One post's card on the page."""
        anfang = html.index('id="post-%d"' % pid)
        ende = html.find('<div class="pe-card"', anfang + 10)
        return html[html.rfind('<div', 0, anfang):ende if ende > 0 else len(html)]

    def daten(self, html):
        return json.loads(re.search(r'const PE_POSTS = (\[.*?\]);\r?\n', html, re.S).group(1))

    def test_same_list_and_editor_as_the_other_tabs(self):
        pid = self.post(title='AI is a great SOP writer.')
        html = self.seite()
        self.assertIn('id="post-edit-modal"', html)              # the shared editor
        self.assertIn('<span class="post-nr" title="Post number">#%d</span>' % pid, self.zeile(html, pid))
        self.assertNotIn('oj-table', html)                       # the old table is gone
        self.assertNotIn('data-f="company"', html)               # post types are not for OJ

    def test_four_tabs_and_where_a_post_goes(self):
        d, r, s, p, a = (self.post('Draft'), self.post('Review'), self.post('Scheduled'),
                         self.post('Posted'), self.post('Archive'))
        firma = self.post('Draft', oj=0)                         # company post: not in this list
        html = self.seite()
        tabs = re.findall(r'data-tab="(\w+)" onclick="ojShowTab[^>]*>\w+<span class="n">(\d+)</span>', html)
        self.assertEqual(tabs, [('Draft', '2'), ('Scheduled', '1'), ('Posted', '1'), ('Archive', '1')])
        for pid, tab in ((d, 'Draft'), (r, 'Draft'), (s, 'Scheduled'), (p, 'Posted'), (a, 'Archive')):
            self.assertIn('data-oj-tab="%s"' % tab, self.zeile(html, pid))
        self.assertNotIn('id="post-%d"' % firma, html)

    def test_missing_medium_and_studio_draft_are_marked(self):
        bild = self.post(image='Marketing & Design/LinkedIn/Planner/Images/b.png')
        film = self.post(video='Marketing & Design/x/a.mp4')
        entwurf = self.post()
        nichts = self.post()
        with connection.cursor() as c:
            c.execute("INSERT INTO studio_images (nc_path, title, canvas_json, post_id) VALUES ('', 'E', '{}', %s)",
                      [entwurf])
        html = self.seite()
        for pid in (bild, film):
            self.assertNotIn('class="pe-medium', self.zeile(html, pid))
        self.assertIn('🎨 Studio draft', self.zeile(html, entwurf))
        self.assertIn('– no medium', self.zeile(html, nichts))

    def test_studio_button_and_in_button_on_every_oj_post(self):
        pid = self.post('Draft')
        with mock.patch.object(pv, '_li_get_superuser_token',
                               return_value={'access_token': 'x', 'org_name': 'Octovis'}):
            html = self.seite()
        z = self.zeile(html, pid)
        self.assertIn('href="/library/studio/?post_id=%d"' % pid, z)
        self.assertIn('onclick="liOpenPost(%d)"' % pid, z)        # also before Scheduled
        # Personal posts only go to the personal profile.
        auswahl = re.search(r'<select id="li-target".*?</select>', html, re.S).group(0)
        self.assertIn('value="person"', auswahl)
        self.assertNotIn('value="org"', auswahl)

    def test_new_post_from_oj_is_an_oj_post(self):
        html = self.seite()
        self.assertIn('status=Draft&amp;oj=1', html)
        planner = self.client.get('/planner/').content.decode()
        self.assertIn("is_oj: window.OV_NEW_OJ ? 1 : 0", planner)

    def test_time_and_link_reach_the_page_data(self):
        pid = self.post()
        with connection.cursor() as c:
            c.execute("UPDATE planner_posts SET planned_date='2026-10-21', planned_time='08:30:00', link=%s WHERE id=%s",
                      [BLOG, pid])
        html = self.seite()
        eintrag = [d for d in self.daten(html) if d['id'] == pid][0]
        self.assertEqual((eintrag['time'][:5], eintrag['link'], eintrag['is_oj']), ('08:30', BLOG, True))
        self.assertIn('21.10.2026 🕐 08:30', self.zeile(html, pid))

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
