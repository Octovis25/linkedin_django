#!/bin/bash

echo "🔧 Deploying fixed dashboard.html..."

# Gehe zum Projekt-Root (anpassen falls nötig)
cd ~/linkedin_dashboard || { echo "❌ Projekt-Verzeichnis nicht gefunden"; exit 1; }

# Erstelle Backup der alten Datei
echo "📦 Creating backup..."
cp collectives/templates/collectives/dashboard.html collectives/templates/collectives/dashboard.html.backup 2>/dev/null || echo "⚠️ No old file to backup"

# Kopiere die neue Version an den richtigen Ort
echo "📝 Copying dashboard.html..."
cp /mnt/data/dashboard.html collectives/templates/collectives/dashboard.html

# Git Operations
echo "🔄 Git add..."
git add collectives/templates/collectives/dashboard.html

echo "💾 Git commit..."
git commit -m "Fix: Add missing JavaScript functions (showTab, loadDashboard) in collectives dashboard"

echo "🚀 Git push..."
git push origin main

echo "✅ Done! Now deploy manually in Render Dashboard."
echo ""
echo "Next steps:"
echo "1. Go to https://dashboard.render.com"
echo "2. Select your service"
echo "3. Click 'Manual Deploy' → 'Deploy latest commit'"
