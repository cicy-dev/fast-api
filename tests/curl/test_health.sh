#!/bin/bash
# fast-api/tests/curl/test_health.sh
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

echo "=== test_health.sh ==="

# GET /health
echo "[1] GET /health"
RESP=$(curl -s -w '\n%{http_code}' "$BASE/health" -H "$H_ACCEPT")
CODE=$(echo "$RESP" | tail -1); BODY=$(echo "$RESP" | head -1)
assert_status "/health returns 200" "200" "$CODE"
assert_contains "/health contains status" '"status"' "$BODY"

# GET /api/health
echo "[2] GET /api/health"
RESP=$(curl -s -w '\n%{http_code}' "$BASE/api/health" -H "$H_ACCEPT")
CODE=$(echo "$RESP" | tail -1); BODY=$(echo "$RESP" | head -1)
assert_status "/api/health returns 200" "200" "$CODE"
assert_contains "/api/health contains source" '"fast-api"' "$BODY"

# GET /ping
echo "[3] GET /ping"
RESP=$(curl -s -w '\n%{http_code}' "$BASE/ping" -H "$H_ACCEPT")
CODE=$(echo "$RESP" | tail -1); BODY=$(echo "$RESP" | head -1)
assert_status "/ping returns 200" "200" "$CODE"
assert_contains "/ping contains server_datetime" 'server_datetime' "$BODY"

# GET /api/auth/verify - no token → 403
echo "[4] GET /api/auth/verify (no token)"
CODE=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/api/auth/verify")
assert_status "/api/auth/verify no token → 401" "401" "$CODE"

# GET /api/auth/verify - valid token → 200
echo "[5] GET /api/auth/verify (valid token)"
RESP=$(curl -s -w '\n%{http_code}' "$BASE/api/auth/verify" -H "$H_AUTH" -H "$H_ACCEPT")
CODE=$(echo "$RESP" | tail -1); BODY=$(echo "$RESP" | head -1)
assert_status "/api/auth/verify valid token → 200" "200" "$CODE"
assert_contains "/api/auth/verify returns valid:true" '"valid"' "$BODY"

# GET /api/auth/verify - invalid token → 401
echo "[6] GET /api/auth/verify (invalid token)"
CODE=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/api/auth/verify" \
  -H "Authorization: Bearer invalid_token_xyz")
assert_status "/api/auth/verify invalid token → 401" "401" "$CODE"

echo ""
echo "PASS: $PASS  FAIL: $FAIL"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
