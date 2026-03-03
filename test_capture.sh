#!/bin/bash

API_TOKEN="1116568a729f18c9903038ff71e70aa1685888d9e8f4ca34419b9a5d9cf784ffdf1"
API_URL="http://localhost:14444"

echo "=== Creating new pane with test output ==="
RESPONSE=$(curl -s -X POST "$API_URL/api/tmux/create" \
  -H "Authorization: Bearer $API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "win_name": "test_capture",
    "init_script": "echo \"Test line 1\"\necho \"Test line 2\"\ndate\npwd\necho \"Test complete\"",
    "workspace": "~/test_ws"
  }')

echo "$RESPONSE" | python3 -m json.tool

PANE_ID=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('pane_id',''))")
LOG_FILE=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('log_file',''))" 2>/dev/null || echo "")

if [ -z "$LOG_FILE" ]; then
    SESSION=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('session',''))")
    LOG_FILE="/tmp/ttyd_${SESSION}_main_0.log"
fi

echo ""
echo "=== Waiting 5 seconds for output ==="
sleep 5

echo ""
echo "=== Log file content: $LOG_FILE ==="
if [ -f "$LOG_FILE" ]; then
    cat "$LOG_FILE"
else
    echo "Log file not found!"
fi

echo ""
echo "=== Cleanup: killing session ==="
if [ -n "$PANE_ID" ]; then
    SESSION=$(echo "$PANE_ID" | cut -d: -f1)
    tmux kill-session -t "$SESSION" 2>/dev/null || echo "Session already gone"
fi
