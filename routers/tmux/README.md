# Tmux API

Centralized HTTP API for tmux operations.

## Quick Start

```bash
# Get token
TOKEN=$(jq -r '.api_token' ~/global.json)

# Send command
curl -H "Authorization: Bearer $TOKEN" \
  -d '{"win_id": "master:cicy_master_xk_bot.0", "text": "echo hello"}' \
  http://localhost:14444/api/tmux/send
```

## API Endpoints

| Method | Endpoint | Payload | Description |
|--------|----------|---------|-------------|
| POST | `/api/tmux/send` | `{"win_id": "...", "text": "..."}` | Send text |
| POST | `/api/tmux/send` | `{"win_id": "...", "keys": "Enter"}` | Send keys |
| POST | `/api/tmux/capture_pane` | `{"pane_id": "...", "start": -100, "end": -1}` | Capture pane output |
| GET | `/api/tmux/tree` | - | Get full tree |


**Tree**
```bash
curl -H "Authorization: Bearer $(jq -r '.api_token' ~/global.json)" \
  http://localhost:14444/api/tmux/tree
```

**Clsar**
```bash
curl -X POST -H "Authorization: Bearer $(jq -r '.api_token' ~/global.json)" \
  http://localhost:14444/api/tmux/clear
```


**Create**
```bash
curl -X POST -H "Authorization: Bearer $(jq -r '.api_token' ~/global.json)" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -d '{"win_name": "test", "session_name": "worker", "dev": false}' \
  http://localhost:14444/api/tmux/create
```


## Send Examples

**Send text:**
```bash
curl -H "Authorization: Bearer $TOKEN" \
  -d '{"win_id": "master:cicy_master_xk_bot.0", "text": "echo hello"}' \
  http://localhost:14444/api/tmux/send
```

**Send Enter:**
```bash
curl -H "Authorization: Bearer $TOKEN" \
  -d '{"win_id": "master:cicy_master_xk_bot.0", "keys": "Enter"}' \
  http://localhost:14444/api/tmux/send
```


**Send to specific pane:**
```bash
curl -H "Authorization: Bearer $TOKEN" \
  -d '{"win_id": "master:cicy_master_xk_bot.1", "text": "hello"}' \
  http://localhost:14444/api/tmux/send
```

**Available keys:** `Enter`, `Escape`, `Space`, `Left`, `Right`, `Up`, `Down`, `C-c`, `C-d`

## Capture Pane

**Capture all output:**
```bash
curl -H "Authorization: Bearer $TOKEN" \
  -d '{"pane_id": "master:cicy_master_xk_bot.0"}' \
  http://localhost:14444/api/tmux/capture_pane
```

**Capture last 100 lines:**
```bash
curl -H "Authorization: Bearer $TOKEN" \
  -d '{"pane_id": "master:cicy_master_xk_bot.0", "start": -100, "end": -1}' \
  http://localhost:14444/api/tmux/capture_pane
```

**Capture specific range:**
```bash
curl -H "Authorization: Bearer $TOKEN" \
  -d '{"pane_id": "master:cicy_master_xk_bot.0", "start": 0, "end": 50}' \
  http://localhost:14444/api/tmux/capture_pane
```

## Response Format

**Default (YAML):**
```yaml
sessions:
- name: master
  windows: 1
```

**JSON (with Accept header):**
```bash
curl -H "Accept: application/json" -H "Authorization: Bearer $TOKEN" \
  http://localhost:14444/api/tmux/tree
```

## Authentication

All `/api/*` endpoints require Bearer token from `~/global.json`:

```bash
TOKEN=$(jq -r '.api_token' ~/global.json)
```

## Python Example

```python
import requests
import json
import os

# Load token
with open(os.path.expanduser("~/global.json")) as f:
    TOKEN = json.load(f)["api_token"]

headers = {"Authorization": f"Bearer {TOKEN}"}

# Send text
requests.post("http://localhost:14444/api/tmux/send", 
    headers=headers,
    json={"win_id": "master:cicy_master_xk_bot.0", "text": "echo hello"})

# Send Enter
requests.post("http://localhost:14444/api/tmux/send",
    headers=headers, 
    json={"win_id": "master:cicy_master_xk_bot.0", "keys": "Enter"})

# Capture pane output
resp = requests.post("http://localhost:14444/api/tmux/capture_pane",
    headers=headers,
    json={"pane_id": "master:cicy_master_xk_bot.0", "start": -100, "end": -1})
print(resp.json()["output"])
```
