"""The edit windows show the post's number in their heading (25.10.2026).

Ortrud wanted to see which post she is changing: the cards carry "#143", the
open edit window did not. Both edit windows - the one of the post lists
(Scheduled, Ready, All, OJ) and the one in the Planner - now say
"Edit Post #143". A new post has no number yet and says "New Post".

The pages are rendered by Django and then run in Chromium; every request the
page makes is answered locally.
"""
from django.contrib.auth.models import User
from django.db import connection
from django.test import TransactionTestCase
from playwright.sync_api import sync_playwright

from .basis import schema_aufbauen

WEITERE_SPALTEN = [
    "topic_id INT NULL", "planned_date DATE NULL", "planned_time TIME NULL",
    "in_pipeline TINYINT NOT NULL DEFAULT 0", "series_id INT NULL",
    "series_order INT NOT NULL DEFAULT 0", "is_oj TINYINT NOT NULL DEFAULT 0",
    "created_at DATETIME DEFAULT CURRENT_TIMESTAMP",
    "updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP",
]


class NummerImBearbeitenFenster(TransactionTestCase):

    def setUp(self):
        super().setUp()
        schema_aufbauen()
        with connection.cursor() as c:
            for s in WEITERE_SPALTEN:
                try:
                    c.execute("ALTER TABLE planner_posts ADD COLUMN " + s)
                except Exception:
                    pass
            c.execute("""CREATE TABLE IF NOT EXISTS planner_topics (
                             id INT AUTO_INCREMENT PRIMARY KEY, name VARCHAR(100),
                             color VARCHAR(20))""")
            c.execute("INSERT INTO planner_topics (name, color) VALUES ('Oversight', '#008591')")
            thema = c.lastrowid
            c.execute("""INSERT INTO planner_posts (title, content, status, in_pipeline, planned_date, topic_id)
                         VALUES ('Monday', 'Text', 'Scheduled', 1, '2030-10-26', %s)""", [thema])
            self.post = c.lastrowid
        self.client.force_login(User.objects.create_superuser('nr', password='nr'))

    def seite(self, url):
        antwort = self.client.get(url)
        self.assertEqual(antwort.status_code, 200)
        return antwort.content.decode('utf-8')

    def im_browser(self, html, schritte):
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                page = browser.new_page()
                page.route('**/*', lambda route: route.fulfill(status=204, body=''))
                page.set_content(html, wait_until='domcontentloaded')
                return schritte(page)
            finally:
                browser.close()

    def test_post_list_edit_window_shows_the_number(self):
        def schritte(page):
            page.evaluate('id => openEdit(id)', self.post)
            return page.evaluate("""() => [
                document.getElementById('pe-heading').textContent,
                document.getElementById('pe-nr').textContent,
                getComputedStyle(document.getElementById('pe-nr')).display]""")
        heading, nr, display = self.im_browser(self.seite('/planner/scheduled/'), schritte)
        self.assertEqual((heading, nr), ('Edit Post', '#%d' % self.post))
        self.assertNotEqual(display, 'none')

    def test_new_post_has_no_number(self):
        def schritte(page):
            page.evaluate('id => openEdit(id)', self.post)
            page.evaluate('openCreate()')
            return page.evaluate("""() => [
                document.getElementById('pe-heading').textContent,
                document.getElementById('pe-nr').textContent,
                getComputedStyle(document.getElementById('pe-nr')).display]""")
        self.assertEqual(self.im_browser(self.seite('/planner/scheduled/'), schritte),
                         ['New Post', '', 'none'])

    def test_planner_edit_window_shows_the_number(self):
        def schritte(page):
            page.evaluate("id => openEditModal(id, 'Monday', 'Text', 'Scheduled', '2030-10-26', '', '', '', '')",
                          self.post)
            return page.evaluate("() => document.querySelector('#edit-modal h3').textContent.trim()")
        self.assertEqual(self.im_browser(self.seite('/planner/'), schritte),
                         'Edit Post #%d' % self.post)
