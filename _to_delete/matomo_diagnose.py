"""Findet heraus, auf welchem Weg Matomo-for-WordPress die Anmeldung akzeptiert.

Aufruf im Projektordner mit aktivem venv:
    python matomo_diagnose.py

Liest MATOMO_* aus der .env. Gibt den Token NICHT aus.
"""
import sys

try:
    import requests
    from requests.auth import HTTPBasicAuth
except ImportError:
    sys.exit("requests fehlt - bitte 'pip install requests'")

werte = {}
for zeile in open(".env", encoding="utf-8", errors="replace"):
    zeile = zeile.strip()
    if zeile and not zeile.startswith("#") and "=" in zeile:
        k, v = zeile.split("=", 1)
        werte[k.strip()] = v.strip().strip('"').strip("'")

app_url = werte.get("MATOMO_URL", "").rstrip("/")
sid = werte.get("MATOMO_SITE_ID", "1")
token = werte.get("MATOMO_TOKEN", "")

if ":" not in token:
    sys.exit("MATOMO_TOKEN muss 'benutzer:anwendungspasswort' sein.")
benutzer, passwort = token.split(":", 1)
basis = app_url.split("/wp-content/")[0]          # https://octotrial.com

print(f"Basis     : {basis}")
print(f"Benutzer  : {benutzer}")
print(f"Passwort  : {len(passwort)} Zeichen"
      + (" (enthaelt Leerzeichen)" if " " in passwort else ""))
print("=" * 72)


def zeige(name, r):
    art = r.headers.get("content-type", "?").split(";")[0]
    text = r.text.strip()
    if text.startswith(("{", "[")):
        kurz = text[:150].replace("\n", " ")
    elif "Log In" in text or "wp-login" in text:
        kurz = ">>> LOGIN-SEITE (Anmeldung abgelehnt)"
    else:
        kurz = text[:100].replace("\n", " ")
    print(f"{name:<46} {r.status_code:<5} {art:<22} {kurz}")


sitzung = requests.Session()
sitzung.headers["User-Agent"] = "octovis-diagnose"
auth = HTTPBasicAuth(benutzer, passwort)
auth_ohne_leer = HTTPBasicAuth(benutzer, passwort.replace(" ", ""))

# 0) Funktionieren Anwendungspasswoerter ueberhaupt?
print("--- Grundtest: WordPress-eigene REST-API ---")
for name, a in [("wp/v2/users/me  (Passwort wie eingetragen)", auth),
                ("wp/v2/users/me  (ohne Leerzeichen)", auth_ohne_leer)]:
    try:
        zeige(name, sitzung.get(f"{basis}/wp-json/wp/v2/users/me", auth=a, timeout=25))
    except Exception as e:
        print(f"{name:<46} FEHLER {type(e).__name__}: {e}")

# 1) Matomo-App-URL, verschiedene Anmeldearten
print("\n--- Matomo-App-URL ---")
felder = {"module": "API", "method": "VisitsSummary.get", "idSite": sid,
          "format": "JSON", "period": "day", "date": "yesterday"}
versuche = [
    ("POST token_auth=benutzer:passwort", dict(data={**felder, "token_auth": token})),
    ("POST token_auth ohne Leerzeichen", dict(data={**felder, "token_auth": token.replace(" ", "")})),
    ("POST + Basic-Auth-Header", dict(data=felder, auth=auth)),
    ("POST + Basic-Auth ohne Leerzeichen", dict(data=felder, auth=auth_ohne_leer)),
    ("GET  token_auth in der URL", dict(params={**felder, "token_auth": token}, method="GET")),
]
for name, kw in versuche:
    methode = kw.pop("method", "POST")
    try:
        r = sitzung.request(methode, app_url, timeout=25, **kw)
        zeige(name, r)
    except Exception as e:
        print(f"{name:<46} FEHLER {type(e).__name__}: {e}")

# 2) Matomo ueber die WordPress-REST-API
print("\n--- Matomo ueber die WordPress-REST-API ---")
for pfad in ["/wp-json/matomo/v1/api/processed_report"
             "?period=day&date=yesterday&apiModule=VisitsSummary&apiAction=get",
             "/wp-json/matomo/v1/sites_manager/all"]:
    try:
        zeige(pfad.split('?')[0][-44:], sitzung.get(basis + pfad, auth=auth, timeout=25))
    except Exception as e:
        print(f"{pfad[:44]:<46} FEHLER {type(e).__name__}: {e}")

print("\nFertig. Schick diese Ausgabe zurueck - der Token steht nicht darin.")
