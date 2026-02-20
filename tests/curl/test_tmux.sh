#!/bin/bash
# fast-api/tests/curl/test_tmux.sh
set -euo pipefail

BASE=${FAST_API_URL:-http://localhost:14444}
TOKEN=$(python3 -c "import json; print(json.load(open('/home/w3c_offical/global.json'))['api_token'])")
H_AUTH="Authorization: Bearer $TOKEN"
H_JSON="Content-Type: application/json"
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

echo "=== test_tmux.sh ==="

# GET /api/tmux/sessions
echo "[1] GET /api/tmux/sessions"
RESP=$(curl -s -w '\n%{http_code}' "$BASE/api/tmux/sessions" -H "$H_AUTH" -H "$H_ACCEPT")
CODE=$(echo "$RESP" | tail -1); BODY=$(echo "$RESP" | head -1)
assert_status "/api/tmux/sessions → 200" "200" "$CODE"
assert_contains "/api/tmux/sessions contains sessions" '"sessions"' "$BODY"

# GET /api/tmux/sessions - no token → 403
echo "[2] GET /api/tmux/sessions (no token)"
CODE=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/api/tmux/sessions")
assert_status "/api/tmux/sessions no token → 401" "401" "$CODE"

# GET /api/tmux/tree
echo "[3] GET /api/tmux/tree"
RESP=$(curl -s -w '\n%{http_code}' "$BASE/api/tmux/tree" -H "$H_AUTH" -H "$H_ACCEPT")
CODE=$(echo "$RESP" | tail -1); BODY=$(echo "$RESP" | head -1)
assert_status "/api/tmux/tree → 200" "200" "$CODE"
assert_contains "/api/tmux/tree contains tree" '"tree"' "$BODY"

# GET /api/tmux-list
echo "[4] GET /api/tmux-list"
RESP=$(curl -s -w '\n%{http_code}' "$BASE/api/tmux-list" -H "$H_AUTH" -H "$H_ACCEPT")
CODE=$(echo "$RESP" | tail -1); BODY=$(echo "$RESP" | head -1)
assert_status "/api/tmux-list → 200" "200" "$CODE"
assert_contains "/api/tmux-list contains success" '"success"' "$BODY"

# POST /api/tmux - no token → 403
echo "[5] POST /api/tmux (no token)"
CODE=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/api/tmux" \
  -H "$H_JSON" -d '{"text":"hello","target":"worker:main.0"}')
assert_status "/api/tmux no token → 401" "401" "$CODE"

# POST /api/tmux - missing target → success:false
echo "[6] POST /api/tmux (missing target)"
RESP=$(curl -s -w '\n%{http_code}' -X POST "$BASE/api/tmux" \
  -H "$H_AUTH" -H "$H_JSON" -H "$H_ACCEPT" \
  -d '{"text":"hello"}')
CODE=$(echo "$RESP" | tail -1); BODY=$(echo "$RESP" | head -1)
assert_status "/api/tmux missing target → 200" "200" "$CODE"
assert_contains "/api/tmux missing target → success:false" 'false' "$BODY"

# GET /api/tmux/panes/{nonexistent}/restart → success:false
echo "[7] POST /api/tmux/panes/nonexistent_pane/restart"
RESP=$(curl -s -w '\n%{http_code}' -X POST "$BASE/api/tmux/panes/nonexistent%3Apane.0/restart" \
  -H "$H_AUTH" -H "$H_ACCEPT")
CODE=$(echo "$RESP" | tail -1); BODY=$(echo "$RESP" | head -1)
assert_status "/api/tmux/panes/nonexistent/restart → 200" "200" "$CODE"
assert_contains "/api/tmux/panes/nonexistent → success:false" 'false' "$BODY"

echo ""
echo "PASS: $PASS  FAIL: $FAIL"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
