"""Cron: 自动处理 tmux pane 状态 — auto yes, auto compact"""
import time, os, sys, pymysql
sys.path.insert(0, os.path.dirname(__file__))
from pathlib import Path
for line in Path(os.path.join(os.path.dirname(__file__), ".env")).read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())
from services.pane_status import check_pane, send_keys, send_text

INTERVAL = int(os.getenv("PANE_CHECK_INTERVAL", "30"))
COMPACT_THRESHOLD = int(os.getenv("COMPACT_THRESHOLD", "70"))

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
    log(f"started | interval={INTERVAL}s compact={COMPACT_THRESHOLD}%")
    while True:
        try:
            panes = get_active_panes()
            for p in panes:
                d = check_pane(p)
                s, ctx = d["status"], d["contextUsage"]
                if s == "wait_auth":
                    log(f"{p}: wait_auth → yes")
                    send_keys(p, "y")
                    time.sleep(0.5)
                    send_keys(p, "Enter")
                    time.sleep(3)  # 等待处理完成
                elif s == "idle" and ctx and ctx > COMPACT_THRESHOLD:
                    log(f"{p}: ctx={ctx}% → /compact")
                    send_text(p, "/compact")
                else:
                    log(f"{p}: {s} ctx={ctx}")
        except Exception as e:
            log(f"error: {e}")
        time.sleep(INTERVAL)

if __name__ == "__main__":
    main()
