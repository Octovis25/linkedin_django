#!/bin/bash
echo "Fix fuer Render..."

# 1. mysqlclient in requirements.txt
if [ -f requirements.txt ]; then
  echo "  requirements.txt existiert"
else
  echo "  requirements.txt neu erstellt"
  touch requirements.txt
fi

for pkg in "django" "mysqlclient" "python-dotenv" "gunicorn"; do
  if ! grep -qi "^${pkg}" requirements.txt 2>/dev/null; then
    echo "$pkg" >> requirements.txt
    echo "    + $pkg hinzugefuegt"
  else
    echo "    $pkg bereits vorhanden"
  fi
done

echo ""
echo "requirements.txt:"
cat requirements.txt
echo ""

# 2. DASHBOARD_URL in .env
if [ -f .env ]; then
  sed -i 's|DASHBOARD_URL=.*|DASHBOARD_URL=https://linkedin-dashboard.onrender.com|' .env
  echo "  .env: DASHBOARD_URL aktualisiert"
fi

# 3. Git speichern
git add -A
git commit -m "Fix Render: mysqlclient in requirements.txt + DASHBOARD_URL"
echo ""
echo "FERTIG! Jetzt pushen:"
echo "  git push origin main"
