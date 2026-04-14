#!/bin/bash
##############################################################
# fix_images.sh – Fixes logo + post images on Render
# RUN MANUALLY: bash fix_images.sh
# Does NOT auto-deploy. Commit & push yourself when ready.
##############################################################
set -e
cd /opt/render/project/src 2>/dev/null || cd "$(dirname "$0")"

echo "=== 1. Add WhiteNoise to settings.py ==="
SETTINGS="dashboard/settings.py"

# Check if whitenoise already in middleware
if grep -q "whitenoise" "$SETTINGS"; then
    echo "   WhiteNoise already present, skipping."
else
    # Add whitenoise middleware after SecurityMiddleware
    sed -i 's/"django.middleware.security.SecurityMiddleware",/"django.middleware.security.SecurityMiddleware","whitenoise.middleware.WhiteNoiseMiddleware",/' "$SETTINGS"
    echo "   WhiteNoise middleware added."
fi

# Add STATICFILES_STORAGE if not present
if grep -q "STATICFILES_STORAGE\|STORAGES" "$SETTINGS"; then
    echo "   Static storage already configured."
else
    echo "" >> "$SETTINGS"
    echo "STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'" >> "$SETTINGS"
    echo "   STATICFILES_STORAGE added."
fi

echo ""
echo "=== 2. Fix MEDIA_ROOT (if typo) ==="
# Ensure MEDIA_ROOT is correct (not MEDIA_ROOT typo)
if grep -q "MEDIA_ROOT" "$SETTINGS"; then
    echo "   MEDIA_ROOT found."
else
    echo "" >> "$SETTINGS"
    echo "MEDIA_ROOT = BASE_DIR / 'media'" >> "$SETTINGS"
    echo "   MEDIA_ROOT added."
fi

echo ""
echo "=== 3. Add media URL patterns to main urls.py ==="
MAIN_URLS="dashboard/urls.py"

if grep -q "MEDIA_URL\|media_root" "$MAIN_URLS"; then
    echo "   Media URLs already configured."
else
    # Append media URL config
    cat >> "$MAIN_URLS" << 'URLS_APPEND'

# Serve media files (uploaded post images)
from django.conf import settings
from django.conf.urls.static import static
if not settings.DEBUG:
    # On Render (production), serve media via WhiteNoise workaround
    from django.views.static import serve
    from django.urls import re_path
    urlpatterns += [
        re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}),
    ]
else:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
URLS_APPEND
    echo "   Media URL patterns added."
fi

echo ""
echo "=== 4. Ensure whitenoise is in requirements.txt ==="
if grep -q "whitenoise" requirements.txt 2>/dev/null; then
    echo "   whitenoise already in requirements.txt."
else
    echo "whitenoise" >> requirements.txt
    echo "   whitenoise added to requirements.txt."
fi

echo ""
echo "=== 5. Ensure static/images/octovis_logo.png exists ==="
mkdir -p static/images
if [ -f static/images/octovis_logo.png ]; then
    echo "   Logo file exists."
else
    echo "   WARNING: static/images/octovis_logo.png NOT FOUND!"
    echo "   Please upload the logo file to static/images/octovis_logo.png"
fi

echo ""
echo "=== 6. Ensure media/ directory exists ==="
mkdir -p media/post_images
echo "   media/post_images/ directory ensured."

echo ""
echo "=== 7. Run collectstatic ==="
python manage.py collectstatic --noinput 2>/dev/null && echo "   collectstatic done." || echo "   collectstatic skipped (run after deploy)."

echo ""
echo "============================================"
echo "DONE! Now commit and push manually:"
echo "  git add -A"
echo "  git commit -m 'Fix: static/media files for images'"
echo "  git push"
echo ""
echo "IMPORTANT: Uploaded post images on Render are"
echo "EPHEMERAL - they get lost on every deploy!"
echo "For permanent storage, consider using an"
echo "external service (S3, Cloudinary, etc.)."
echo "============================================"
