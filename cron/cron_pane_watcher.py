"""Watcher: inotify 实时监听 pipe log 变化，即时更新 Redis pane 状态"""
import time, os, sys, json, re, threading
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from pathlib import Path

env_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
for line in Path(env_file).read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

import redis as _redis
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from services.pane_status import check_pane_active, send_keys, send_text

COMPACT_THRESHOLD = int(os.getenv("COMPACT_THRESHOLD", "70"))
FULL_SYNC_INTERVAL = int(os.getenv("FULL_SYNC_INTERVAL", "30"))
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
REDIS_KEY = "pane_status_map"

# pane_id -> config row cache, refreshed by full sync
_config_cache = {}
_lock = threading.Lock()

# pane_id -> last action timestamp, prevent duplicate sends
_action_cooldown = {}
ACTION_COOLDOWN_SEC = 3  # 同一 pane 的 auto action 至少间隔 3 秒

def get_redis():
    return _redis.Redis(
        host=os.getenv("REDIS_HOST", "127.0.0.1"),
        port=int(os.getenv("REDIS_PORT", "6379")),
        db=int(os.getenv("REDIS_DB", "0")),
    )

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

def filename_to_pane_id(filename):
    """pipe-w-20077_main_0.log -> w-20077:main.0"""
    m = re.match(r"pipe-(.+)\.log$", filename)
    if not m:
        return None
    raw = m.group(1)  # w-20077_main_0
    parts = raw.rsplit("_", 2)  # ['w-20077', 'main', '0']
    if len(parts) == 3:
        return f"{parts[0]}:{parts[1]}.{parts[2]}"
    return None

def get_active_panes():
    from db_pool import get_db
    conn = get_db()
    try:
        with conn.cursor() as c:
            c.execute("SELECT pane_id, title, agent_type FROM ttyd_config WHERE active=1")
            return c.fetchall()
    finally:
        conn.close()

def _do_auto_action(pane_id, d):
    """统一 auto action，带 cooldown 防重复"""
    s, ctx = d.get("status"), d.get("contextUsage")
    now = time.time()
    last = _action_cooldown.get(pane_id, 0)
    if now - last < ACTION_COOLDOWN_SEC:
        return
    if s == "wait_auth":
        log(f"{pane_id}: wait_auth → t (trust)")
        _action_cooldown[pane_id] = now
        send_keys(pane_id, "t")
        time.sleep(0.5)
        send_keys(pane_id, "Enter")
    elif s == "idle" and ctx and ctx > COMPACT_THRESHOLD:
        log(f"{pane_id}: ctx={ctx}% → /compact")
        _action_cooldown[pane_id] = now
        send_text(pane_id, "/compact")


def process_pane(pane_id, r, config=None):
    """检查单个 pane 状态并更新 Redis"""
    check_time = int(time.time())
    d = check_pane_active(pane_id, config=config)
    d["checkTime"] = check_time
    if d.get("lastUpdateAt"):
        d["timeAgo"] = check_time - d["lastUpdateAt"]
    else:
        d["timeAgo"] = None
    if config:
        d["title"] = config.get("title")

    # 更新 Redis 中的单个 pane
    with _lock:
        raw = r.get(REDIS_KEY)
        status_map = json.loads(raw) if raw else {}
        prev = status_map.get(pane_id, {})
        # thinking 状态保护：只有明确 idle/wait_auth/compacting 才能解除
        if prev.get("status") == "thinking" and d.get("status") not in ("idle", "wait_auth", "compacting"):
            d["status"] = "thinking"
        status_map[pane_id] = d
        r.set(REDIS_KEY, json.dumps(status_map, default=str))

    _do_auto_action(pane_id, d)
    return d

def ensure_pipe_pane(pane_id):
    """确保 pipe-pane 在运行，没有则自动开启"""
    import subprocess
    target = f"{pane_id}:main.0" if ':' not in pane_id else pane_id
    try:
        pp = subprocess.run(
            ["tmux", "display-message", "-t", target, "-p", "#{pane_pipe}"],
            capture_output=True, text=True, timeout=5
        )
        if pp.stdout.strip() == "0":
            log_file = os.path.join(LOG_DIR, f"pipe-{target.replace(':', '_').replace('.', '_')}.log")
            subprocess.run(
                ["tmux", "pipe-pane", "-t", target, f"cat >> {log_file}"],
                capture_output=True, timeout=5
            )
            return True
    except Exception:
        pass
    return False

def full_sync(r):
    """全量同步：刷新 config 缓存 + 更新所有 pane 状态"""
    global _config_cache
    rows = get_active_panes()
    new_cache = {row["pane_id"]: row for row in rows}
    _config_cache = new_cache

    status_map = {}
    restored = 0
    # 读取上一次的状态用于 thinking 保护
    with _lock:
        prev_raw = r.get(REDIS_KEY)
        prev_map = json.loads(prev_raw) if prev_raw else {}
    for pane_id, config in new_cache.items():
        try:
            if ensure_pipe_pane(pane_id):
                restored += 1
            check_time = int(time.time())
            d = check_pane_active(pane_id, config=config)
            d["checkTime"] = check_time
            if d.get("lastUpdateAt"):
                d["timeAgo"] = check_time - d["lastUpdateAt"]
            else:
                d["timeAgo"] = None
            d["title"] = config.get("title")
            # thinking 状态保护
            prev = prev_map.get(pane_id, {})
            if prev.get("status") == "thinking" and d.get("status") not in ("idle", "wait_auth", "compacting"):
                d["status"] = "thinking"
            status_map[pane_id] = d

            _do_auto_action(pane_id, d)
        except Exception as e:
            log(f"{pane_id}: error - {e}")
            status_map[pane_id] = {"error": str(e), "pane_id": pane_id, "checkTime": int(time.time())}

    with _lock:
        r.set(REDIS_KEY, json.dumps(status_map, default=str))
    if restored:
        log(f"full sync: {len(status_map)} panes, restored {restored} pipe-pane")
    else:
        log(f"full sync: {len(status_map)} panes")


class PipeLogHandler(FileSystemEventHandler):
    """监听 pipe log 文件修改事件"""

    def __init__(self, r):
        self.r = r
        # debounce: 每个 pane 最近处理时间
        self._last = {}
        self._debounce = 0.5  # 秒

    def on_modified(self, event):
        if event.is_directory:
            return
        filename = os.path.basename(event.src_path)
        if not filename.startswith("pipe-") or not filename.endswith(".log"):
            return

        pane_id = filename_to_pane_id(filename)
        if not pane_id:
            return

        # debounce
        now = time.time()
        if pane_id in self._last and now - self._last[pane_id] < self._debounce:
            return
        self._last[pane_id] = now

        config = _config_cache.get(pane_id)
        try:
            d = process_pane(pane_id, self.r, config=config)
            s = d.get("status")
            if s and s != "idle":
                log(f"[watch] {pane_id}: {s}")
        except Exception as e:
            log(f"[watch] {pane_id}: error - {e}")


def main():
    r = get_redis()
    r.ping()
    log(f"started | log_dir={LOG_DIR} full_sync_interval={FULL_SYNC_INTERVAL}s")

    # 初始全量同步
    full_sync(r)

    # 启动 inotify watcher
    handler = PipeLogHandler(r)
    observer = Observer()
    observer.schedule(handler, LOG_DIR, recursive=False)
    observer.start()
    log("inotify watcher started")

    try:
        while True:
            time.sleep(FULL_SYNC_INTERVAL)
            try:
                full_sync(r)
            except Exception as e:
                log(f"full sync error: {e}")
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


if __name__ == "__main__":
    main()
