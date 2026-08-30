"""Kontext, der in jedem Template zur Verfügung steht."""

from django.conf import settings


def live_adresse(request):
    """Adresse der öffentlich erreichbaren Instanz, für den Link im Kopfbereich.

    Auf Render setzt die Plattform RENDER_EXTERNAL_URL selbst; lokal greift
    DASHBOARD_URL aus der .env. Läuft man bereits auf dieser Adresse, wird der
    Link ausgeblendet - er würde nur auf die eigene Seite zeigen.
    """
    adresse = getattr(settings, "LIVE_URL", "") or ""
    if adresse:
        try:
            if request.get_host() in adresse:
                adresse = ""
        except Exception:
            pass
    return {"live_url": adresse.rstrip("/")}
