#!/bin/bash
# Behebt: TemplateSyntaxError – falsche Backslashes in Statistics-Link (base.html)
set -euo pipefail

BASE="core/templates/core/base.html"

echo "Patching $BASE ..."

python3 - << 'PYEOF'
import re

path = "core/templates/core/base.html"
with open(path, "r") as f:
    content = f.read()

# Entferne alle fehlerhaften Statistics-Varianten (mit oder ohne Backslashes)
content = re.sub(
    r'[ \t]*<a href="/statistics/"[^>]*>Statistics</a>\n?',
    '',
    content
)

# Füge korrekte Zeile nach Collectives ein
correct_link = '    <a href="/statistics/" {% if \'/statistics/\' in request.path %}class="active"{% endif %}>Statistics</a>'

# Der Trick: in Python-String sind die einfachen Quotes normal – kein Backslash-Problem
# Wir schreiben direkt den korrekten String:
correct_link = "    <a href=\"/statistics/\" {% if '/statistics/' in request.path %}class=\"active\"{% endif %}>Statistics</a>"

if '/statistics/' not in content:
    content = content.replace(
        '<a href="/collectives/"',
        '<a href="/collectives/"'  # Anker für die Einfügestelle
    )
    # Collectives-Link suchen und danach einfügen
    content = re.sub(
        r'(<a href="/collectives/"[^>]*>[^<]*</a>)',
        r'\1\n' + correct_link,
        content
    )
    print("Statistics-Link eingefügt.")
else:
    print("Statistics-Link bereits vorhanden – keine Änderung nötig.")

with open(path, "w") as f:
    f.write(content)

print("DONE.")
PYEOF

echo ""
echo "Ergebnis Zeilen 80-90:"
sed -n '80,90p' "$BASE"
echo ""
echo "✅ Fertig – Server neu starten:"
echo "   python manage.py runserver 0.0.0.0:8000"
