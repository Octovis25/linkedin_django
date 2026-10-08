"""Sorting in every planner tab (08.10.2026): each card carries what the sort
in the browser needs - number, send date, created, last edited."""
import json
import re

from django.contrib.auth.models import User
from django.db import connection
from django.test import TransactionTestCase

from .basis import schema_aufbauen

WEITERE_SPALTEN = [
    "topic_id INT NULL", "planned_date DATE NULL", "planned_time TIME NULL",
    "in_pipeline TINYINT NOT NULL DEFAULT 0", "series_id INT NULL",
    "series_order INT NOT NULL DEFAULT 0", "is_oj TINYINT NOT NULL DEFAULT 0",
    "created_at DATETIME DEFAULT CURRENT_TIMESTAMP",
    "updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP",
]


class Sortieren(TransactionTestCase):

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
                             id INT AUTO_INCREMENT PRIMARY KEY, name VARCHAR(100), color VARCHAR(20))""")
            for status, oj, tag, zeit in (('Draft', 0, '2026-10-12', '08:45:00'), ('Ready', 0, None, None),
                                          ('Draft', 1, '2026-11-02', '07:30:00')):
                c.execute("""INSERT INTO planner_posts (title, content, status, in_pipeline, is_oj,
                                                        planned_date, planned_time, created_at, updated_at)
                             VALUES ('T', 'C', %s, 1, %s, %s, %s, '2026-09-01 10:00:00', '2026-10-05 11:30:00')""",
                          [status, oj, tag, zeit])
        self.client.force_login(User.objects.create_superuser('so', password='so'))

    def karten(self, url, tag):
        html = self.client.get(url).content.decode()
        self.assertIn('Sort by:', html)
        return re.findall(r'<%s class="(?:pe-card|post-row)"[^>]*>' % tag, html)

    def test_draft_karten_tragen_die_daten(self):
        karte = self.karten('/planner/draft/', 'div')[0]
        self.assertIn('data-send="12.10.2026 08:45"', karte)
        self.assertIn('data-created="2026-09-01 10:00:00"', karte)
        self.assertIn('data-edited="2026-10-05 11:30:00"', karte)
        self.assertRegex(karte, r'data-num="\d+"')

    def test_ready_ohne_datum(self):
        karte = self.karten('/planner/ready/', 'div')[0]
        self.assertIn('data-send=""', karte)

    def test_oj_bekommt_sortierung_mit_datum_und_uhrzeit(self):
        zeile = self.karten('/planner/oj/', 'tr')[0]
        self.assertIn('data-send="02.11.2026 07:30"', zeile)
        self.assertIn('data-created="2026-09-01 10:00:00"', zeile)
