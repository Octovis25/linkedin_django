from .views import get_brand_colors


def brand_colors(request):
    """Stellt die Brand-Farben in jedem Template-Kontext bereit."""
    return {'brand': get_brand_colors()}
