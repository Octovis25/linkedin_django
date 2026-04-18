#!/bin/bash
set -e
echo "=== Fix: Statistik in Navigation + Sub-Nav ==="

BASE="templates/base.html"

# 1) Statistik-Link in Haupt-Nav ergänzen (nach Collectives)
sed -i 's|<a href="/collectives/" {% if '"'"'/collectives/'"'"' in request.path %}class="active"{% endif %}>Collectives</a>|<a href="/collectives/" {% if '"'"'/collectives/'"'"' in request.path %}class="active"{% endif %}>Collectives</a>\n    <a href="/statistics/" {% if '"'"'/statistics/'"'"' in request.path %}class="active"{% endif %}>Statistik</a>|' "$BASE"

# 2) Sub-Nav für Statistics hinzufügen (nach dem Data-Sub-Nav-Block)
# Sucht den {% endif %} nach dem /data/ Sub-Nav-Block und fügt Statistics-Block davor ein
python3 - << 'PYEOF'
with open("templates/base.html", "r") as f:
    content = f.read()

# Prüfen ob schon vorhanden
if "linkedin_statistics:overview" in content:
    print("Statistics Sub-Nav bereits vorhanden – skip.")
else:
    statistics_subnav = """
  {% if '/statistics/' in request.path %}
  <div class="sub-nav">
    <a href="{% url 'linkedin_statistics:overview' %}" {% if request.path == '/statistics/' or 'overview' in request.path %}class="active"{% endif %}>Übersicht</a>
    <a href="{% url 'linkedin_statistics:timeline' %}" {% if 'timeline' in request.path %}class="active"{% endif %}>Timeline</a>
  </div>
  {% endif %}"""

    # Nach dem bestehenden {% endif %} des data-Sub-Nav einfügen
    content = content.replace(
        "{% endif %}\n\n  {% if messages %}",
        "{% endif %}" + statistics_subnav + "\n\n  {% if messages %}"
    )
    with open("templates/base.html", "w") as f:
        f.write(content)
    print("Statistics Sub-Nav erfolgreich eingefügt.")
PYEOF

echo ""
echo "=== Ergebnis: Nav-Links ==="
grep -n "statistic\|Statistik\|Collectives" templates/base.html

echo ""
echo "=== Fertig! Bitte Server neu starten ==="
