#!/bin/bash
# ============================================================
# FIX_STATISTICS_DEFINITIVE.sh
# Behebt ALLE Statistics-Probleme auf einmal:
# 1. base.html → Statistics-Link in Nav + Subnav
# 2. settings.py → linkedin_statistics in INSTALLED_APPS
# 3. dashboard/urls.py → Statistics-URLs eingebunden
# 4. linkedin_statistics App-Dateien sauber setzen
# ============================================================

set -e

# ── Projektpfad ermitteln ──────────────────────────────────
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
echo "📁 Projektverzeichnis: $PROJECT_DIR"

# Haupt-Django-Konfig ermitteln
DASHBOARD_DIR="$PROJECT_DIR/dashboard"
if [ ! -d "$DASHBOARD_DIR" ]; then
  echo "❌ dashboard/-Verzeichnis nicht gefunden. Script muss im Projektwurzel-Verzeichnis liegen."
  exit 1
fi

# ── 1. base.html finden und patchen ───────────────────────
echo ""
echo "🔧 SCHRITT 1: base.html – Statistics-Link + Subnav"
BASE_HTML=$(find "$PROJECT_DIR" -name "base.html" | grep -v ".git" | grep -v "node_modules" | head -1)
echo "   Gefunden: $BASE_HTML"

cat > "$BASE_HTML" << 'BASE_EOF'
{% load static %}
<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{% block title %}LinkedIn Dashboard{% endblock %}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link href="https://fonts.googleapis.com/css2?family=Roboto:wght@400;500;700&display=swap" rel="stylesheet" />
  <style>
    :root {
      --octo-petrol:      #008591;
      --octo-turquoise:   #61CEBC;
      --octo-orange:      #F56E28;
      --octo-dark-petrol: #005F68;
      --octo-text:        #161616;
      --octo-white:       #FFFFFF;
      --octo-light-gray:  #F9F7F0;
    }

    * { margin: 0; padding: 0; box-sizing: border-box; }

    body {
      font-family: 'Roboto', Arial, sans-serif;
      background-color: var(--octo-white);
      color: var(--octo-text);
      line-height: 1.4;
      font-size: 14px;
    }

    /* ── HEADER ── */
    header {
      background-color: var(--octo-white);
      border-bottom: 2px solid var(--octo-petrol);
      padding: 0.5rem 1.5rem;
    }

    .header-top {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 0.5rem;
    }

    .logo { height: 40px; }

    .user-section {
      display: flex;
      gap: 1.5rem;
      align-items: center;
      font-size: 14px;
    }

    .user-info {
      color: var(--octo-dark-petrol);
      font-weight: 500;
    }

    .user-section a {
      color: var(--octo-petrol);
      text-decoration: none;
      font-weight: 500;
      transition: color 0.3s;
    }

    .user-section a:hover { color: var(--octo-orange); }

    /* ── NAVIGATION ── */
    nav {
      display: flex;
      gap: 0;
      border-bottom: 2px solid var(--octo-light-gray);
    }

    nav a {
      color: var(--octo-petrol);
      text-decoration: none;
      font-weight: 500;
      padding: 0.5rem 1rem;
      border-bottom: 3px solid transparent;
      transition: all 0.3s;
    }

    nav a:hover,
    nav a.active {
      color: var(--octo-orange);
      border-bottom-color: var(--octo-orange);
    }

    /* ── SUB-NAV ── */
    .sub-nav {
      display: flex;
      gap: 0;
      background: var(--octo-light-gray);
      padding: 0 1.5rem;
    }

    .sub-nav a {
      color: var(--octo-dark-petrol);
      padding: 0.4rem 1rem;
      font-size: 0.9rem;
      text-decoration: none;
      border-bottom: 2px solid transparent;
    }

    .sub-nav a:hover,
    .sub-nav a.active {
      color: var(--octo-orange);
      border-bottom-color: var(--octo-orange);
    }

    /* ── MAIN ── */
    main {
      max-width: 1400px;
      margin: 1rem auto;
      padding: 0 1.5rem;
    }

    h1, h2, h3 { color: var(--octo-petrol); margin-bottom: 0.75rem; font-size: 1.3rem; }
    h2 { font-size: 1.1rem; }

    /* ── BUTTONS ── */
    .btn {
      display: inline-block;
      padding: 0.4rem 1rem;
      border: none;
      border-radius: 6px;
      font-size: 0.9rem;
      font-weight: 500;
      cursor: pointer;
      text-decoration: none;
      transition: all 0.3s;
    }
    .btn-primary   { background-color: var(--octo-petrol);  color: var(--octo-white); }
    .btn-primary:hover { background-color: var(--octo-dark-petrol); }
    .btn-secondary { background-color: var(--octo-orange);  color: var(--octo-white); }
    .btn-secondary:hover { background-color: #d55a1f; }
    .btn-danger    { background-color: #dc3545; color: var(--octo-white); }
    .btn-danger:hover { background-color: #c82333; }
    .btn-sm { padding: 0.3rem 0.75rem; font-size: 0.85rem; }

    /* ── TABLE ── */
    table {
      width: 100%;
      border-collapse: collapse;
      background-color: var(--octo-white);
      box-shadow: 0 1px 3px rgba(0,0,0,0.1);
      border-radius: 6px;
      overflow: hidden;
      font-size: 0.9rem;
    }
    thead { background-color: var(--octo-petrol); color: var(--octo-white); }
    th, td { padding: 0.6rem 0.8rem; text-align: left; border-bottom: 1px solid var(--octo-light-gray); }
    tr:hover { background-color: var(--octo-light-gray); }

    /* ── FORMS ── */
    .form-group { margin-bottom: 1rem; }

    label {
      display: block;
      color: var(--octo-petrol);
      font-weight: 500;
      margin-bottom: 0.3rem;
      font-size: 0.9rem;
    }

    input[type="text"],
    input[type="url"],
    input[type="date"],
    input[type="file"],
    input[type="datetime-local"],
    input[type="password"],
    select {
      width: 100%;
      padding: 0.5rem;
      border: 2px solid var(--octo-light-gray);
      border-radius: 6px;
      font-size: 0.9rem;
      transition: border-color 0.3s;
    }

    input:focus, select:focus {
      outline: none;
      border-color: var(--octo-orange);
    }

    /* ── ALERTS ── */
    .messages { margin: 0.75rem 0; }

    .alert {
      padding: 0.75rem;
      border-radius: 6px;
      margin-bottom: 0.75rem;
      font-size: 0.9rem;
    }
    .alert-success { background-color: #d4edda; color: #155724; border: 1px solid #c3e6cb; }
    .alert-error   { background-color: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }
    .alert-info    { background-color: #d1ecf1; color: #0c5460; border: 1px solid #bee5eb; }

    /* ── CARD ── */
    .card {
      background-color: var(--octo-white);
      border-radius: 6px;
      box-shadow: 0 1px 4px rgba(0,0,0,0.1);
      padding: 1.25rem;
      margin-bottom: 1.25rem;
    }

    a { color: var(--octo-petrol); transition: color 0.3s; }
    a:hover { color: var(--octo-orange); }

    /* ── FOOTER ── */
    footer {
      background-color: var(--octo-light-gray);
      color: var(--octo-text);
      text-align: center;
      padding: 0.75rem;
      margin-top: 2rem;
      border-top: 2px solid var(--octo-petrol);
      font-size: 0.85rem;
    }
  </style>
</head>
<body>

<header>
  <div class="header-top">
    <a href="/">
      <img src="{% static 'images/octovis_logo--1-.png' %}" alt="Octovis Logo" class="logo" />
    </a>

    <div class="user-section">
      {% if user.is_authenticated %}
        {% if user.is_superuser %}
          <a href="/users/">User-Verwaltung</a>
        {% endif %}
        <span class="user-info">{{ user.get_full_name|default:user.username }}</span>
        <a href="/change-password/">Passwort ändern</a>
        <a href="/logout/">Logout</a>
      {% else %}
        <a href="/login/">Login</a>
      {% endif %}
    </div>
  </div>

  <nav>
    <a href="/" {% if request.path == '/' %}class="active"{% endif %}>Dashboard</a>
    <a href="/data/posts/" {% if '/data/' in request.path %}class="active"{% endif %}>Data</a>
    <a href="/collectives/" {% if '/collectives/' in request.path %}class="active"{% endif %}>Collectives</a>
    <a href="/statistics/" {% if '/statistics/' in request.path %}class="active"{% endif %}>Statistics</a>
  </nav>

  {% if '/data/' in request.path %}
  <div class="sub-nav">
    <a href="/data/posts/" {% if request.path == '/data/posts/' %}class="active"{% endif %}>Posts Posted</a>
    <a href="/data/upload/" {% if request.path == '/data/upload/' %}class="active"{% endif %}>Upload Data</a>
  </div>
  {% endif %}

  {% if '/statistics/' in request.path %}
  <div class="sub-nav">
    <a href="/statistics/" {% if request.path == '/statistics/' %}class="active"{% endif %}>Overview</a>
    <a href="/statistics/timeline/" {% if '/statistics/timeline' in request.path %}class="active"{% endif %}>Timeline</a>
  </div>
  {% endif %}

</header>

<main>
  {% if messages %}
  <div class="messages">
    {% for message in messages %}
    <div class="alert alert-{{ message.tags }}">{{ message }}</div>
    {% endfor %}
  </div>
  {% endif %}

  {% block content %}{% endblock %}
</main>

<footer>
  © 2026 Octotrial | LinkedIn Dashboard
</footer>

{% block extra_js %}{% endblock %}

</body>
</html>
BASE_EOF

echo "   ✅ base.html gesetzt"

# ── 2. settings.py – linkedin_statistics in INSTALLED_APPS ─
echo ""
echo "🔧 SCHRITT 2: settings.py – linkedin_statistics hinzufügen"
SETTINGS_FILE="$DASHBOARD_DIR/settings.py"
if [ ! -f "$SETTINGS_FILE" ]; then
  SETTINGS_FILE=$(find "$PROJECT_DIR" -name "settings.py" | grep -v ".git" | head -1)
fi
echo "   Gefunden: $SETTINGS_FILE"

# Nur hinzufügen wenn noch nicht vorhanden
if grep -q "linkedin_statistics" "$SETTINGS_FILE"; then
  echo "   ℹ️  linkedin_statistics bereits in INSTALLED_APPS"
else
  # Nach 'collectives' einfügen (oder ans Ende der INSTALLED_APPS)
  python3 - "$SETTINGS_FILE" << 'PYEOF'
import sys, re

path = sys.argv[1]
with open(path, 'r') as f:
    content = f.read()

# Ersetze collectives', durch collectives', 'linkedin_statistics',
new_content = re.sub(
    r"'collectives'(\s*,?\s*\])",
    "'collectives',\n    'linkedin_statistics',\n]",
    content
)

# Falls collectives nicht gefunden, nach letztem Eintrag
if new_content == content:
    new_content = re.sub(
        r'(\]\s*\nMIDDLEWARE)',
        "    'linkedin_statistics',\n]\nMIDDLEWARE",
        content
    )

with open(path, 'w') as f:
    f.write(new_content)
print("   Done")
PYEOF
  echo "   ✅ linkedin_statistics zu INSTALLED_APPS hinzugefügt"
fi

# ── 3. dashboard/urls.py – Statistics einbinden ───────────
echo ""
echo "🔧 SCHRITT 3: dashboard/urls.py – Statistics-URLs einbinden"
MAIN_URLS="$DASHBOARD_DIR/urls.py"
if [ ! -f "$MAIN_URLS" ]; then
  echo "   ❌ $MAIN_URLS nicht gefunden"
  exit 1
fi

echo "   Gefunden: $MAIN_URLS"
cat "$MAIN_URLS"

if grep -q "statistics" "$MAIN_URLS"; then
  echo "   ℹ️  Statistics-URL bereits vorhanden"
else
  python3 - "$MAIN_URLS" << 'PYEOF'
import sys, re

path = sys.argv[1]
with open(path, 'r') as f:
    content = f.read()

# Statistics-Import hinzufügen nach letztem Import
if 'linkedin_statistics' not in content:
    content = re.sub(
        r'(from django\.urls import.*\n)',
        r'\1from linkedin_statistics import stat_views\n',
        content,
        count=1
    )

# Statistics-URL-Zeilen einfügen vor der schließenden Klammer der urlpatterns
if 'statistics' not in content:
    content = re.sub(
        r'(\])\s*$',
        "    path('statistics/', stat_views.overview, name='stat_overview'),\n"
        "    path('statistics/timeline/', stat_views.timeline, name='stat_timeline'),\n"
        "    path('statistics/timeline/<int:post_id>/', stat_views.timeline_detail, name='stat_timeline_detail'),\n"
        "]",
        content.rstrip()
    )

with open(path, 'w') as f:
    f.write(content)
print("   Done")
PYEOF
  echo "   ✅ Statistics-URLs hinzugefügt"
fi

# ── 4. linkedin_statistics App-Struktur sicherstellen ──────
echo ""
echo "🔧 SCHRITT 4: linkedin_statistics App-Struktur prüfen"
STAT_DIR="$PROJECT_DIR/linkedin_statistics"

if [ ! -d "$STAT_DIR" ]; then
  echo "   Erstelle $STAT_DIR ..."
  mkdir -p "$STAT_DIR/templates/linkedin_statistics"
  touch "$STAT_DIR/__init__.py"
  cat > "$STAT_DIR/apps.py" << 'APPSEOF'
from django.apps import AppConfig
class LinkedinStatisticsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'linkedin_statistics'
APPSEOF
fi

# stat_views.py kopieren wenn nicht vorhanden
if [ ! -f "$STAT_DIR/stat_views.py" ]; then
  echo "   ⚠️  stat_views.py fehlt – bitte manuell von /linkedin_statistics/stat_views.py kopieren"
else
  echo "   ✅ stat_views.py vorhanden"
fi

# Templates prüfen
TMPL_DIR="$STAT_DIR/templates/linkedin_statistics"
mkdir -p "$TMPL_DIR"

if [ ! -f "$TMPL_DIR/stat_overview.html" ]; then
  echo "   ⚠️  stat_overview.html fehlt im Template-Verzeichnis"
fi
if [ ! -f "$TMPL_DIR/stat_timeline.html" ]; then
  echo "   ⚠️  stat_timeline.html fehlt im Template-Verzeichnis"
fi

# ── 5. Zusammenfassung ────────────────────────────────────
echo ""
echo "════════════════════════════════════════════════"
echo "✅ FIX ABGESCHLOSSEN"
echo ""
echo "Bitte jetzt auf dem Server:"
echo "  python manage.py collectstatic --noinput"
echo "  → Render baut automatisch neu (git push)"
echo "════════════════════════════════════════════════"
