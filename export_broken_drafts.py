"""
Einmal-Helfer: exportiert die kaputten Planner-Drafts (mit rohem HTML-Muell)
in die Datei 'broken_drafts_dump.txt' im Repo-Ordner.

Ausfuehren im Repo-Ordner C:\\dev\\linkedin_django mit aktivierter venv:

    python export_broken_drafts.py

Nur LESEND - aendert nichts in der Datenbank. Danach kann die Datei geloescht werden.
"""
import os, django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from django.db import connection

SQL = """
    SELECT id, title, status, planned_date, content
    FROM planner_posts
    WHERE content LIKE %s OR content LIKE %s
    ORDER BY id
"""

with connection.cursor() as c:
    c.execute(SQL, ["%data-start%", "%selectionAnchorContainer%"])
    rows = c.fetchall()

out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "broken_drafts_dump.txt")
with open(out_path, "w", encoding="utf-8") as f:
    f.write("Gefundene kaputte Drafts: %d\n" % len(rows))
    for r in rows:
        _id, title, status, date, content = r
        f.write("\n" + "=" * 70 + "\n")
        f.write("id=%s | status=%s | date=%s | title=%r\n" % (_id, status, date, title))
        f.write("-" * 70 + "\n")
        f.write((content or "") + "\n")

print("Fertig. %d Draft(s) geschrieben nach:\n%s" % (len(rows), out_path))
