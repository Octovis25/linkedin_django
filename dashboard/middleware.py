from django.conf import settings


class NoCacheStaticInDebug:
    """Im Entwicklungsbetrieb statische Dateien nie cachen.

    Sonst liefert der Browser alte JS-Module aus (studio.js hat einen
    Versions-Stempel, die davon importierten Module wie editor.js aber nicht),
    und Code-Aenderungen kommen scheinbar nicht an.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if settings.DEBUG and request.path.startswith(settings.STATIC_URL):
            response["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response["Pragma"] = "no-cache"
            response["Expires"] = "0"
        return response
