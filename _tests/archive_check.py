"""Which posts were archived before they were ever published?

Until September 2026 the Buffer sync wrote Buffer's dueAt - the PLANNED time -
into sent_at, and promote_scheduled_to_posted() read any timestamp there as
proof that the post had gone out. Posts that were merely queued were moved to
'Posted' and showed up in the archive, days early.

The sync no longer does that, but the posts it already moved are still sitting
in 'Posted'. This lists them. It changes nothing.

    python _tests/archive_check.py

Run the Buffer sync first (python manage.py fetch_buffer_posts) - it rewrites
sent_at, and only then can a queued post be told from a published one.
"""
import os
import sys

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HIER))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dashboard.settings')

import django

django.setup()

from django.db import connection          # noqa: E402

ABFRAGE = """
    SELECT p.id, p.title, p.status, b.status, b.due_at
    FROM planner_posts p
    JOIN buffer_posts_posted b ON b.planner_post_id = p.id
    WHERE p.status = 'Posted'
      AND b.sent_at IS NULL
      AND LOWER(COALESCE(b.status, '')) <> 'sent'
    ORDER BY b.due_at
"""

with connection.cursor() as zeiger:
    zeiger.execute(ABFRAGE)
    zeilen = zeiger.fetchall()

if not zeilen:
    print('Nothing found. No post sits in the archive unpublished.')
    sys.exit(0)

print('%d post(s) are in the archive although Buffer has not sent them:\n' % len(zeilen))
print('%-6s %-44s %-12s %s' % ('id', 'title', 'buffer', 'planned for'))
print('-' * 84)
for kennung, titel, _status, buffer_status, geplant in zeilen:
    print('%-6s %-44s %-12s %s' % (
        kennung, (titel or '')[:44], buffer_status or '-', geplant or '-'))

print('\nTo put them back, with their planned time restored:\n')
print("""UPDATE planner_posts p
JOIN buffer_posts_posted b ON b.planner_post_id = p.id
SET p.status = 'Scheduled',
    p.linkedin_posted = 0,
    p.post_scheduled_at = STR_TO_DATE(
        REPLACE(REPLACE(b.due_at, 'T', ' '), 'Z', ''), '%Y-%m-%d %H:%i:%s')
WHERE p.status = 'Posted'
  AND b.sent_at IS NULL
  AND LOWER(COALESCE(b.status, '')) <> 'sent';""")
print('\nRead the list above first. Anything you archived on purpose does not')
print('belong in that UPDATE - move it out of the way before running it.')
