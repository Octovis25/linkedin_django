"""Findet heraus, unter welchen Parametern Actions-Berichte Daten liefern."""
import os, django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
django.setup()

from matomo import client

def zeilen(roh):
    if isinstance(roh, dict):
        d = roh.get("reportData")
        if isinstance(d, list):
            return len(d), (d[0].get("label") if d else None)
        if isinstance(d, dict):
            return len(d), "dict"
        return -1, f"keys={list(roh)[:6]}"
    return -2, type(roh).__name__

faelle = [
    ("Actions.getPageUrls   range/last30 flat=1", dict(period="range", date="last30", flat=1)),
    ("Actions.getPageUrls   range/last30 flat=0", dict(period="range", date="last30", flat=0)),
    ("Actions.getPageUrls   day/yesterday flat=0", dict(period="day", date="yesterday", flat=0)),
    ("Actions.getPageUrls   month/today  flat=0", dict(period="month", date="today", flat=0)),
    ("Actions.getPageUrls   day/last30   flat=0", dict(period="day", date="last30", flat=0)),
]
for name, kw in faelle:
    try:
        n, erste = zeilen(client.report("Actions", "getPageUrls", filter_limit=5,
                                        cache_seconds=0, **kw))
        print(f"{name:<45} {n:>4} Zeilen   {erste}")
    except Exception as e:
        print(f"{name:<45} FEHLER {type(e).__name__}: {str(e)[:120]}")

print()
for modul, aktion in [("Referrers","getWebsites"), ("Referrers","getAll"),
                      ("UserCountry","getCountry"), ("VisitsSummary","get")]:
    try:
        n, erste = zeilen(client.report(modul, aktion, period="range", date="last30",
                                        filter_limit=5, flat=0, cache_seconds=0))
        print(f"{modul}.{aktion:<20} range/last30   {n:>4} Zeilen   {erste}")
    except Exception as e:
        print(f"{modul}.{aktion:<20} FEHLER {type(e).__name__}: {str(e)[:120]}")

print("\n--- Rohantwort Actions.getPageUrls, range/last30 ---")
import json
roh = client.report("Actions", "getPageUrls", period="range", date="last30",
                    filter_limit=5, flat=0, cache_seconds=0)
print(json.dumps(roh, ensure_ascii=False)[:1500] if isinstance(roh, dict) else roh)
