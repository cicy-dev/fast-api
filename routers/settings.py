from fastapi import APIRouter, Depends, HTTPException
from db_pool import get_db
import json

router = APIRouter()

@router.get("/api/settings/global")
async def get_global_settings():
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("SELECT `value` FROM global_var WHERE `key` = 'global_settings'")
        row = cur.fetchone()
        if row:
            return json.loads(row['value'])
        return {"favor": {"dir": [], "cmd": []}}
    finally:
        cur.close()
        conn.close()

@router.post("/api/settings/global")
async def save_global_settings(data: dict):
    conn = get_db()
    cur = conn.cursor()
    try:
        value = json.dumps(data)
        cur.execute("""
            INSERT INTO global_var (`key`, `value`) 
            VALUES ('global_settings', %s)
            ON DUPLICATE KEY UPDATE `value` = VALUES(`value`)
        """, (value,))
        conn.commit()
        return {"success": True}
    finally:
        cur.close()
        conn.close()
