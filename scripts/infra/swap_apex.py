"""Move FAO to fao.futarchy.ai, then point the apex at the bayes tunnel.

Order matters: FAO gets its new home and is verified BEFORE the apex flips.
Reversible: flipping the apex CNAME back to fao-site.pages.dev restores it.
"""

import json
import os
import time
import urllib.request
import urllib.error

BASE = "https://api.cloudflare.com/client/v4"
EMAIL = os.environ["CLOUDFLARE_AUTH_EMAIL"]
KEY = os.environ["CLOUDFLARE_GLOBAL_API_KEY"]
ZONE_ID = "df84e6b495e990cb283401087a26ebeb"
ACCOUNT_ID = "878924eda0607cab3b6c0c86a9babb3f"
TUNNEL_TARGET = "8e5ae8e1-42db-4dbd-86e7-cefb1f78251f.cfargotunnel.com"
PAGES_PROJECT = "fao-site"
FAO_HOST = "fao.futarchy.ai"


def call(method, path, body=None, ok_codes=()):
    req = urllib.request.Request(
        BASE + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"X-Auth-Email": EMAIL, "X-Auth-Key": KEY, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as exc:
        data = json.load(exc)
    if not data.get("success"):
        codes = {e.get("code") for e in data.get("errors") or []}
        if codes & set(ok_codes):
            return None
        raise SystemExit(f"API error on {method} {path}: {data.get('errors')}")
    return data.get("result")


# 1. Register fao.futarchy.ai on the Pages project (code 8000015 = already exists)
call(
    "POST",
    f"/accounts/{ACCOUNT_ID}/pages/projects/{PAGES_PROJECT}/domains",
    {"name": FAO_HOST},
    ok_codes=(8000015, 8000018),
)
print("pages custom domain ensured:", FAO_HOST)

# 2. DNS: fao -> fao-site.pages.dev (proxied)
records = call("GET", f"/zones/{ZONE_ID}/dns_records?per_page=100") or []
fao_existing = [r for r in records if r["name"] == FAO_HOST and r["type"] in {"A", "AAAA", "CNAME"}]
if not fao_existing:
    call(
        "POST",
        f"/zones/{ZONE_ID}/dns_records",
        {"type": "CNAME", "name": FAO_HOST, "content": f"{PAGES_PROJECT}.pages.dev", "proxied": True, "ttl": 1},
    )
    print("DNS created: fao -> pages.dev")
else:
    print("DNS exists for fao:", fao_existing[0]["content"])

def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (deploy-check)"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read(4096).decode(errors="replace")


# 3. Verify FAO serves on its new host before touching the apex
ok = False
for attempt in range(10):
    time.sleep(6)
    try:
        if "FAO" in fetch(f"https://{FAO_HOST}/"):
            ok = True
            break
    except Exception as exc:  # noqa: BLE001 - propagation retries
        print(f"  fao check attempt {attempt + 1}: {exc}")
if not ok:
    raise SystemExit("fao.futarchy.ai not serving FAO yet — apex NOT flipped, rerun later")
print("fao.futarchy.ai verified serving FAO")

# 4. Flip the apex CNAME to the tunnel
apex = [r for r in records if r["name"] == "futarchy.ai" and r["type"] == "CNAME"]
if not apex:
    raise SystemExit("apex CNAME not found")
record = apex[0]
print(f"apex was: CNAME -> {record['content']}")
if record["content"] != TUNNEL_TARGET:
    call(
        "PATCH",
        f"/zones/{ZONE_ID}/dns_records/{record['id']}",
        {"type": "CNAME", "name": "futarchy.ai", "content": TUNNEL_TARGET, "proxied": True},
    )
    print(f"apex now: CNAME -> {TUNNEL_TARGET}")
else:
    print("apex already on tunnel")

# 5. Verify apex serves the bayes app
for attempt in range(10):
    time.sleep(6)
    try:
        if "Bayes Market" in fetch("https://futarchy.ai/"):
            print("futarchy.ai verified serving the belief-network app")
            break
        print(f"  apex check attempt {attempt + 1}: serving other content")
    except Exception as exc:  # noqa: BLE001
        print(f"  apex check attempt {attempt + 1}: {exc}")
print("DONE")
