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
        status_map[pane_id] = d
        r.set(REDIS_KEY, json.dumps(status_map, default=str))

    # auto actions
    s, ctx = d.get("status"), d.get("contextUsage")
    if s == "wait_auth":
        log(f"{pane_id}: wait_auth → yes")
        send_keys(pane_id, "y")
        time.sleep(0.5)
        send_keys(pane_id, "Enter")
    elif s == "idle" and ctx and ctx > COMPACT_THRESHOLD:
        log(f"{pane_id}: ctx={ctx}% → /compact")
        send_text(pane_id, "/compact")

    return d

def full_sync(r):
    """全量同步：刷新 config 缓存 + 更新所有 pane 状态"""
    global _config_cache
    rows = get_active_panes()
    new_cache = {row["pane_id"]: row for row in rows}
    _config_cache = new_cache

    status_map = {}
    for pane_id, config in new_cache.items():
        try:
            check_time = int(time.time())
            d = check_pane_active(pane_id, config=config)
            d["checkTime"] = check_time
            if d.get("lastUpdateAt"):
                d["timeAgo"] = check_time - d["lastUpdateAt"]
            else:
                d["timeAgo"] = None
            d["title"] = config.get("title")
            status_map[pane_id] = d

            s, ctx = d.get("status"), d.get("contextUsage")
            if s == "wait_auth":
                log(f"{pane_id}: wait_auth → yes")
                send_keys(pane_id, "y")
                time.sleep(0.5)
                send_keys(pane_id, "Enter")
                time.sleep(3)
            elif s == "idle" and ctx and ctx > COMPACT_THRESHOLD:
                log(f"{pane_id}: ctx={ctx}% → /compact")
                send_text(pane_id, "/compact")
            else:
                log(f"{pane_id}: {s} ctx={ctx}")
        except Exception as e:
            log(f"{pane_id}: error - {e}")
            status_map[pane_id] = {"error": str(e), "pane_id": pane_id, "checkTime": int(time.time())}

    with _lock:
        r.set(REDIS_KEY, json.dumps(status_map, default=str))
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
