"""Pane status detection service — 统一状态检测逻辑"""
import subprocess
import re
import pymysql
import argparse
from typing import Optional
from db_pool import get_db


def run_tmux(cmd: list[str]) -> str:
    r = subprocess.run(["tmux"] + cmd, capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def session_exists(session_name: str) -> bool:
    """Check if tmux session exists"""
    result = run_tmux(["list-sessions", "-F", "#{session_name}"])
    return session_name in result.split('\n')


def get_worker_panes() -> list[str]:
    """Get all worker pane sessions"""
    out = run_tmux(["list-sessions", "-F", "#{session_name}"])
    return [s for s in out.split('\n') if s.startswith('w-')]


def _guess_agent_type(text: str, lines: list[str]) -> str:
    """Guess agent type from output patterns"""
    # Only check last 2000 chars to avoid regex on huge TUI output
    sample = text[-2000:] if len(text) > 2000 else text
    
    # Kiro CLI patterns (check first - more specific)
    kiro_patterns = [
        "I will run the following command",
        "Purpose:",
        "\\(using tool:",
        "Looking up symbols",
        "Found.*symbols",
        "Completed in.*s"
    ]
    if any(re.search(pattern, sample) for pattern in kiro_patterns):
        return "kiro-cli"
    
    # OpenCode patterns (check after kiro-cli)
    opencode_patterns = [
        "▣.*Build.*trinity",
        "Build.*Trinity.*OpenCode",
        "█▀▀█ █▀▀█ █▀▀█",
        "Ask anything"
    ]
    if any(re.search(pattern, sample, re.IGNORECASE) for pattern in opencode_patterns):
        return "opencode"
    
    # Shell patterns
    last_line = lines[-1] if lines else ""
    if last_line.rstrip().endswith('$') or last_line.rstrip().endswith('#'):
        return "shell"
    
    return "unknown"


def _make_status(agent_type: str | None = None, active: bool = True) -> dict:
    """Return standardized status template"""
    return {
        "pane_id": None,
        "agent_type": agent_type,
        "active": active,
        "status": None,
        "isThinking": None,
        "isWaitingAuth": None,
        "isCompacting": None,
        "isWaitStartup": None,
        "isIdle": None,
        "contextUsage": None,
        "credits": None,
        "elapsedTime": None,
        "raw": None,
        "currentTask": None,
        "guess": None,  # Guessed agent type
    }


def _parse_kiro_cli(pane_id: str, text: str, last2: str, lines: list[str]) -> dict:
    """Parse kiro-cli agent status"""
    status_dict = _make_status("kiro-cli")
    status_dict["pane_id"] = pane_id
    
    # Extract context usage: "34% >"
    ctx_matches = re.findall(r'(\d+)%?\s*!?>\s*$', text, re.MULTILINE)
    status_dict["contextUsage"] = int(ctx_matches[-1]) if ctx_matches else None
    
    # Extract credits: "Credits: 0.57"
    credits_match = re.search(r'Credits:\s*([\d.]+)', last2)
    status_dict["credits"] = float(credits_match.group(1)) if credits_match else None
    
    # Extract elapsed time: "Time: 10s"
    time_match = re.search(r'Time:\s*(\d+)s', last2)
    status_dict["elapsedTime"] = int(time_match.group(1)) if time_match else None
    
    # Detect status
    is_waiting_auth = 'Allow this action' in last2 or '[y/n/t]' in last2
    is_compacting = 'Creating summary' in last2 or '/compact' in last2
    is_thinking = bool(re.search(r'[⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏]', last2))
    last = lines[-1] if lines else ''
    is_idle = last.rstrip().endswith('>') or last.rstrip().endswith('$')
    
    if is_waiting_auth:
        status_dict["status"] = "wait_auth"
    elif is_compacting:
        status_dict["status"] = "compacting"
    elif is_thinking and not is_idle:
        status_dict["status"] = "thinking"
    elif is_idle:
        status_dict["status"] = "idle"
    else:
        status_dict["status"] = None
    
    status_dict["isThinking"] = is_thinking or is_compacting
    status_dict["isWaitingAuth"] = is_waiting_auth
    status_dict["isCompacting"] = is_compacting
    status_dict["isIdle"] = is_idle
    status_dict["raw"] = text
    
    return status_dict


def _parse_opencode(pane_id: str, text: str, last2: str, lines: list[str]) -> dict:
    """Parse opencode agent status"""
    status_dict = _make_status("opencode")
    status_dict["pane_id"] = pane_id
    
    # Extract context usage: "7% used"
    ctx_match = re.search(r'(\d+)%\s+used', text)
    status_dict["contextUsage"] = int(ctx_match.group(1)) if ctx_match else None
    
    # Extract current task: "Thinking: ..."
    task_match = re.search(r'Thinking:\s*(.+?)(?:\n|$)', text)
    status_dict["currentTask"] = task_match.group(1).strip() if task_match else None
    
    # Detect status
    is_thinking = 'Thinking:' in text or bool(re.search(r'⬝⬝■■', text))
    is_waiting_auth = 'Allow this action' in last2 or '[y/n/t]' in last2
    last = lines[-1] if lines else ''
    is_idle = last.rstrip().endswith('>') or last.rstrip().endswith('$')
    
    if is_waiting_auth:
        status_dict["status"] = "wait_auth"
    elif is_thinking and not is_idle:
        status_dict["status"] = "thinking"
    elif is_idle:
        status_dict["status"] = "idle"
    else:
        status_dict["status"] = None
    
    status_dict["isThinking"] = is_thinking
    status_dict["isWaitingAuth"] = is_waiting_auth
    status_dict["isIdle"] = is_idle
    # Limit raw output for OpenCode (keep last 10 lines)
    status_dict["raw"] = "\n".join(text.split("\n")[-10:])
    
    return status_dict


def _parse_claude_code(pane_id: str, text: str, last2: str, lines: list[str]) -> dict:
    """Parse claude_code agent status (placeholder)"""
    status_dict = _make_status("claude_code")
    status_dict["pane_id"] = pane_id
    status_dict["raw"] = text
    return status_dict


def _parse_gemini(pane_id: str, text: str, last2: str, lines: list[str]) -> dict:
    """Parse gemini agent status (placeholder)"""
    status_dict = _make_status("gemini")
    status_dict["pane_id"] = pane_id
    status_dict["raw"] = text
    return status_dict


def _parse_default(pane_id: str, text: str, last2: str, lines: list[str]) -> dict:
    """Default parser for unknown agent types"""
    status_dict = _make_status()
    status_dict["pane_id"] = pane_id
    
    # Basic status detection
    is_waiting_auth = 'Allow this action' in last2 or '[y/n/t]' in last2
    is_thinking = bool(re.search(r'[⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏]', last2))
    last = lines[-1] if lines else ''
    is_idle = last.rstrip().endswith('>') or last.rstrip().endswith('$')
    
    if is_waiting_auth:
        status_dict["status"] = "wait_auth"
    elif is_thinking and not is_idle:
        status_dict["status"] = "thinking"
    elif is_idle:
        status_dict["status"] = "idle"
    else:
        status_dict["status"] = None
    
    status_dict["isThinking"] = is_thinking
    status_dict["isWaitingAuth"] = is_waiting_auth
    status_dict["isIdle"] = is_idle
    status_dict["raw"] = text
    
    return status_dict


PARSERS = {
    "kiro-cli": _parse_kiro_cli,
    "opencode": _parse_opencode,
    "claude_code": _parse_claude_code,
    "gemini": _parse_gemini,
}


from functools import lru_cache
import time

# Cache with TTL
_pane_config_cache = {}
_cache_ttl = 30  # 30 seconds

@lru_cache(maxsize=128)
def get_pane_config(pane_id: str) -> dict | None:
    """Get pane configuration from ttyd_config table (cached)"""
    cache_key = pane_id
    now = time.time()
    
    # Check cache first
    if cache_key in _pane_config_cache:
        cached_data, timestamp = _pane_config_cache[cache_key]
        if now - timestamp < _cache_ttl:
            return cached_data
    
    # Fetch from database
    conn = get_db()
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as c:
            # Try exact match first
            c.execute(
                "SELECT pane_id, title, agent_type FROM ttyd_config WHERE pane_id=%s",
                (pane_id,)
            )
            result = c.fetchone()
            if result:
                _pane_config_cache[cache_key] = (result, now)
                return result
            
            # If not found and doesn't contain ':', try with :main.0
            if ':' not in pane_id:
                c.execute(
                    "SELECT pane_id, title, agent_type FROM ttyd_config WHERE pane_id=%s",
                    (f"{pane_id}:main.0",)
                )
                result = c.fetchone()
                _pane_config_cache[cache_key] = (result, now)
                return result
            
            _pane_config_cache[cache_key] = (None, now)
            return None
    finally:
        conn.close()


def check_pane(pane_id: str, lines: int = 4) -> dict:
    return {}
    """Check single pane status"""
    from routers.tmux.router import read_pipe_log
    
    target = f"{pane_id}:main.0" if ':' not in pane_id else pane_id
    active = session_exists(pane_id.split(':')[0])
    
    if not active:
        status_dict = _make_status(active=False)
        status_dict["pane_id"] = pane_id.replace(":main.0", "")
        config = get_pane_config(pane_id.replace(":main.0", ""))
        if config:
            status_dict["agent_type"] = config.get("agent_type")
        return status_dict
    
    # Try to read from pipe-pane log first
    raw = read_pipe_log(target, lines * 3)  # Read more lines to account for control chars
    
    if raw is None:
        # Fallback to capture-pane
        raw = run_tmux(["capture-pane", "-t", target, "-p"])
    
    pane_lines = [l for l in raw.split('\n') if l.strip()]
    text = '\n'.join(pane_lines[-lines:])
    last2 = ' '.join(pane_lines[-2:]) if len(pane_lines) >= 2 else ' '.join(pane_lines)
    
    # First guess agent type from output
    guess = _guess_agent_type(raw, pane_lines)
    
    # Get config for fallback
    clean_pane_id = pane_id.replace(":main.0", "")
    config = get_pane_config(clean_pane_id)
    config_agent_type = config.get("agent_type") if config else None
    
    # Use guess first, fallback to config, then default
    detected_type = guess if guess != "unknown" else config_agent_type
    parser = PARSERS.get(detected_type, _parse_default)
    
    status_dict = parser(clean_pane_id, text, last2, pane_lines)
    status_dict["active"] = True
    status_dict["agent_type"] = config_agent_type  # Keep original config
    status_dict["guess"] = guess
    
    return status_dict


def check_pane_active(pane_id: str, lines: int = 4, config: dict = None) -> dict:
    """Check pane status only if active and log exists"""
    from routers.tmux.router import read_pipe_log
    import os
    
    target = f"{pane_id}:main.0" if ':' not in pane_id else pane_id
    active = session_exists(pane_id.split(':')[0])
    
    if not active:
        return {"active": False, "pane_id": pane_id.replace(":main.0", "")}
    
    # Get log file path and check mtime
    log_file = f"./logs/pipe-{target.replace(':', '_').replace('.', '_')}.log"
    lastUpdateAt = None
    if os.path.exists(log_file):
        lastUpdateAt = int(os.path.getmtime(log_file))
    
    raw = read_pipe_log(target, lines * 3)
    if raw is None:
        # Fallback to capture-pane when pipe log doesn't exist
        try:
            raw = run_tmux(["capture-pane", "-t", target, "-p"])
        except Exception:
            return {"active": True, "log_exists": False, "pane_id": pane_id.replace(":main.0", ""), "lastUpdateAt": lastUpdateAt}
    
    if not raw:
        return {"active": True, "log_exists": False, "pane_id": pane_id.replace(":main.0", ""), "lastUpdateAt": lastUpdateAt}
    
    pane_lines = [l for l in raw.split('\n') if l.strip()]
    text = '\n'.join(pane_lines[-lines:])
    last2 = ' '.join(pane_lines[-2:]) if len(pane_lines) >= 2 else ' '.join(pane_lines)
    
    guess = _guess_agent_type(raw, pane_lines)
    clean_pane_id = pane_id.replace(":main.0", "")
    if config is None:
        config = get_pane_config(clean_pane_id)
    config_agent_type = config.get("agent_type") if config else None
    
    detected_type = guess if guess != "unknown" else config_agent_type
    parser = PARSERS.get(detected_type, _parse_default)
    
    status_dict = parser(clean_pane_id, text, last2, pane_lines)
    status_dict["active"] = True
    status_dict["log_exists"] = True
    status_dict["agent_type"] = config_agent_type
    status_dict["guess"] = guess
    status_dict["lastUpdateAt"] = lastUpdateAt
    
    return status_dict


import time

_status_cache = {}
_cache_ttl = 3  # 3秒缓存

def get_all_panes_status(
    lines: int = 4,
    include_inactive: bool = False,
    agent_type: str | None = None
) -> list[dict]:
    """Get status of all registered panes (with cache)"""
    cache_key = f"{lines}_{include_inactive}_{agent_type}"
    now = time.time()
    
    # Check cache
    if cache_key in _status_cache:
        cached_time, cached_data = _status_cache[cache_key]
        if now - cached_time < _cache_ttl:
            return cached_data
    
    # Fetch real data
    conn = get_db()
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as c:
            query = "SELECT pane_id, agent_type FROM ttyd_config WHERE 1=1"
            params = []
            
            if agent_type:
                query += " AND agent_type=%s"
                params.append(agent_type)
            
            c.execute(query, params)
            pane_configs = c.fetchall()
    finally:
        conn.close()
    
    statuses = []
    for config in pane_configs:
        pane_id = config.get("pane_id")
        status = check_pane(pane_id, lines)
        
        if include_inactive or status["active"]:
            statuses.append(status)
    
    # Update cache
    _status_cache[cache_key] = (now, statuses)
    return statuses


def send_keys(pane_id: str, keys: str):
    """Send keys to pane"""
    target = f"{pane_id}:main.0" if ':' not in pane_id else pane_id
    run_tmux(["send-keys", "-t", target, keys])


def send_text(pane_id: str, text: str):
    """Send text to pane"""
    import time
    target = f"{pane_id}:main.0" if ':' not in pane_id else pane_id
    run_tmux(["send-keys", "-t", target, "-l", text])
    time.sleep(0.3)
    run_tmux(["send-keys", "-t", target, "Enter"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pane status detection CLI")
    parser.add_argument("--pane", "-p", help="Check single pane status")
    parser.add_argument("--all", "-a", action="store_true", help="Check all panes")
    parser.add_argument("--lines", "-l", type=int, default=4, help="Last N lines (default: 4)")
    parser.add_argument("--include-inactive", "-i", action="store_true", help="Include inactive panes")
    parser.add_argument("--agent-type", "-t", help="Filter by agent type")
    parser.add_argument("--format", "-f", choices=["json", "table", "plain"], default="plain", help="Output format")
    
    args = parser.parse_args()
    
    if args.pane:
        status = check_pane(args.pane, args.lines)
        if args.format == "json":
            import json
            print(json.dumps(status, indent=2, ensure_ascii=False))
        else:
            print(f"pane_id:     {status['pane_id']}")
            print(f"agent_type:  {status.get('agent_type', 'N/A')}")
            print(f"active:      {status['active']}")
            print(f"status:      {status['status']}")
            print(f"isIdle:      {status.get('isIdle')}")
            print(f"isThinking:  {status.get('isThinking')}")
            if status.get('contextUsage'):
                print(f"context:     {status['contextUsage']}%")
            if status.get('credits'):
                print(f"credits:     {status['credits']}")
            if status.get('elapsedTime'):
                print(f"time:        {status['elapsedTime']}s")
    
    elif args.all:
        statuses = get_all_panes_status(args.lines, args.include_inactive, args.agent_type)
        
        if args.format == "json":
            import json
            print(json.dumps({"panes": statuses}, indent=2, ensure_ascii=False))
        
        elif args.format == "table":
            from tabulate import tabulate
            rows = []
            for s in statuses:
                rows.append([
                    s['pane_id'],
                    s.get('agent_type', 'unknown'),
                    'yes' if s['active'] else 'no',
                    s.get('status', '-'),
                    f"{s.get('contextUsage')}%" if s.get('contextUsage') else '-',
                    s.get('credits', '-')
                ])
            print(tabulate(rows, headers=['Pane ID', 'Type', 'Active', 'Status', 'Context', 'Credits']))
        
        else:
            for s in statuses:
                print(f"{s['pane_id']:15} {s.get('agent_type', 'unknown'):12} active={s['active']} status={s.get('status')}")
    
    else:
        parser.print_help()
