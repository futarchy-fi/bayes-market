"""Wire futarchy.ai apex (+www) to the bayes app via the existing tunnel.

Reads CF creds from env. Steps:
1. Find the tunnel that already serves bayes.futarchy.ai.
2. Append ingress rules for futarchy.ai and www.futarchy.ai -> same service,
   preserving every existing rule and the catch-all.
3. Create proxied CNAME records for @ and www -> <tunnel>.cfargotunnel.com.
Idempotent: skips steps already done. Prints a summary; never prints secrets.
"""

import json
import os
import urllib.request

BASE = "https://api.cloudflare.com/client/v4"
EMAIL = os.environ["CLOUDFLARE_AUTH_EMAIL"]
KEY = os.environ["CLOUDFLARE_GLOBAL_API_KEY"]
ZONE_ID = "df84e6b495e990cb283401087a26ebeb"
ACCOUNT_ID = "878924eda0607cab3b6c0c86a9babb3f"
TARGET_HOSTS = ["futarchy.ai", "www.futarchy.ai"]
SERVICE = "http://127.0.0.1:3205"


def call(method, path, body=None):
    req = urllib.request.Request(
        BASE + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "X-Auth-Email": EMAIL,
            "X-Auth-Key": KEY,
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req) as resp:
        data = json.load(resp)
    if not data.get("success"):
        raise SystemExit(f"API error on {method} {path}: {data.get('errors')}")
    return data["result"]


# 1. Find the tunnel serving bayes.futarchy.ai
tunnels = call("GET", f"/accounts/{ACCOUNT_ID}/cfd_tunnel?is_deleted=false")
tunnel = None
config = None
for t in tunnels:
    cfg = call("GET", f"/accounts/{ACCOUNT_ID}/cfd_tunnel/{t['id']}/configurations")
    ingress = ((cfg or {}).get("config") or {}).get("ingress") or []
    if any(rule.get("hostname") == "bayes.futarchy.ai" for rule in ingress):
        tunnel, config = t, cfg
        break
if tunnel is None or config is None:
    raise SystemExit("No tunnel with a bayes.futarchy.ai ingress rule found")
print(f"tunnel: {tunnel['name']} ({tunnel['id']})")

ingress = config["config"]["ingress"]
existing_hosts = {rule.get("hostname") for rule in ingress}
print(f"existing ingress hostnames: {sorted(h for h in existing_hosts if h)}")

# 2. Append missing rules before the catch-all (last rule has no hostname)
to_add = [h for h in TARGET_HOSTS if h not in existing_hosts]
if to_add:
    catch_all = ingress[-1] if ingress and "hostname" not in ingress[-1] else None
    body_rules = ingress[:-1] if catch_all else list(ingress)
    for host in to_add:
        body_rules.append({"hostname": host, "service": SERVICE})
    if catch_all:
        body_rules.append(catch_all)
    new_config = dict(config["config"])
    new_config["ingress"] = body_rules
    call("PUT", f"/accounts/{ACCOUNT_ID}/cfd_tunnel/{tunnel['id']}/configurations", {"config": new_config})
    print(f"ingress rules added: {to_add}")
else:
    print("ingress rules already present")

# 3. DNS records. Only A/AAAA/CNAME records at the same name are routing
# conflicts; TXT (SPF etc.) coexists with a CNAME at the apex on Cloudflare.
records = call("GET", f"/zones/{ZONE_ID}/dns_records?per_page=100")
target = f"{tunnel['id']}.cfargotunnel.com"
ADDRESS_TYPES = {"A", "AAAA", "CNAME"}
for host in TARGET_HOSTS:
    same_name = [r for r in records if r["name"] == host and r["type"] in ADDRESS_TYPES]
    if not same_name:
        call(
            "POST",
            f"/zones/{ZONE_ID}/dns_records",
            {"type": "CNAME", "name": host, "content": target, "proxied": True, "ttl": 1},
        )
        print(f"DNS created: {host} -> {target} (proxied)")
        continue
    existing = same_name[0]
    if existing["type"] == "CNAME" and existing["content"] == target:
        print(f"DNS already correct: {host}")
    elif host == "www.futarchy.ai" and existing["type"] == "CNAME" and existing["content"] == "futarchy.ai":
        print("DNS ok: www chains to the apex")
    else:
        print(
            f"DNS CONFLICT (not touching): {host} is {existing['type']} -> {existing['content']}"
        )

print("DONE")
