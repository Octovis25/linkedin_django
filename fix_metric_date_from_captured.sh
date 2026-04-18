#!/bin/bash
##############################################################
# fix_metric_date_from_captured.sh
# FIX: metric_date muss DATE(captured_at) sein, NICHT post_date!
# Sonst zeigt der Chart immer nur "Tag 1" weil alle Datenpunkte
# dasselbe Datum haben.
##############################################################
set -e
cd /opt/render/project/src 2>/dev/null || cd "$(dirname "$0")"

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  FIX: metric_date = DATE(captured_at)                       ║"
echo "║  Problem: Alle metric_date = post_date → immer 'Tag 1'      ║"
echo "║  Loesung: metric_date = DATE(captured_at) = echter Messtag   ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# ── SCHRITT 1: metric_date korrigieren ────────────────────────
echo "=== 1. metric_date aus captured_at berechnen ==="

python3 << 'PYEOF'
import os, django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from django.db import connection

print("--- VORHER: metric_date Verteilung ---")
with connection.cursor() as c:
    c.execute("""
        SELECT metric_date, COUNT(*) AS cnt
        FROM linkedin_posts_metrics
        GROUP BY metric_date
        ORDER BY metric_date
        LIMIT 20
    """)
    for row in c.fetchall():
        print(f"  {row[0]}  →  {row[1]} Zeilen")

print("")
print("--- FIX: metric_date = DATE(captured_at) ---")
with connection.cursor() as c:
    c.execute("""
        UPDATE linkedin_posts_metrics
        SET metric_date = DATE(captured_at)
        WHERE captured_at IS NOT NULL
    """)
    print(f"  Aktualisiert: {c.rowcount} Zeilen")

print("")
print("--- NACHHER: metric_date Verteilung ---")
with connection.cursor() as c:
    c.execute("""
        SELECT metric_date, COUNT(*) AS cnt
        FROM linkedin_posts_metrics
        GROUP BY metric_date
        ORDER BY metric_date
        LIMIT 20
    """)
    for row in c.fetchall():
        print(f"  {row[0]}  →  {row[1]} Zeilen")

print("")
print("--- Beispiel: Tagesverlauf fuer einen Post ---")
with connection.cursor() as c:
    # Einen Post mit mehreren Messpunkten finden
    c.execute("""
        SELECT m.post_id,
               COALESCE(pp.post_date, lp.post_date) AS post_date,
               COUNT(DISTINCT m.metric_date) AS tage
        FROM linkedin_posts_metrics m
        LEFT JOIN linkedin_posts lp ON m.post_id = lp.post_id
        LEFT JOIN linkedin_posts_posted pp ON m.post_id = pp.post_id
        GROUP BY m.post_id, post_date
        ORDER BY tage DESC
        LIMIT 3
    """)
    for row in c.fetchall():
        pid, pdate, tage = row
        print(f"  Post {pid}: post_date={pdate}, {tage} verschiedene Messtage")
        if pdate:
            c2 = connection.cursor()
            c2.execute("""
                SELECT DATEDIFF(metric_date, %s) + 1 AS tag, metric_date, impressions
                FROM linkedin_posts_metrics
                WHERE post_id = %s AND metric_date >= %s
                ORDER BY metric_date
                LIMIT 10
            """, [pdate, pid, pdate])
            for r2 in c2.fetchall():
                print(f"    Tag {r2[0]}: {r2[1]} → {r2[2]} Impressions")

print("")
print("=== FERTIG ===")
PYEOF

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  ✅  metric_date FIX angewendet!                            ║"
echo "║                                                              ║"
echo "║  Jetzt sollte der Timeline-Chart korrekte Tage zeigen:       ║"
echo "║  Tag 1, Tag 2, Tag 3, ... statt immer nur 'Tag 1'           ║"
echo "║                                                              ║"
echo "║  → Server neu starten: Render Dashboard → Manual Deploy      ║"
echo "║  → Dann /statistics/timeline/ pruefen                       ║"
echo "╚══════════════════════════════════════════════════════════════╝"
