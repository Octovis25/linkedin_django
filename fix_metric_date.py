import os, django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from django.db import connection

print("=== FIX: metric_date befuellen ===")
with connection.cursor() as c:
    c.execute("""
        UPDATE linkedin_posts_metrics pm
        JOIN linkedin_posts lp ON pm.post_id = lp.post_id
        SET pm.metric_date = lp.post_date
        WHERE pm.metric_date IS NULL
    """)
    print(f"Aktualisiert: {c.rowcount} Zeilen")

with connection.cursor() as c:
    c.execute("SELECT MIN(metric_date), MAX(metric_date), COUNT(*) FROM linkedin_posts_metrics")
    row = c.fetchone()
    print(f"Datum-Range: {row[0]} bis {row[1]} | Gesamt: {row[2]} Zeilen")

print("=== FERTIG ===")
