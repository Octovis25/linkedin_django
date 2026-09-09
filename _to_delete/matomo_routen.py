"""Listet alle Routen auf, die Matomo-for-WordPress ueber die WP-REST-API anbietet."""
import json
import requests
from requests.auth import HTTPBasicAuth

werte = {}
for z in open(".env", encoding="utf-8", errors="replace"):
    z = z.strip()
    if z and not z.startswith("#") and "=" in z:
        k, v = z.split("=", 1)
        werte[k.strip()] = v.strip().strip('"').strip("'")

basis = werte["MATOMO_URL"].split("/wp-content/")[0]
benutzer, passwort = werte["MATOMO_TOKEN"].split(":", 1)
auth = HTTPBasicAuth(benutzer, passwort)

r = requests.get(f"{basis}/wp-json/matomo/v1", auth=auth, timeout=30)
print("HTTP", r.status_code)
d = r.json()
routen = sorted(d.get("routes", {}).keys())
print(f"{len(routen)} Routen:\n")
for pfad in routen:
    verben = ",".join(sorted({m for e in d["routes"][pfad].get("endpoints", [])
                              for m in e.get("methods", [])}))
    args = d["routes"][pfad].get("endpoints", [{}])[0].get("args", {})
    print(f"  {pfad:<60} [{verben}]  args: {', '.join(sorted(args))[:90]}")

print("\n--- Testabruf: Seitenaufrufe ---")
t = requests.get(f"{basis}/wp-json/matomo/v1/api/processed_report",
                 params={"period":"day","date":"yesterday",
                         "apiModule":"Actions","apiAction":"getPageUrls","filter_limit":"3"},
                 auth=auth, timeout=30)
print("HTTP", t.status_code)
print(json.dumps(t.json(), ensure_ascii=False)[:900])
