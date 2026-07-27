#!/usr/bin/env bash
# Exercised restart drill: place a real trade, kill -9 the exchange, restart,
# and prove the state came back byte-identical via the /v1/health digest.
# ponytail: kill -9 on purpose — a clean shutdown hook would prove less.
set -euo pipefail

PORT="${1:-3299}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'kill "${PID:-0}" 2>/dev/null || true; rm -rf "$WORK"' EXIT

export BAYES_STATE_PATH="$WORK/state.json"
export BAYES_JOINT_STATE_PATH="$WORK/joint.json"

boot() {
  python3 "$ROOT/backend/server.py" --host 127.0.0.1 --port "$PORT" 2>"$WORK/log.$1" &
  PID=$!
  for _ in $(seq 1 50); do
    curl -sf --max-time 1 "http://127.0.0.1:$PORT/v1/health" >/dev/null 2>&1 && return 0
    sleep 0.2
  done
  echo "FAIL: server did not come up"; cat "$WORK/log.$1"; exit 1
}

digest() { curl -s "http://127.0.0.1:$PORT/v1/health" | python3 -c 'import json,sys; print(json.load(sys.stdin)["components"]["db"].get("digest",""))'; }
dbkind() { curl -s "http://127.0.0.1:$PORT/v1/health" | python3 -c 'import json,sys; print(json.load(sys.stdin)["components"]["db"]["kind"])'; }
events() { curl -s "http://127.0.0.1:$PORT/v1/markets/m1/events" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(len(d.get("events",d.get("items",[]))))'; }

echo "== boot 1 =="
boot 1
echo "db kind: $(dbkind)"

VAR=$(curl -s "http://127.0.0.1:$PORT/v1/markets/m1" | python3 -c 'import json,sys; print(json.load(sys.stdin)["market"]["variableId"])')
echo "== placing a real trade on m1 (variable $VAR) =="
curl -sf -X POST "http://127.0.0.1:$PORT/v1/markets/m1/orders/probability-edit" \
  -H 'content-type: application/json' -H 'x-agent-id: drill' \
  -d "{\"accountId\":\"acct_drill\",\"variableId\":\"$VAR\",\"target\":{\"kind\":\"marginal\",\"outcomeId\":\"yes\",\"probability\":0.77},\"context\":[]}" \
  >/dev/null

BEFORE=$(digest); BEFORE_EVENTS=$(events)
echo "before: digest=$BEFORE events=$BEFORE_EVENTS"
[ -n "$BEFORE" ] || { echo "FAIL: no digest — persistence not active"; exit 1; }

echo "== kill -9 (unclean crash) =="
kill -9 "$PID"; wait "$PID" 2>/dev/null || true

echo "== boot 2 (recovery) =="
boot 2
grep -q "restored durable state" "$WORK/log.2" || { echo "FAIL: no restore on boot"; cat "$WORK/log.2"; exit 1; }

AFTER=$(digest); AFTER_EVENTS=$(events)
echo "after:  digest=$AFTER events=$AFTER_EVENTS"

if [ "$BEFORE" = "$AFTER" ] && [ "$BEFORE_EVENTS" = "$AFTER_EVENTS" ]; then
  echo "PASS: state survived kill -9 with identical digest"
else
  echo "FAIL: digest or event count changed across restart"; exit 1
fi

echo "== counter-attack: corrupt the snapshot, the exchange must refuse to boot =="
kill -9 "$PID"; wait "$PID" 2>/dev/null || true
echo '{ truncated' > "$BAYES_STATE_PATH"
if python3 "$ROOT/backend/server.py" --host 127.0.0.1 --port "$PORT" 2>"$WORK/log.3"; then
  echo "FAIL: booted clean on top of a corrupt snapshot"; exit 1
fi
grep -q "refusing to start" "$WORK/log.3" || { echo "FAIL: wrong failure mode"; cat "$WORK/log.3"; exit 1; }
echo "PASS: refused to start on an unreadable snapshot (history not silently erased)"
