#!/bin/bash
set -e
echo "🚀 Deploying: Post-Bilder (Nextcloud) + Lösch-Button..."

APP=linkedin_django
POSTS=posts_posted

# ── 1. views.py ──────────────────────────────────────────────────
cp views_posts_FINAL.py $APP/$POSTS/views.py
echo "✅ views.py"

# ── 2. urls.py ───────────────────────────────────────────────────
cp urls_posts_FINAL.py $APP/$POSTS/urls.py
echo "✅ urls.py"

# ── 3. edit.html ─────────────────────────────────────────────────
cp edit_posts_FINAL.html $APP/$POSTS/templates/$POSTS/edit.html
echo "✅ edit.html"

# ── 4. models.py: post_image als CharField (kein ImageField mehr) ─
# Nur anpassen falls noch ImageField – kein Migration nötig da managed=False
grep -q "CharField" $APP/$POSTS/models.py && echo "ℹ️  models.py bereits CharField" || \
  sed -i 's/models.ImageField([^)]*)/models.CharField(max_length=512, blank=True, null=True, verbose_name="Post-Bild")/' \
      $APP/$POSTS/models.py
echo "✅ models.py geprüft"

# ── 5. Git Push ───────────────────────────────────────────────────
cd $APP
git add -A
git commit -m "fix: Post-Bilder via Nextcloud WebDAV + Lösch-Button in edit.html"
git push origin main
echo ""
echo "✅ FERTIG! Render deployt automatisch."
echo "   → Bilder werden direkt in Nextcloud gespeichert"
echo "   → Collectives App-Passwort wird wiederverwendet"
echo "   → Lösch-Button im Edit-Formular aktiv"
