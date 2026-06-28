"""
Eigenstaendiges Skript (ohne Django/DB): liest Buffer-Posts aus und zeigt alle
Felder ausser metrics. So sehen wir, ob Statistik-Werte mitkommen.

Aufruf:
    python buffer_dump.py DEIN_TOKEN
"""
import sys
import json
import urllib.request
import urllib.error

if len(sys.argv) < 2:
    print("Aufruf: python buffer_dump.py DEIN_TOKEN")
    sys.exit(1)

TOKEN = sys.argv[1]


def post(query_str):
    req = urllib.request.Request(
        "https://api.buffer.com",
        data=json.dumps({"query": query_str}).encode("utf-8"),
        method="POST",
    )
    req.add_header("Authorization", f"Bearer {TOKEN}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.read().decode("utf-8", errors="replace")


# 1) Org-ID
ob = post("query { account { organizations { id name } } }")
print("=== Org-Abfrage ===")
print(ob[:500])
try:
    org_id = json.loads(ob)["data"]["account"]["organizations"][0]["id"]
except Exception:
    print("Konnte Org-ID nicht lesen. Stop.")
    sys.exit(1)

# 2) Posts MIT vielen Feldern, OHNE metrics
q = (
    'query { posts(input:{organizationId:"%s"}, first:3){ edges{ node{ '
    'id status text dueAt createdAt updatedAt channelId __typename '
    '} } } }' % org_id
)
print("\n=== Posts (ohne metrics) ===")
body = post(q)
try:
    print(json.dumps(json.loads(body), indent=2, ensure_ascii=False)[:5000])
except Exception:
    print(body[:5000])
