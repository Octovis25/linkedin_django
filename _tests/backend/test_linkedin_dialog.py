"""The LinkedIn dialog keeps a post's date when the time is missing (17.10.2026).

Since 06.10.2026 the dialog shows the post's own date and time, nothing made
up. But it was one datetime field: a post with a date and no time (#142)
opened with the whole field empty, and the date had to be typed again. Now
date and time are two fields. The date comes from the post, the time too if
there is one, and an empty time stops the sending with a message.

The page is rendered by Django and then run in Chromium; every request the
page makes is answered locally, and the send call is caught, not sent.
"""
from unittest import mock

from django.contrib.auth.models import User
from django.db import connection
from django.test import TransactionTestCase
from playwright.sync_api import sync_playwright

from planner import views as pv

from .basis import schema_aufbauen

WEITERE_SPALTEN = [
    "topic_id INT NULL", "planned_date DATE NULL", "planned_time TIME NULL",
    "in_pipeline TINYINT NOT NULL DEFAULT 0", "series_id INT NULL",
    "series_order INT NOT NULL DEFAULT 0", "is_oj TINYINT NOT NULL DEFAULT 0",
    "created_at DATETIME DEFAULT CURRENT_TIMESTAMP",
    "updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP",
]

SEND_CATCHER = """
window.__sent = null;
window.fetch = async (url, opts) => {
  if (String(url).includes('/linkedin/post/'))
    window.__sent = {url: String(url), body: JSON.parse(opts.body)};
  return new Response(JSON.stringify({ok: true, scheduled: true}),
                      {headers: {'Content-Type': 'application/json'}});
};
"""


class LinkedInDialog(TransactionTestCase):

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
            c.execute("""INSERT INTO planner_posts (title, content, status, in_pipeline, planned_date)
                         VALUES ('No time', 'Text', 'Scheduled', 1, '2030-10-19')""")
            self.ohne = c.lastrowid
            c.execute("""INSERT INTO planner_posts (title, content, status, in_pipeline, planned_date, planned_time)
                         VALUES ('With time', 'Text', 'Scheduled', 1, '2030-10-30', '10:00:00')""")
            self.mit = c.lastrowid
            c.execute("""INSERT INTO planner_posts (title, content, status, planned_date, is_oj)
                         VALUES ('OJ no time', 'Text', 'Draft', '2030-10-21', 1)""")
            self.oj = c.lastrowid
        self.client.force_login(User.objects.create_superuser('ld', password='ld'))

    def seite(self, url):
        # The dialog is only on the page when LinkedIn is connected.
        with mock.patch.object(pv, '_li_get_superuser_token',
                               return_value={'access_token': 'x', 'org_name': 'Octovis'}):
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
                page.evaluate(SEND_CATCHER)
                return schritte(page)
            finally:
                browser.close()

    # ── Scheduled / Ready / Archive / All ─────────────────────────────────
    def test_date_without_time_keeps_the_date(self):
        def schritte(page):
            page.evaluate('id => liOpenPost(id)', self.ohne)
            return (page.input_value('#li-schedule-date'),
                    page.input_value('#li-schedule-time'))
        self.assertEqual(self.im_browser(self.seite('/planner/scheduled/'), schritte),
                         ('2030-10-19', ''))

    def test_date_and_time_are_both_taken(self):
        def schritte(page):
            page.evaluate('id => liOpenPost(id)', self.mit)
            return (page.input_value('#li-schedule-date'),
                    page.input_value('#li-schedule-time'))
        self.assertEqual(self.im_browser(self.seite('/planner/scheduled/'), schritte),
                         ('2030-10-30', '10:00'))

    def test_missing_time_sends_nothing_and_says_so(self):
        def schritte(page):
            page.evaluate('id => liOpenPost(id)', self.ohne)
            page.evaluate('liDoPost()')
            page.wait_for_function("document.getElementById('li-post-result').textContent")
            return (page.text_content('#li-post-result'), page.evaluate('window.__sent'))
        text, gesendet = self.im_browser(self.seite('/planner/scheduled/'), schritte)
        self.assertIn('Choose a time', text)
        self.assertIsNone(gesendet)

    def test_choosing_a_time_sends_date_and_time(self):
        def schritte(page):
            page.evaluate('id => liOpenPost(id)', self.ohne)
            page.select_option('#li-schedule-time', '10:00')
            page.evaluate('liDoPost()')
            page.wait_for_function('window.__sent')
            return page.evaluate("""() => {
                const d = new Date(window.__sent.body.scheduled_ms);
                return [d.getFullYear(), d.getMonth() + 1, d.getDate(), d.getHours(), d.getMinutes()];
            }""")
        self.assertEqual(self.im_browser(self.seite('/planner/scheduled/'), schritte),
                         [2030, 10, 19, 10, 0])

    # ── OJ: same dialog, personal profile, video stays, link is for the comment ──
    def test_oj_date_without_time_keeps_the_date(self):
        def schritte(page):
            page.evaluate('id => liOpenPost(id)', self.oj)
            erst = (page.input_value('#li-schedule-date'), page.input_value('#li-schedule-time'),
                    page.input_value('#li-target'))
            page.evaluate('liDoPost()')
            page.wait_for_function("document.getElementById('li-post-result').textContent")
            return erst, page.text_content('#li-post-result'), page.evaluate('window.__sent')
        erst, text, gesendet = self.im_browser(self.seite('/planner/oj/'), schritte)
        self.assertEqual(erst, ('2030-10-21', '', 'person'))
        self.assertIn('Choose a time', text)
        self.assertIsNone(gesendet)

    def test_oj_video_goes_along_although_there_is_a_link(self):
        with connection.cursor() as c:
            c.execute("""UPDATE planner_posts SET planned_time='09:00:00', video_nc_path=%s, link=%s
                         WHERE id=%s""", ['Marketing & Design/x/AI_SOP.webm',
                                          'https://octotrial.com/insights/x/', self.oj])

        def schritte(page):
            page.evaluate('id => liOpenPost(id)', self.oj)
            sichtbar = page.evaluate("""() => [
                getComputedStyle(document.getElementById('li-video-info')).display,
                document.getElementById('li-link-label').textContent]""")
            page.evaluate('liDoPost()')
            page.wait_for_function('window.__sent')
            return sichtbar, page.evaluate('window.__sent.body')
        (video, hinweis), body = self.im_browser(self.seite('/planner/oj/'), schritte)
        self.assertNotEqual(video, 'none')
        self.assertIn('first comment', hinweis)
        self.assertEqual((body['target'], body['include_video']), ('person', True))
        self.assertTrue(body['scheduled_ms'])
