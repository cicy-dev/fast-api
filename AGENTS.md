# AI Agents Guide - fast-api

## Project Overview

FastAPI-based REST API for managing tmux sessions, windows, panes, and ttyd (web terminal) instances. Uses MySQL for persistence.

## Commands

### Run the Server

```bash
cd fast-api
source venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 14444 --reload
```

Or via Docker:

```bash
cd fast-api
docker compose up -d
```

### Run Tests

Run all tests (pre-commit required):

```bash
cd fast-api
bash run_tests.sh
```

Run single pytest test:

```bash
docker exec fast-api python -m pytest tests/test_create_window.py::TestCreateWindow::test_create_window -v
```

Run single curl test:

```bash
bash tests/curl/test_health.sh
```

### Linting

No formal linter configured. Follow code style guidelines below.

## Code Style Guidelines

### General

- Use 4 spaces for indentation (no tabs)
- No trailing whitespace
- Max line length: 120 characters (soft limit)
- Use descriptive variable/function names

### Imports

Standard library first, then third-party, then local:

```python
import os
import subprocess
import re
from typing import Optional

import pymysql
import yaml
from fastapi import APIRouter, HTTPException, Request

from routers.tmux.router import run_tmux
```

### Type Hints

- Use Python 3.10+ union syntax: `str | None` (not `Optional[str]`)
- Use `dict` for generic dicts, not `Dict[str, Any]`
- Return type hints on functions when non-trivial:

```python
def run_tmux(cmd: list[str], check_session: bool = False) -> str | None:
    ...
```

### Naming Conventions

| Type | Convention | Example |
|------|------------|---------|
| Functions | snake_case | `get_db()`, `create_ttyd_pane_common()` |
| Classes | PascalCase | `WindowCreate`, `ServiceIn` |
| Constants | UPPER_SNAKE | `MYSQL_HOST`, `TTYD_PORT_RANGE_PROD` |
| Variables | snake_case | `session_check`, `pane_id` |
| Private functions | prefix with `_` | `_load_api_token()` |

### Pydantic Models

```python
class WindowCreate(BaseModel):
    win_name: str
    dev: bool = False
    workspace: Optional[str] = None
    init_script: str = "pwd"
    
    @field_validator('win_name')
    @classmethod
    def validate_win_name(cls, v):
        if not re.match(r'^[a-zA-Z0-9_]+$', v):
            raise ValueError('win_name must contain only alphanumeric characters and underscores')
        return v
```

- Use `Optional[str] = None` for optional fields with defaults
- Use Pydantic v2 validators for input validation
- Always validate user input (regex, length, etc.)

### Error Handling

- Use `HTTPException(status_code=400, detail="message")` for API errors
- Use `try/except` with specific exceptions, then `pass` or re-raise
- Return `None` for "not found" cases when appropriate:

```python
def run_tmux(cmd, check_session=False):
    result = subprocess.run(...)
    if result.returncode != 0:
        if check_session and ("no server running" in err or "can't find session" in err):
            return None
        raise HTTPException(status_code=400, detail=result.stderr.strip())
    return result.stdout.strip()
```

### Database

- Use pymysql with DictCursor for named column access
- Always close connections with `finally` block or context manager
- Use parameterized queries ( `%s` placeholders):

```python
conn = pymysql.connect(host=MYSQL_HOST, port=MYSQL_PORT, ...)
try:
    with conn.cursor() as c:
        c.execute("SELECT pane_id FROM ttyd_config WHERE pane_id=%s", (pane_id,))
        row = c.fetchone()
finally:
    conn.close()
```

### FastAPI Endpoints

- Use `async def` for endpoints
- Include auth dependency on routers:

```python
app.include_router(tmux_router, dependencies=[Depends(verify_token)])
```

- Use `Request` parameter for YAML/JSON response negotiation:


### Response Formatting

Use `format_response()` helper for dual format support:

```python
def format_response(data: dict, request: Request = None):
    if request and is_yaml(request):
        yaml_str = yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)
        return PlainTextResponse(yaml_str, media_type="application/yaml")
    return data
```

### Tmux Integration

- Each pane should have its own unique tmux session (no shared sessions)

### File Organization

```
fast-api/
├── main.py              # App entry, health endpoints, service CRUD
├── routers/
│   ├── __init__.py
│   ├── tmux/
│   │   └── router.py   # Tmux session/window/pane management
│   ├── ttyd.py         # TTYD service management
│   └── groups.py       # Group management
├── tests/
│   ├── test_*.py       # Pytest tests
│   └── curl/
│       └── test_*.sh   # Shell-based API tests
└── DOCS/
    ├── ARCHITECTURE.md
    └── DEVELOPMENT.md
```

### Environment Variables

Required in `.env` (copy from `.env.example`):

```
TMUX_SOCKET=
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=...
MYSQL_DATABASE=tts_bot
TTYD_PORT_RANGE_DEV=16100-16200
TTYD_PORT_RANGE_PROD=15100-15300
```

### Testing Guidelines

- Tests must clean up created resources (tmux sessions, files)
- Use timestamps in test names to avoid conflicts: `test_win_{int(time.time())}`
- Wait for async operations: `time.sleep()` after pane creation
- Test both success and failure paths

### Commit Messages

Follow conventional commits:

```
feat: add new endpoint
fix: resolve pane display sync
docs: update API documentation
```

### Security

- Never commit secrets (use `.env` and `.gitignore`)
- Validate all user input (regex, length checks)
- Use authentication on all production endpoints
