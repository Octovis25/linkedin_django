#!/bin/bash
# deploy_statistics_fix.sh
# Kopiert korrigierte views.py + overview.html auf den Server
set -e
cd /opt/render/project/src 2>/dev/null || cd "$(dirname "$0")"

STAT_APP="linkedin_statistics"
STAT_TPL="${STAT_APP}/templates/${STAT_APP}"
mkdir -p "${STAT_TPL}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== 1. Diagnose ==="
bash "${SCRIPT_DIR}/diagnose.sh" 2>&1 | head -80

echo ""
echo "=== 2. views.py deployen ==="
cp "${SCRIPT_DIR}/views.py" "${STAT_APP}/views.py"
echo "  ✅ views.py"

echo "=== 3. overview.html deployen ==="
cp "${SCRIPT_DIR}/overview.html" "${STAT_TPL}/overview.html"
echo "  ✅ overview.html"

echo "=== 4. urls.py sicherstellen ==="
cat > "${STAT_APP}/urls.py" << 'URLEOF'
from django.urls import path
from . import views

app_name = 'linkedin_statistics'

urlpatterns = [
    path('',                        views.overview,         name='overview'),
    path('timeline/',               views.timeline,         name='timeline'),
    path('timeline/<str:post_id>/', views.timeline_detail,  name='timeline_detail'),
]
URLEOF
echo "  ✅ urls.py"

echo ""
echo "=== 5. Neustart ==="
supervisorctl restart web 2>/dev/null || \
  pkill -HUP -f gunicorn 2>/dev/null || true
sleep 2

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║  ✅ STATISTICS FIX DEPLOYED                              ║"
echo "║                                                          ║"
echo "║  Prüfe oben die Diagnose-Ausgabe:                       ║"
echo "║  • Zeigt linkedin_posts_metrics Zeilen > 0?             ║"
echo "║  • Zeigt linkedin_followers Zeilen > 0?                 ║"
echo "║  • Zeigt linkedin_content_metrics Zeilen > 0?           ║"
echo "╚══════════════════════════════════════════════════════════╝"
