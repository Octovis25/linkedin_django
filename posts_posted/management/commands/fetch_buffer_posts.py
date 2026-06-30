"""
Holt die Posts aus Buffer (ohne Metriken, kommt mit posts:read aus) und
speichert sie in der Tabelle buffer_posts_posted. Der Tab 'Buffer Posts Posted'
liest NUR aus dieser Tabelle -> schnell und unabhaengig vom Internet.

Aufruf:
    python manage.py fetch_buffer_posts
    python manage.py fetch_buffer_posts --token <TOKEN>

Buffer-Token wird aus planner_linkedin_tokens (Superuser) gelesen -- derselbe
Token, der auch zum Posten verwendet wird.
"""
from django.core.management.base import BaseCommand
from django.db import connection


def _ensure_table():
    with connection.cursor() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS buffer_posts_posted (
                id INT AUTO_INCREMENT PRIMARY KEY,
                buffer_post_id VARCHAR(100) NOT NULL UNIQUE,
                channel_id VARCHAR(100),
                post_text TEXT,
                status VARCHAR(50),
                sent_at VARCHAR(64),
                planner_post_id INT DEFAULT NULL,
                has_image TINYINT DEFAULT 0,
                linkedin_url TEXT,
                thumbnail_url TEXT,
                fetched_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            )
        """)
        # Migration: Spalte ergaenzen falls Tabelle schon ohne sie existiert.
        try:
            c.execute("ALTER TABLE buffer_posts_posted ADD COLUMN thumbnail_url TEXT")
        except Exception:
            pass


def _get_buffer_token():
    with connection.cursor() as c:
        try:
            c.execute("""
                SELECT t.buffer_token
                FROM planner_linkedin_tokens t
                JOIN auth_user u ON t.user_id = u.id
                WHERE u.is_superuser = 1 AND t.buffer_token IS NOT NULL
                LIMIT 1
            """)
            row = c.fetchone()
            return row[0] if row else None
        except Exception:
            return None


def _planner_lookup(buffer_post_id):
    """Bild + LinkedIn-Link aus planner_posts holen (ueber buffer_update_id)."""
    with connection.cursor() as c:
        try:
            c.execute(
                "SELECT id, image, link FROM planner_posts WHERE buffer_update_id=%s LIMIT 1",
                [buffer_post_id],
            )
            row = c.fetchone()
            if not row:
                return None, 0, ''
            pid, image, link = row
            return pid, (1 if image else 0), (link or '')
        except Exception:
            return None, 0, ''


class Command(BaseCommand):
    help = "Holt Buffer-Posts und speichert sie in buffer_posts_posted."

    def add_arguments(self, parser):
        parser.add_argument('--token', type=str, default=None,
                            help='Buffer-Token direkt angeben (sonst aus DB).')
        parser.add_argument('--first', type=int, default=50,
                            help='Posts pro Seite (Standard 50).')

    def handle(self, *args, **options):
        from planner.views import _buffer_first_org_id, _buffer_fetch_posts_basic

        buf_token = options.get('token') or _get_buffer_token()
        if not buf_token:
            self.stderr.write("Kein Buffer-Token (--token angeben oder in DB speichern). Abbruch.")
            return

        try:
            org_id = _buffer_first_org_id(buf_token)
        except Exception as e:
            self.stderr.write(f"Buffer-Organisation konnte nicht geladen werden: {e}")
            return
        if not org_id:
            self.stderr.write("Keine Buffer-Organisation gefunden. Abbruch.")
            return

        try:
            posts = _buffer_fetch_posts_basic(buf_token, org_id, first=options['first'], all_pages=True)
        except Exception as e:
            self.stderr.write(f"Buffer-Posts konnten nicht geladen werden: {e}")
            return

        _ensure_table()
        written = 0
        with connection.cursor() as c:
            for p in posts:
                bpid = p.get('buffer_post_id')
                if not bpid:
                    continue
                # Fallback aus planner_posts (falls Post ueber den Planner lief).
                pid, planner_has_image, planner_link = _planner_lookup(bpid)
                # Bild + Link bevorzugt direkt aus Buffer.
                thumb = p.get('thumbnail_url') or ''
                link = p.get('external_link') or planner_link or ''
                has_image = 1 if (thumb or planner_has_image) else 0
                c.execute("""
                    INSERT INTO buffer_posts_posted
                        (buffer_post_id, channel_id, post_text, status, sent_at,
                         planner_post_id, has_image, linkedin_url, thumbnail_url)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON DUPLICATE KEY UPDATE
                        channel_id=VALUES(channel_id),
                        post_text=VALUES(post_text),
                        status=VALUES(status),
                        sent_at=VALUES(sent_at),
                        planner_post_id=VALUES(planner_post_id),
                        has_image=VALUES(has_image),
                        linkedin_url=VALUES(linkedin_url),
                        thumbnail_url=VALUES(thumbnail_url)
                """, [
                    bpid, p.get('channel_id'), (p.get('text') or '')[:5000],
                    p.get('status'), p.get('sent_at'),
                    pid, has_image, link, thumb,
                ])
                written += 1

        self.stdout.write(self.style.SUCCESS(
            f"Buffer-Posts gespeichert: {written} Posts in buffer_posts_posted."
        ))
