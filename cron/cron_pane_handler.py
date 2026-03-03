"""Cron: 自动处理 tmux pane 状态 — auto yes, auto compact"""
import time, os, sys, pymysql, json
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from pathlib import Path
env_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
for line in Path(env_file).read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())
from services.pane_status import check_pane_active, send_keys, send_text

try:
    import redis
    REDIS_ENABLED = True
except ImportError:
    REDIS_ENABLED = False

INTERVAL = int(os.getenv("PANE_CHECK_INTERVAL", "5"))
COMPACT_THRESHOLD = int(os.getenv("COMPACT_THRESHOLD", "70"))
REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))

def get_active_panes():
    conn = pymysql.connect(
        host=os.getenv("MYSQL_HOST", "127.0.0.1"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        user=os.getenv("MYSQL_USER", "root"),
        password=os.getenv("MYSQL_PASSWORD", ""),
        database=os.getenv("MYSQL_DATABASE", "tts_bot"),
        cursorclass=pymysql.cursors.DictCursor
    )
    try:
        with conn.cursor() as c:
            c.execute("SELECT pane_id FROM ttyd_config WHERE active=1")
            return [r["pane_id"] for r in c.fetchall()]
    finally:
        conn.close()

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

def main():
    once = "--once" in sys.argv
    r = None
    if REDIS_ENABLED:
        try:
            r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB)
            r.ping()
        except Exception as e:
            log(f"redis unavailable: {e}")
            r = None
    
    log(f"started | interval={INTERVAL}s compact={COMPACT_THRESHOLD}% once={once} redis={r is not None}")
    
    while True:
        try:
            check_time = int(time.time())
            panes = get_active_panes()
            status_map = {}
            
            for p in panes:
                try:
                    d = check_pane_active(p)
                    
                    # Add checkTime and timeAgo
                    d["checkTime"] = check_time
                    if d.get("lastUpdateAt"):
                        d["timeAgo"] = check_time - d["lastUpdateAt"]
                    else:
                        d["timeAgo"] = None
                    
                    status_map[p] = d
                    
                    s, ctx = d.get("status"), d.get("contextUsage")
                    if s == "wait_auth":
                        log(f"{p}: wait_auth → yes")
                        send_keys(p, "y")
                        time.sleep(0.5)
                        send_keys(p, "Enter")
                        time.sleep(3)
                    elif s == "idle" and ctx and ctx > COMPACT_THRESHOLD:
                        log(f"{p}: ctx={ctx}% → /compact")
                        send_text(p, "/compact")
                    else:
                        log(f"{p}: {s} ctx={ctx}")
                except Exception as e:
                    log(f"{p}: error - {e}")
                    status_map[p] = {"error": str(e), "pane_id": p, "checkTime": check_time}
            
            if r:
                try:
                    r.set("pane_status_map", json.dumps(status_map, default=str))
                    log(f"cached {len(status_map)} panes to redis")
                except Exception as e:
                    log(f"redis write error: {e}")
            
            # Always write to state.json
            try:
                with open("state.json", "w") as f:
                    json.dump(status_map, f, indent=2, default=str)
            except Exception as e:
                log(f"state.json write error: {e}")
                
        except Exception as e:
            log(f"error: {e}")
        if once:
            break
        time.sleep(INTERVAL)

if __name__ == "__main__":
    main()
