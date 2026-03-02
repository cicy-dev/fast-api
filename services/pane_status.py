"""Pane status detection service — 统一状态检测逻辑"""
import subprocess, re

def run_tmux(cmd):
    r = subprocess.run(["tmux"] + cmd, capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""

def get_worker_panes():
    out = run_tmux(["list-sessions", "-F", "#{session_name}"])
    return [s for s in out.split('\n') if s.startswith('w-')]

def check_pane(pane_id: str) -> dict:
    """检测 pane 状态，返回完整状态 dict"""
    target = f"{pane_id}:main.0" if ':' not in pane_id else pane_id
    raw = run_tmux(["capture-pane", "-t", target, "-p"])
    lines = [l for l in raw.split('\n') if l.strip()]
    text = '\n'.join(lines[-4:])
    last2 = ' '.join(lines[-2:]) if len(lines) >= 2 else ' '.join(lines)
    last = lines[-1] if lines else ''

    ctx_matches = re.findall(r'(\d+)%?\s*!?>\s*$', raw, re.MULTILINE)
    context_usage = int(ctx_matches[-1]) if ctx_matches else None

    is_waiting_auth = 'Allow this action' in last2 or '[y/n/t]' in last2
    is_compacting = 'Creating summary' in last2 or '/compact' in last2
    is_thinking = bool(re.search(r'[⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏]', last2))
    is_idle = last.rstrip().endswith('>') or last.rstrip().endswith('$')
    is_wait_startup = len(lines) == 0 or (is_idle and last.rstrip().endswith('$'))

    if is_waiting_auth: status = 'wait_auth'
    elif is_compacting: status = 'compacting'
    elif is_thinking and not is_idle: status = 'thinking'
    elif is_idle: status = 'idle'
    elif is_wait_startup: status = 'wait_startup'
    else: status = 'thinking'

    return {
        "pane_id": pane_id.replace(":main.0", ""),
        "raw": text, "status": status,
        "isThinking": is_thinking or is_compacting,
        "isWaitingAuth": is_waiting_auth,
        "isCompacting": is_compacting,
        "isWaitStartup": is_wait_startup,
        "contextUsage": context_usage,
    }

def send_keys(pane_id: str, keys: str):
    target = f"{pane_id}:main.0" if ':' not in pane_id else pane_id
    run_tmux(["send-keys", "-t", target, keys])

def send_text(pane_id: str, text: str):
    target = f"{pane_id}:main.0" if ':' not in pane_id else pane_id
    run_tmux(["send-keys", "-t", target, "-l", text])
    import time; time.sleep(0.3)
    run_tmux(["send-keys", "-t", target, "Enter"])
