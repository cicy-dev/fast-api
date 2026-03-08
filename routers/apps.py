"""
Desktop Apps CRUD API
prefix: /api/apps
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from db_pool import get_db

router = APIRouter(prefix="/api/apps", tags=["apps"])


class AppCreate(BaseModel):
    name: str
    url: str
    icon: Optional[str] = ""


class AppUpdate(BaseModel):
    name: Optional[str] = None
    url: Optional[str] = None
    icon: Optional[str] = None


@router.get("")
async def list_apps():
    conn = get_db()
    try:
        with conn.cursor() as c:
            c.execute("SELECT id, name, url, icon, created_at, updated_at FROM desktop_apps ORDER BY id")
            apps = c.fetchall()
            for a in apps:
                if a.get("created_at"): a["created_at"] = a["created_at"].isoformat()
                if a.get("updated_at"): a["updated_at"] = a["updated_at"].isoformat()
            return {"apps": apps}
    finally:
        conn.close()


@router.post("")
async def create_app(body: AppCreate):
    conn = get_db()
    try:
        with conn.cursor() as c:
            c.execute("INSERT INTO desktop_apps (name, url, icon) VALUES (%s, %s, %s)",
                      (body.name, body.url, body.icon or ""))
            conn.commit()
            return {"id": c.lastrowid, "name": body.name, "url": body.url, "icon": body.icon or ""}
    finally:
        conn.close()


@router.patch("/{app_id}")
async def update_app(app_id: int, body: AppUpdate):
    updates = {k: v for k, v in body.dict().items() if v is not None}
    if not updates:
        raise HTTPException(400, "No fields to update")
    conn = get_db()
    try:
        with conn.cursor() as c:
            set_clause = ", ".join(f"{k}=%s" for k in updates)
            c.execute(f"UPDATE desktop_apps SET {set_clause} WHERE id=%s",
                      list(updates.values()) + [app_id])
            if c.rowcount == 0:
                raise HTTPException(404, "App not found")
            conn.commit()
            return {"success": True, "id": app_id}
    finally:
        conn.close()


@router.delete("/{app_id}")
async def delete_app(app_id: int):
    conn = get_db()
    try:
        with conn.cursor() as c:
            c.execute("DELETE FROM desktop_apps WHERE id=%s", (app_id,))
            if c.rowcount == 0:
                raise HTTPException(404, "App not found")
            conn.commit()
            return {"success": True, "id": app_id}
    finally:
        conn.close()
