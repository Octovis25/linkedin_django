#!/bin/bash
# diagnose.sh - Zeigt genau was in der DB steht
# Ausführen: bash diagnose.sh
cd /opt/render/project/src 2>/dev/null || cd "$(dirname "$0")"

python3 - << 'PYEOF'
import os, sys
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dashboard.settings')
import django; django.setup()
from django.db import connection

def q(sql, label=""):
    with connection.cursor() as c:
        try:
            c.execute(sql)
            rows = c.fetchall()
            cols = [d[0] for d in c.description]
            print(f"\n=== {label} ===")
            print(" | ".join(cols))
            print("-" * 60)
            for r in rows[:5]:
                print(" | ".join(str(x) for x in r))
            print(f"  → {len(rows)} Zeile(n)")
        except Exception as e:
            print(f"\n=== {label} ===  FEHLER: {e}")

# Tabellen prüfen
q("SHOW TABLES", "Alle Tabellen")
q("SELECT COUNT(*) AS n FROM linkedin_posts", "linkedin_posts Zeilen")
q("SELECT COUNT(*) AS n FROM linkedin_posts_metrics", "linkedin_posts_metrics Zeilen")
q("SELECT COUNT(*) AS n FROM linkedin_followers", "linkedin_followers Zeilen")
q("SELECT COUNT(*) AS n FROM linkedin_content_metrics", "linkedin_content_metrics Zeilen")

# Spalten prüfen
q("DESCRIBE linkedin_posts", "Spalten: linkedin_posts")
q("DESCRIBE linkedin_posts_metrics", "Spalten: linkedin_posts_metrics")
q("DESCRIBE linkedin_followers", "Spalten: linkedin_followers")
q("DESCRIBE linkedin_content_metrics", "Spalten: linkedin_content_metrics")

# Stichproben
q("""
  SELECT post_id, metric_date, impressions, clicks, likes, comments, direct_shares
  FROM linkedin_posts_metrics ORDER BY metric_date DESC LIMIT 3
""", "Letzte Metriken")

q("""
  SELECT date, followers_total FROM linkedin_followers ORDER BY date DESC LIMIT 3
""", "Letzte Follower-Zahlen")
PYEOF
