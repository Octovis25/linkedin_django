#!/bin/bash
# fix_statistics_cleanup.sh
# 1) Loescht die alte views.py aus linkedin_statistics/
# 2) Stellt sicher dass NUR stat_views.py existiert
# 3) Korrigiert urls.py Import
# 4) Prueft alle Referenzen im gesamten Projekt
set -e

echo "╔══════════════════════════════════════════════════════════╗"
echo "║  CLEANUP: linkedin_statistics - views.py entfernen      ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

STAT_DIR="linkedin_statistics"

# ── 1. Aktuelle Lage zeigen ──────────────────────────────────
echo "=== 1. Aktuelle Dateien in ${STAT_DIR}/ ==="
ls -la "${STAT_DIR}/"
echo ""

# ── 2. views.py loeschen ────────────────────────────────────
if [ -f "${STAT_DIR}/views.py" ]; then
    echo "=== 2. LOESCHE ${STAT_DIR}/views.py ==="
    rm -f "${STAT_DIR}/views.py"
    rm -f "${STAT_DIR}/__pycache__/views.cpython-*.pyc" 2>/dev/null || true
    echo "  ✅ views.py geloescht"
else
    echo "=== 2. ${STAT_DIR}/views.py existiert nicht (gut!) ==="
fi
echo ""

# ── 3. __pycache__ komplett loeschen (alte .pyc raus) ────────
echo "=== 3. __pycache__ aufraeumen ==="
find "${STAT_DIR}" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
echo "  ✅ __pycache__ geloescht"
echo ""

# ── 4. Pruefen ob stat_views.py existiert ────────────────────
echo "=== 4. stat_views.py pruefen ==="
if [ -f "${STAT_DIR}/stat_views.py" ]; then
    echo "  ✅ stat_views.py existiert"
    head -5 "${STAT_DIR}/stat_views.py"
else
    echo "  ❌ FEHLER: stat_views.py fehlt! Bitte erst write_statistics_files.py ausfuehren!"
    exit 1
fi
echo ""

# ── 5. urls.py korrigieren ──────────────────────────────────
echo "=== 5. urls.py pruefen und korrigieren ==="
cat > "${STAT_DIR}/urls.py" << 'URLEOF'
from django.urls import path
from . import stat_views

app_name = 'linkedin_statistics'

urlpatterns = [
    path('',                        stat_views.overview,         name='overview'),
    path('timeline/',               stat_views.timeline,         name='timeline'),
    path('timeline/<str:post_id>/', stat_views.timeline_detail,  name='timeline_detail'),
]
URLEOF
echo "  ✅ urls.py geschrieben (importiert stat_views)"
echo ""

# ── 6. Gesamtes Projekt nach falschen Importen durchsuchen ───
echo "=== 6. Suche nach 'from . import views' oder 'from linkedin_statistics import views' ==="
echo "    (sollte NICHTS finden!)"
grep -rn "from.*linkedin_statistics.*import views" . --include="*.py" 2>/dev/null | grep -v "__pycache__" | grep -v ".pyc" || echo "  ✅ Keine falschen Imports gefunden"
grep -rn "from \. import views" "${STAT_DIR}/" --include="*.py" 2>/dev/null | grep -v "__pycache__" || echo "  ✅ Keine 'from . import views' in ${STAT_DIR}/"
echo ""

# ── 7. Haupt-urls.py / settings.py pruefen ──────────────────
echo "=== 7. Haupt-settings.py: linkedin_statistics in INSTALLED_APPS? ==="
grep -n "linkedin_statistics" */settings.py 2>/dev/null || grep -rn "linkedin_statistics" . --include="settings.py" 2>/dev/null | grep -v __pycache__ || echo "  ⚠️  NICHT GEFUNDEN - muss in INSTALLED_APPS stehen!"
echo ""

echo "=== 8. Haupt-urls.py: include linkedin_statistics? ==="
grep -rn "linkedin_statistics" . --include="urls.py" 2>/dev/null | grep -v __pycache__ | grep -v "${STAT_DIR}/urls.py" || echo "  ⚠️  NICHT GEFUNDEN - muss in Haupt-urls.py stehen!"
echo ""

# ── 9. apps.py pruefen ──────────────────────────────────────
echo "=== 9. apps.py pruefen ==="
if [ -f "${STAT_DIR}/apps.py" ]; then
    cat "${STAT_DIR}/apps.py"
else
    echo "  ⚠️  apps.py fehlt - erzeuge..."
    cat > "${STAT_DIR}/apps.py" << 'APPEOF'
from django.apps import AppConfig

class LinkedinStatisticsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'linkedin_statistics'
    verbose_name = 'LinkedIn Statistics'
APPEOF
    echo "  ✅ apps.py erzeugt"
fi
echo ""

# ── 10. __init__.py pruefen ─────────────────────────────────
echo "=== 10. __init__.py pruefen ==="
if [ ! -f "${STAT_DIR}/__init__.py" ]; then
    touch "${STAT_DIR}/__init__.py"
    echo "  ✅ __init__.py erzeugt"
else
    echo "  ✅ __init__.py existiert"
fi
echo ""

# ── 11. Templates pruefen ──────────────────────────────────
echo "=== 11. Templates pruefen ==="
TPL_DIR="${STAT_DIR}/templates/linkedin_statistics"
if [ -d "${TPL_DIR}" ]; then
    ls -la "${TPL_DIR}/"
else
    echo "  ❌ Template-Verzeichnis fehlt! Bitte write_statistics_files.py ausfuehren!"
fi
echo ""

# ── 12. Endergebnis ─────────────────────────────────────────
echo "╔══════════════════════════════════════════════════════════╗"
echo "║  ERGEBNIS: Dateien in ${STAT_DIR}/                      ║"
echo "╚══════════════════════════════════════════════════════════╝"
ls -la "${STAT_DIR}/"
echo ""
echo "Naechste Schritte:"
echo "  git add -A"
echo "  git commit -m 'fix: views.py geloescht, nur stat_views.py bleibt'"
echo "  git push"
echo ""
echo "Falls Fehler auftreten, stehen sie jetzt im Server-Log!"
echo "  python manage.py check"
