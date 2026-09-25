"""Why is a post still sitting in Scheduled?

A post leaves Scheduled when the Buffer sync finds it published. Three things
have to line up for that, and this prints all three:

  * the planner post has to be linked to a Buffer post at all
    (buffer_posts_posted.planner_post_id),
  * Buffer has to report that post as sent - status='sent', or a sent_at on
    record,
  * and the sync has to have run since it went out.

Until September 2026 the sync wrote Buffer's dueAt - the PLANNED time - into
sent_at, so every queued post looked published and was archived days early.
That is fixed. The opposite failure is now the one to watch: if Buffer supplies
neither a status of 'sent' nor a sent_at, nothing is ever promoted and posts
pile up in Scheduled. This tells the two apart.

    python _tests/sync_check.py
"""
import os
import sys

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HIER))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dashboard.settings')

import django

django.setup()

from django.conf import settings            # noqa: E402
from django.db import connection            # noqa: E402
from django.utils import timezone           # noqa: E402

print('Django TIME_ZONE : %s' % getattr(settings, 'TIME_ZONE', '(unset)'))
print('USE_TZ           : %s' % getattr(settings, 'USE_TZ', '(unset)'))
print('now() in that zone: %s' % timezone.localtime().strftime('%d.%m.%Y %H:%M'))
print()

ABFRAGE = """
    SELECT p.id, p.title, p.post_scheduled_at,
           b.buffer_post_id, b.status, b.sent_at, b.due_at, b.updated_at
    FROM planner_posts p
    LEFT JOIN buffer_posts_posted b ON b.planner_post_id = p.id
    WHERE p.status = 'Scheduled'
    ORDER BY p.post_scheduled_at
"""

with connection.cursor() as zeiger:
    try:
        zeiger.execute(ABFRAGE)
    except Exception as fehler:
        if 'due_at' in str(fehler):
            print('The due_at column is missing. Run the sync once, it adds it:')
            print('    python manage.py fetch_buffer_posts')
            sys.exit(2)
        raise
    zeilen = zeiger.fetchall()

if not zeilen:
    print('No post is in Scheduled.')
    sys.exit(0)

print('%d post(s) in Scheduled:\n' % len(zeilen))
for kennung, titel, geplant, bpid, bstatus, gesendet, faellig, aktualisiert in zeilen:
    print('#%-5s %s' % (kennung, (titel or '')[:60]))
    print('   planned for  : %s' % (geplant or '-'))
    if not bpid:
        print('   Buffer       : NOT LINKED - no row in buffer_posts_posted carries')
        print('                  this post id. The sync can never find it, whatever')
        print('                  Buffer says. Was it posted through the planner?')
    else:
        gesendet_laut = (str(bstatus or '').lower() == 'sent') or bool(gesendet)
        print('   Buffer id    : %s' % bpid)
        print('   Buffer status: %s' % (bstatus or '(empty)'))
        print('   sent_at      : %s' % (gesendet or '(empty)'))
        print('   due_at       : %s' % (faellig or '(empty)'))
        print('   last sync    : %s' % (aktualisiert or '-'))
        if gesendet_laut:
            print('   -> Buffer says SENT. It should have been promoted; so the sync')
            print('      has not run since. Trigger it: python manage.py fetch_buffer_posts')
        else:
            print('   -> Buffer does NOT report it as sent. Either it really has not')
            print('      gone out, or Buffer supplies neither a status of "sent" nor a')
            print('      sent_at - in which case the promotion rule needs widening.')
    print()
