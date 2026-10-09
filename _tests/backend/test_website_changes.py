"""Website changes, check stage (08.10.2026): reading the WordPress REST API
and taking a page's HTML apart into headings, texts, buttons and images."""
from unittest import mock

from django.test import SimpleTestCase, override_settings

from website_changes import inhalt, wp

EL = ('<h2>Clinical trial &amp; oversight</h2><p>For sponsors who <strong>want</strong> clarity.</p>'
      '<a class="elementor-button" href="/contact-page/"><span>Book a call</span></a>'
      '<a href="/x/">plain link</a><img src="https://o.com/a.png?v=2" alt="Hero"><ul><li>One</li></ul>')


class Inhalt(SimpleTestCase):
    def test_teile_in_reihenfolge(self):
        self.assertEqual([
            ('heading', 'Clinical trial & oversight', 'h2'),
            ('text', 'For sponsors who want clarity.', 'p'),
            ('button', 'Book a call', '/contact-page/'),
            ('image', 'Hero', 'https://o.com/a.png'),
            ('text', 'One', 'li'),
        ], inhalt.parts(EL))

    def test_zusammenfassung(self):
        s = inhalt.summary(EL)
        self.assertEqual({'heading': 1, 'text': 2, 'button': 1, 'image': 1}, s['counts'])


def antwort(status, daten):
    return mock.Mock(status_code=status, json=mock.Mock(return_value=daten))


@override_settings(MATOMO_URL='https://octotrial.com', MATOMO_TOKEN='u:p')
class Rest(SimpleTestCase):
    def test_revisionen_ohne_autosave(self):
        revs = [{'id': 2, 'author': 1, 'modified_gmt': '2026-10-07T08:00:00', 'slug': '9-revision-v1',
                 'title': {'raw': 'Home'}, 'content': {'raw': EL}},
                {'id': 3, 'author': 1, 'modified_gmt': '2026-10-07T08:05:00', 'slug': '9-autosave-v1',
                 'title': {'raw': 'Home'}, 'content': {'raw': ''}}]
        with mock.patch('requests.get', return_value=antwort(200, revs)) as get:
            r = wp.revisions('pages', 9)
        self.assertEqual([2], [x['id'] for x in r])
        self.assertEqual('https://octotrial.com/wp-json/wp/v2/pages/9/revisions', get.call_args.args[0])
        self.assertEqual(('u', 'p'), get.call_args.kwargs['auth'])
        self.assertEqual('edit', get.call_args.kwargs['params']['context'])

    def test_fehlende_rechte_klar_benannt(self):
        with mock.patch('requests.get', return_value=antwort(403, {})):
            with self.assertRaisesRegex(wp.WordPressError, 'may not edit'):
                wp.revisions('pages', 9)
        with mock.patch('requests.get', return_value=antwort(401, {})):
            with self.assertRaisesRegex(wp.WordPressError, 'sign-in'):
                wp.page(9)

    def test_seite_oder_beitrag(self):
        antworten = [antwort(404, {}), antwort(200, {'id': 5, 'title': {'raw': 'Insight'}, 'status': 'publish',
                                                     'type': 'post', 'link': 'https://x/', 'modified_gmt': ''})]
        with mock.patch('requests.get', side_effect=antworten):
            self.assertEqual('posts', wp.page(5)['kind'])
