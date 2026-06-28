"""
Holt einmal täglich (nachts) die Post-Statistiken aus Buffer und speichert sie
in der Tabelle buffer_post_metrics. Buffer aktualisiert die Metriken ohnehin nur
einmal pro Tag, daher reicht ein nächtlicher Lauf.

Aufruf:
    python manage.py fetch_buffer_stats

Buffer-Token wird aus planner_linkedin_tokens (Superuser) gelesen — derselbe
Token, der auch zum Posten verwendet wird.
"""
from django.core.management.base import BaseCommand
from django.db import connection


def _ensure_metrics_table():
    with connection.cursor() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS buffer_post_metrics (
                id INT AUTO_INCREMENT PRIMARY KEY,
                fetched_date DATE NOT NULL,
                buffer_post_id VARCHAR(100) NOT NULL,
                channel_id VARCHAR(100),
                sent_at VARCHAR(64),
                status VARCHAR(50),
                metric_type VARCHAR(100),
                metric_name VARCHAR(200),
                metric_value DOUBLE DEFAULT 0,
                metric_unit VARCHAR(50),
                metrics_updated_at VARCHAR(64),
                planner_post_id INT DEFAULT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY uniq_day_post_metric (fetched_date, buffer_post_id, metric_type)
            )
        """)


def _get_buffer_token():
    """Buffer-Token des Superusers holen (gleiche Quelle wie beim Posten)."""
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


def _map_planner_post_id(buffer_post_id):
    """Falls der Buffer-Post zu einem Planner-Post gehört, dessen id finden."""
    with connection.cursor() as c:
        try:
            c.execute("SELECT id FROM planner_posts WHERE buffer_update_id=%s LIMIT 1",
                      [buffer_post_id])
            row = c.fetchone()
            return row[0] if row else None
        except Exception:
            return None


class Command(BaseCommand):
    help = "Holt Post-Statistiken aus Buffer und speichert sie in buffer_post_metrics."

    def add_arguments(self, parser):
        parser.add_argument('--first', type=int, default=50,
                            help='Anzahl der zuletzt gesendeten Posts, die abgefragt werden (Standard 50).')
        parser.add_argument('--token', type=str, default=None,
                            help='Buffer-Token direkt angeben (sonst aus DB).')

    def handle(self, *args, **options):
        # Import hier, um Django-Setup-Reihenfolge sicherzustellen.
        from planner.views import (_buffer_first_org_id, _buffer_fetch_post_metrics)
        from datetime import date

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
            posts = _buffer_fetch_post_metrics(buf_token, org_id, first=options['first'])
        except Exception as e:
            self.stderr.write(f"Buffer-Metriken konnten nicht geladen werden: {e}")
            return

        _ensure_metrics_table()
        today = date.today()
        rows_written = 0
        posts_with_metrics = 0

        with connection.cursor() as c:
            for p in posts:
                bpid = p.get('buffer_post_id')
                if not bpid:
                    continue
                metrics = p.get('metrics') or []
                if metrics:
                    posts_with_metrics += 1
                planner_id = _map_planner_post_id(bpid)
                for m in metrics:
                    c.execute("""
                        INSERT INTO buffer_post_metrics
                            (fetched_date, buffer_post_id, channel_id, sent_at, status,
                             metric_type, metric_name, metric_value, metric_unit,
                             metrics_updated_at, planner_post_id)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        ON DUPLICATE KEY UPDATE
                            metric_value=VALUES(metric_value),
                            metric_name=VALUES(metric_name),
                            metric_unit=VALUES(metric_unit),
                            metrics_updated_at=VALUES(metrics_updated_at),
                            channel_id=VALUES(channel_id),
                            sent_at=VALUES(sent_at),
                            status=VALUES(status),
                            planner_post_id=VALUES(planner_post_id)
                    """, [
                        today, bpid, p.get('channel_id'), p.get('sent_at'), p.get('status'),
                        m.get('type'), m.get('name'), m.get('value') or 0, m.get('unit'),
                        p.get('metrics_updated_at'), planner_id,
                    ])
                    rows_written += 1

        self.stdout.write(self.style.SUCCESS(
            f"Buffer-Statistik abgeholt: {len(posts)} Posts, {posts_with_metrics} mit Metriken, "
            f"{rows_written} Metrik-Zeilen gespeichert (Datum {today})."
        ))
