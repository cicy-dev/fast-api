#!/bin/bash
# fast-api/tests/curl/test_services.sh
set -euo pipefail

BASE=${FAST_API_URL:-http://localhost:14444}
TOKEN=$(python3 -c "import json; print(json.load(open('/home/w3c_offical/global.json'))['api_token'])")
H_AUTH="Authorization: Bearer $TOKEN"
H_JSON="Content-Type: application/json"
H_ACCEPT="Accept: application/json"

PASS=0; FAIL=0
TEST_PORT=19999

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

echo "=== test_services.sh ==="

# Cleanup: delete test service if exists
curl -s -X DELETE "$BASE/api/services/$TEST_PORT" -H "$H_AUTH" > /dev/null 2>&1 || true

# GET /api/services
echo "[1] GET /api/services"
RESP=$(curl -s -w '\n%{http_code}' "$BASE/api/services" -H "$H_AUTH" -H "$H_ACCEPT")
CODE=$(echo "$RESP" | tail -1); BODY=$(echo "$RESP" | head -1)
assert_status "/api/services → 200" "200" "$CODE"
assert_contains "/api/services contains services" '"services"' "$BODY"

# GET /api/services - no token → 403
echo "[2] GET /api/services (no token)"
CODE=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/api/services")
assert_status "/api/services no token → 401" "401" "$CODE"

# POST /api/services (create)
echo "[3] POST /api/services (create)"
RESP=$(curl -s -w '\n%{http_code}' -X POST "$BASE/api/services" \
  -H "$H_AUTH" -H "$H_JSON" -H "$H_ACCEPT" \
  -d "{\"port\":$TEST_PORT,\"name\":\"test-e2e\",\"description\":\"TDD test service\",\"status\":\"unknown\"}")
CODE=$(echo "$RESP" | tail -1); BODY=$(echo "$RESP" | head -1)
assert_status "/api/services create → 200" "200" "$CODE"
assert_contains "/api/services create → success:true" '"success"' "$BODY"

# GET /api/services/{port}
echo "[4] GET /api/services/$TEST_PORT"
RESP=$(curl -s -w '\n%{http_code}' "$BASE/api/services/$TEST_PORT" -H "$H_AUTH" -H "$H_ACCEPT")
CODE=$(echo "$RESP" | tail -1); BODY=$(echo "$RESP" | head -1)
assert_status "/api/services/{port} → 200" "200" "$CODE"
assert_contains "/api/services/{port} contains port" "$TEST_PORT" "$BODY"
assert_contains "/api/services/{port} contains name" '"test-e2e"' "$BODY"

# POST /api/services (upsert - update name)
echo "[5] POST /api/services (upsert/update)"
RESP=$(curl -s -w '\n%{http_code}' -X POST "$BASE/api/services" \
  -H "$H_AUTH" -H "$H_JSON" -H "$H_ACCEPT" \
  -d "{\"port\":$TEST_PORT,\"name\":\"test-e2e-updated\",\"status\":\"running\"}")
CODE=$(echo "$RESP" | tail -1); BODY=$(echo "$RESP" | head -1)
assert_status "/api/services upsert → 200" "200" "$CODE"

# DELETE /api/services/{port}
echo "[6] DELETE /api/services/$TEST_PORT"
RESP=$(curl -s -w '\n%{http_code}' -X DELETE "$BASE/api/services/$TEST_PORT" -H "$H_AUTH" -H "$H_ACCEPT")
CODE=$(echo "$RESP" | tail -1); BODY=$(echo "$RESP" | head -1)
assert_status "/api/services delete → 200" "200" "$CODE"
assert_contains "/api/services delete → success:true" '"success"' "$BODY"

# Verify deleted
echo "[7] GET /api/services/$TEST_PORT (after delete)"
RESP=$(curl -s -w '\n%{http_code}' "$BASE/api/services/$TEST_PORT" -H "$H_AUTH" -H "$H_ACCEPT")
BODY=$(echo "$RESP" | head -1)
assert_contains "/api/services/{port} not found → error" '"error"' "$BODY"

echo ""
echo "PASS: $PASS  FAIL: $FAIL"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
