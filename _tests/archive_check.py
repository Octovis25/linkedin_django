"""Which posts sit in the archive although they were never published?

Two ways that happens, and they need different queries.

The old one: until September 2026 the sync wrote Buffer's dueAt - the PLANNED
time - into sent_at, and promote_scheduled_to_posted() read any timestamp there
as proof of publication. Those posts have no send proof at all any more.

The second one is worse, because it still bites: a row that the sync does not
refresh keeps whatever it had. If that is an old planned time in sent_at, the
promotion reads it as proof at the very next sync - and the post is archived
days before it goes out. A send date in the FUTURE is the giveaway: nothing is
ever sent tomorrow.

This changes nothing. It reads and prints.

    python _tests/archive_check.py

Run the Buffer sync first (python manage.py fetch_buffer_posts) - it rewrites
sent_at, and only then can a queued post be told from a published one.
"""
import os
import sys

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HIER))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dashboard.settings')

import django                              # noqa: E402

django.setup()

from django.db import connection           # noqa: E402

# sent_at and due_at are text (Buffer's ISO stamps). LEFT(...,19) cuts the
# milliseconds and the Z off, so MySQL can read them as a time.
ALS_ZEIT = ("STR_TO_DATE(REPLACE(LEFT(%s, 19), 'T', ' '), '%%Y-%%m-%%d %%H:%%i:%%s')")

OHNE_BELEG = """
    SELECT p.id, p.title, COALESCE(b.status,''), COALESCE(b.due_at,''), COALESCE(b.sent_at,'')
    FROM planner_posts p
    JOIN buffer_posts_posted b ON b.planner_post_id = p.id
    WHERE p.status IN ('Posted', 'Archive')
      AND b.sent_at IS NULL
      AND LOWER(COALESCE(b.status, '')) <> 'sent'
    ORDER BY b.due_at
"""

IN_DER_ZUKUNFT = """
    SELECT p.id, p.title, COALESCE(b.status,''), COALESCE(b.due_at,''), COALESCE(b.sent_at,'')
    FROM planner_posts p
    JOIN buffer_posts_posted b ON b.planner_post_id = p.id
    WHERE p.status IN ('Posted', 'Archive')
      AND b.sent_at IS NOT NULL
      AND {zeit} > UTC_TIMESTAMP()
    ORDER BY b.sent_at
""".format(zeit=ALS_ZEIT % 'b.sent_at')


def zeige(titel, sql, erklaerung):
    with connection.cursor() as zeiger:
        zeiger.execute(sql)
        zeilen = zeiger.fetchall()
    print('\n=== %s ===' % titel)
    if not zeilen:
        print('  nothing found.')
        return []
    print('  %s\n' % erklaerung)
    print('  %-6s %-40s %-10s %-22s %s' % ('id', 'title', 'buffer', 'planned for', 'sent at'))
    print('  ' + '-' * 104)
    for kennung, name, bstatus, faellig, gesendet in zeilen:
        print('  %-6s %-40s %-10s %-22s %s' % (
            kennung, (name or '')[:40], bstatus or '-', faellig or '-', gesendet or '-'))
    return zeilen


# The two queries above ask Buffer's side of the story and need a row there.
# This one asks the post itself: it is filed as done, but the day you planned it
# for has not come. However it got there, that is wrong - and it finds posts
# with no Buffer row at all, which the others cannot see.
NOCH_NICHT_FAELLIG = """
    SELECT p.id, p.title, p.status,
           CONCAT(COALESCE(p.planned_date,''), ' ', COALESCE(p.planned_time,'')),
           COALESCE(b.status,'(no buffer row)')
    FROM planner_posts p
    LEFT JOIN buffer_posts_posted b ON b.planner_post_id = p.id
    WHERE p.status IN ('Posted', 'Archive')
      AND p.planned_date IS NOT NULL
      AND p.planned_date > CURDATE()
    ORDER BY p.planned_date
"""

with connection.cursor() as zeiger:
    zeiger.execute(NOCH_NICHT_FAELLIG)
    kuenftig = zeiger.fetchall()

print('\n=== Filed as done, but planned for a day still to come ===')
if not kuenftig:
    print('  nothing found.')
else:
    print('  These sit in the archive although their date has not arrived.\n')
    print('  %-6s %-40s %-10s %-20s %s' % ('id', 'title', 'status', 'planned for', 'buffer'))
    print('  ' + '-' * 100)
    for kennung, name, pstatus, geplant, bstatus in kuenftig:
        print('  %-6s %-40s %-10s %-20s %s' % (
            kennung, (name or '')[:40], pstatus, (geplant or '').strip() or '-', bstatus))
    print('\n  To put them back on Scheduled:')
    print('  UPDATE planner_posts SET status=\'Scheduled\', linkedin_posted=0')
    print('  WHERE id IN (%s);' % ', '.join(str(z[0]) for z in kuenftig))

ohne = zeige('Archived without any proof of sending',
             OHNE_BELEG,
             'Buffer reports neither a send date nor status "sent" for these.')

zukunft = zeige('Archived with a send date in the FUTURE',
                IN_DER_ZUKUNFT,
                'Nothing is sent tomorrow. sent_at still holds a planned time - '
                'the row was never refreshed, and the promotion believed it.')

if not ohne and not zukunft and not kuenftig:
    print('\nNothing to repair. Every archived post has a real send date.')
    sys.exit(0)

print('\n\nTo put them back, with their planned time restored:\n')
print("""UPDATE planner_posts p
JOIN buffer_posts_posted b ON b.planner_post_id = p.id
SET p.status = 'Scheduled',
    p.linkedin_posted = 0,
    p.post_scheduled_at = STR_TO_DATE(
        REPLACE(LEFT(COALESCE(NULLIF(b.due_at,''), b.sent_at), 19), 'T', ' '),
        '%Y-%m-%d %H:%i:%s')
WHERE p.id IN (""" + ', '.join(str(z[0]) for z in (list(ohne) + list(zukunft))) + """);""")
print('\nThe ids above are exactly the posts listed. Read the list first -')
print('anything you archived on purpose does not belong in that UPDATE.')
