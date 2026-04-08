# T581 — DNS + Cloudflare Tunnel Routing Runbook (Public Mode)

Generated: 2026-02-26 UTC  
Task: T581 (BAYES-44)

## Objective

Expose `bayes.futarchy.ai` publicly via Cloudflare Tunnel in **public mode** (no Cloudflare Access login), routing to the Bayes service running on this host.

Target endpoint:
- `https://bayes.futarchy.ai/healthz` → `200` and Bayes JSON payload.

---

## Topology (public mode)

- Public hostname: `bayes.futarchy.ai`
- Public edge runtime: active host tunnel via `cloudflared-hermes.service`
- Cloudflare Tunnel ingress target: shared local Caddy on `http://127.0.0.1:80`
- Required Cloudflare origin host header: `bayes.futarchy.ai`
- Caddy upstream: `http://127.0.0.1:3205`
- Local service: `bayes-market.service` (user systemd)
- Probe script: `scripts/bayes_public_route_probe.sh`

Flow:

`Internet -> Cloudflare DNS -> Cloudflare Tunnel -> 127.0.0.1:80 (Caddy) -> 127.0.0.1:3205 -> bayes-market`

Important boundary:
- treat the active `cloudflared-hermes.service` runtime as the Bayes-facing edge path
- do not repurpose the checked-in `infra/host/cloudflared/config.yml` `ops.futarchy.ai` tunnel for Bayes unless the owner explicitly migrates Bayes onto that path

---

## Prerequisites

1. Bayes service is installed and healthy locally:
   - `curl -sS http://127.0.0.1:3205/healthz`
2. Host Caddy has a `bayes.futarchy.ai` site block and can reach the local Bayes service:
   - `curl -sS -H 'Host: bayes.futarchy.ai' http://127.0.0.1/healthz`
3. Tunnel service is running on host (the active runtime is `cloudflared-hermes.service`).
4. You have Cloudflare DNS and Zero Trust/Tunnel permissions for `futarchy.ai` zone.

---

## Step 1 — Ensure local service is healthy

```bash
systemctl --user status bayes-market.service --no-pager
curl -sS http://127.0.0.1:3205/healthz
```

Pass condition:
- JSON response contains `"service": "bayes-market"` and status `ok`.

---

## Step 2 — Add tunnel hostname route

In the active host tunnel used by `cloudflared-hermes.service`:

1. Open the active tunnel used by this host.
2. Add public hostname:
   - **Hostname:** `bayes.futarchy.ai`
   - **Service:** `http://127.0.0.1:80`
   - **Origin request host header:** `bayes.futarchy.ai`
3. Save/deploy tunnel config.

If the active tunnel is managed from YAML outside this repo, the equivalent ingress intent is:

```yaml
ingress:
  - hostname: bayes.futarchy.ai
    service: http://127.0.0.1:80
    originRequest:
      httpHostHeader: bayes.futarchy.ai
  - service: http_status:404
```

If the live tunnel already has other hostname rules, insert the Bayes rule above the terminal fallback entry.

---

## Step 3 — DNS verification

Ensure DNS record exists for `bayes.futarchy.ai` and is active through Cloudflare proxy.

Typical outcomes:
- tunnel-managed CNAME to `<tunnel-id>.cfargotunnel.com` (proxied), or
- equivalent route created automatically by Zero Trust UI.

Check:

```bash
getent hosts bayes.futarchy.ai || true
```

---

## Step 4 — Access policy (public mode)

In Cloudflare Access policies for this hostname/app:

- Set policy to **bypass/public** for `bayes.futarchy.ai`.
- Confirm no login challenge is applied to `/healthz`.

Requirement for BAYES MVP gate:
- Public health endpoint must not redirect to Access login.

---

## Step 5 — End-to-end validation

Run the deterministic probe:

```bash
bash scripts/bayes_public_route_probe.sh
```

Expected success output includes:
- `LOCAL_STATUS=PASS` (required)
- `PUBLIC_STATUS=PASS` when the external route is already serving Bayes health JSON
- or `PUBLIC_STATUS=WARN` when local Bayes is healthy but DNS/tunnel/Access propagation still needs follow-up

Interpretation:
- the script exits non-zero only on local Bayes health failure
- `PUBLIC_STATUS=WARN` is acceptable for repo-local deploy verification, but it is not enough to claim the final public-route launch gate in `apps/bayes-market/docs/t539-mvp-launch-gate.md`

Optional manual checks:

```bash
curl -sS -H 'Host: bayes.futarchy.ai' http://127.0.0.1/healthz | python3 -m json.tool
curl -sSI https://bayes.futarchy.ai/healthz | head -n 10
curl -sS https://bayes.futarchy.ai/healthz | python3 -m json.tool
```

---

## Troubleshooting

## Case A: `LOCAL_STATUS=FAIL`
Cause: local Bayes service is unavailable or not returning the expected health JSON.
Fix:
- verify `bayes-market.service` status
- verify local `127.0.0.1:3205` health response
- verify the service is still bound to `127.0.0.1:3205`

## Case B: `PUBLIC_STATUS=WARN` + HTML login page
Cause: Access policy still enforced.
Fix: Set app/hostname policy to bypass/public for this endpoint.

## Case C: `PUBLIC_STATUS=WARN` + `HTTP=52x`
Cause: tunnel route exists, but the edge cannot reach the healthy local backend.
Fix:
- verify local `curl -H 'Host: bayes.futarchy.ai' http://127.0.0.1/healthz`
- verify tunnel ingress target is `http://127.0.0.1:80`
- verify Caddy still proxies Bayes to `127.0.0.1:3205`
- verify the active `cloudflared-hermes.service` runtime picked up the hostname route
- re-check local `127.0.0.1:3205` health before escalating the edge issue

## Case D: `PUBLIC_STATUS=WARN` + DNS does not resolve
Cause: route/record not created or wrong zone.
Fix:
- verify hostname created in the correct Cloudflare account/zone
- ensure record is active and proxied

## Case E: `PUBLIC_STATUS=WARN` + intermittent 404 from tunnel
Cause: missing Bayes hostname rule, wrong ingress ordering, missing `httpHostHeader`, or stale config.
Fix:
- check tunnel ingress ordering
- confirm the Bayes rule sets `originRequest.httpHostHeader: bayes.futarchy.ai`
- ensure hostname rule is above default `http_status:404`

---

## Rollback (public exposure off)

1. Remove/disable tunnel hostname route for `bayes.futarchy.ai`.
2. Optionally stop local service:

```bash
systemctl --user disable --now bayes-market.service
```

3. Confirm route no longer serves Bayes health payload.

---

## Evidence capture template (for launch gate)

```md
## T581 Routing Evidence (<date>)
- Tunnel route: bayes.futarchy.ai -> http://127.0.0.1:80 with host header bayes.futarchy.ai (configured)
- Access policy: public/bypass (confirmed)
- Local Caddy route: PASS (`curl -H 'Host: bayes.futarchy.ai' http://127.0.0.1/healthz`)
- Local health: PASS (`curl http://127.0.0.1:3205/healthz`)
- Public probe: PASS | WARN (`scripts/bayes_public_route_probe.sh`)
- Public follow-up owner if WARN:
- Notes/owners:
```

---

## Related references

- `docs/ops/bayes-market-deploy.md`
- `scripts/bayes_public_route_probe.sh`
- `infra/host/caddy/Caddyfile`
- `infra/host/systemd/bayes-market.service`
