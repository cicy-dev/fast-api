#!/bin/bash
# fast-api/tests/curl/test_ttyd.sh
set -euo pipefail

BASE=${FAST_API_URL:-http://localhost:14444}
TOKEN=$(python3 -c "import json; print(json.load(open('/home/w3c_offical/global.json'))['api_token'])")
H_AUTH="Authorization: Bearer $TOKEN"
H_ACCEPT="Accept: application/json"

PASS=0; FAIL=0

pass() { echo "  ✓ $1"; PASS=$((PASS+1)); }
fail() { echo "  ✗ $1: $2"; FAIL=$((FAIL+1)); }

assert_status() {
  local desc="$1" expected="$2" actual="$3"
  [ "$actual" = "$expected" ] && pass "$desc" || fail "$desc" "expected HTTP $expected got $actual"
}

assert_contains() {
  local desc="$1" needle="$2" haystack="$3"
  echo "$haystack" | grep -q "$needle" && pass "$desc" || fail "$desc" "expected '$needle' in response"
}

echo "=== test_ttyd.sh ==="

# GET /api/ttyd/list
echo "[1] GET /api/ttyd/list"
RESP=$(curl -s -w '\n%{http_code}' "$BASE/api/ttyd/list" -H "$H_AUTH" -H "$H_ACCEPT")
CODE=$(echo "$RESP" | tail -1); BODY=$(echo "$RESP" | head -1)
assert_status "/api/ttyd/list → 200" "200" "$CODE"
assert_contains "/api/ttyd/list contains configs" '"configs"' "$BODY"

# GET /api/ttyd/list - no token → 403
echo "[2] GET /api/ttyd/list (no token)"
CODE=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/api/ttyd/list")
assert_status "/api/ttyd/list no token → 401" "401" "$CODE"

# GET /api/ttyd/by-name/{nonexistent} → 404
echo "[3] GET /api/ttyd/by-name/nonexistent_pane"
CODE=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/api/ttyd/by-name/nonexistent%3Apane.0" \
  -H "$H_AUTH" -H "$H_ACCEPT")
assert_status "/api/ttyd/by-name nonexistent → 404" "404" "$CODE"

# GET /api/ttyd/by-name/{valid pane} - pick first from list
echo "[4] GET /api/ttyd/by-name/{valid pane}"
FIRST_PANE=$(curl -s "$BASE/api/ttyd/list" -H "$H_AUTH" -H "$H_ACCEPT" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['configs'][0]['pane_id'] if d.get('configs') else '')" 2>/dev/null)

if [ -n "$FIRST_PANE" ]; then
  ENCODED=$(python3 -c "import urllib.parse; print(urllib.parse.quote('$FIRST_PANE', safe=''))")
  RESP=$(curl -s -w '\n%{http_code}' "$BASE/api/ttyd/by-name/$ENCODED" -H "$H_AUTH" -H "$H_ACCEPT")
  CODE=$(echo "$RESP" | tail -1); BODY=$(echo "$RESP" | head -1)
  assert_status "/api/ttyd/by-name valid → 200" "200" "$CODE"
  assert_contains "/api/ttyd/by-name contains port" '"port"' "$BODY"
  assert_contains "/api/ttyd/by-name contains token" '"token"' "$BODY"
else
  pass "/api/ttyd/by-name (skipped - no panes configured)"
fi

# GET /api/ttyd/status/{valid pane}
echo "[5] GET /api/ttyd/status/{valid pane}"
if [ -n "$FIRST_PANE" ]; then
  ENCODED=$(python3 -c "import urllib.parse; print(urllib.parse.quote('$FIRST_PANE', safe=''))")
  RESP=$(curl -s -w '\n%{http_code}' "$BASE/api/ttyd/status/$ENCODED" -H "$H_AUTH" -H "$H_ACCEPT")
  CODE=$(echo "$RESP" | tail -1); BODY=$(echo "$RESP" | head -1)
  assert_status "/api/ttyd/status valid → 200" "200" "$CODE"
  assert_contains "/api/ttyd/status contains ready" '"ready"' "$BODY"
else
  pass "/api/ttyd/status (skipped - no panes configured)"
fi

echo ""
echo "PASS: $PASS  FAIL: $FAIL"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
