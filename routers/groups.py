#!/usr/bin/env python3
"""
Group Management API
prefix: /api/groups
"""

import os
import pymysql
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from typing import List, Optional
import yaml

router = APIRouter(prefix="/api/groups", tags=["groups"])

MYSQL_HOST = os.getenv("MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "tts_bot")


def get_db():
    return pymysql.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DATABASE,
        cursorclass=pymysql.cursors.DictCursor
    )


def format_response(data, request: Request = None):
    if request and "application/yaml" in request.headers.get("accept", "").lower():
        yaml_str = yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)
        return PlainTextResponse(yaml_str, media_type="application/yaml")
    return data


# --- Pydantic models ---

class GroupCreate(BaseModel):
    name: str
    description: Optional[str] = ""


class GroupPatch(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class PaneIdList(BaseModel):
    pane_ids: List[str]


class LayoutPatch(BaseModel):
    pos_x: Optional[float] = None
    pos_y: Optional[float] = None
    width: Optional[float] = None
    height: Optional[float] = None
    z_index: Optional[int] = None


class PaneLayoutItem(BaseModel):
    pane_id: str
    pos_x: float
    pos_y: float
    width: float
    height: float
    z_index: int = 1


class BatchLayoutPatch(BaseModel):
    panes: List[PaneLayoutItem]


class GroupStatePatch(BaseModel):
    activePane: Optional[str] = None
    layoutMode: Optional[str] = None


# --- Routes ---

@router.get("")
async def list_groups(request: Request):
    """List all groups with pane_ids and pane_count. If token has group_id restriction, only return that group."""
    # Get token from Authorization header
    from routers.auth import _verify_token_from_db
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.replace("Bearer ", "").strip() if auth_header.startswith("Bearer ") else None
    
    token_group_id = None
    if token:
        token_info = _verify_token_from_db(token)
        if token_info and token_info.get("valid"):
            token_group_id = token_info.get("group_id")
    
    conn = get_db()
    try:
        with conn.cursor() as c:
            if token_group_id is not None:
                # Token has group_id restriction, only return that group
                c.execute("SELECT id, name, description, created_at, updated_at FROM ttyd_groups WHERE id=%s", (token_group_id,))
            else:
                # No restriction, return all groups
                c.execute("SELECT id, name, description, created_at, updated_at FROM ttyd_groups ORDER BY id")
            
            groups = c.fetchall()
            for g in groups:
                c.execute("SELECT pane_id FROM ttyd_group_panes WHERE group_id=%s", (g["id"],))
                pane_rows = c.fetchall()
                g["pane_ids"] = [r["pane_id"] for r in pane_rows]
                g["pane_count"] = len(pane_rows)
                # Convert datetime to string
                if g.get("created_at"):
                    g["created_at"] = g["created_at"].isoformat()
                if g.get("updated_at"):
                    g["updated_at"] = g["updated_at"].isoformat()
            return format_response({"groups": groups}, request)
    finally:
        conn.close()


@router.post("")
async def create_group(body: GroupCreate, request: Request):
    """Create a new group."""
    conn = get_db()
    try:
        with conn.cursor() as c:
            c.execute(
                "INSERT INTO ttyd_groups (name, description) VALUES (%s, %s)",
                (body.name, body.description or "")
            )
            conn.commit()
            group_id = c.lastrowid
            c.execute("SELECT id, name, description, created_at, updated_at FROM ttyd_groups WHERE id=%s", (group_id,))
            row = c.fetchone()
            if row.get("created_at"):
                row["created_at"] = row["created_at"].isoformat()
            if row.get("updated_at"):
                row["updated_at"] = row["updated_at"].isoformat()
            row["pane_ids"] = []
            row["pane_count"] = 0
            return format_response(row, request)
    finally:
        conn.close()


@router.get("/{group_id}")
async def get_group(group_id: int, request: Request):
    """Get a single group with full pane layout details. Returns 403 if token's group_id doesn't match."""
    # Get token from Authorization header
    from routers.auth import _verify_token_from_db
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.replace("Bearer ", "").strip() if auth_header.startswith("Bearer ") else None
    
    token_group_id = None
    if token:
        token_info = _verify_token_from_db(token)
        if token_info and token_info.get("valid"):
            token_group_id = token_info.get("group_id")
    
    # Check permission: if token has group_id restriction, must match
    if token_group_id is not None and token_group_id != group_id:
        raise HTTPException(status_code=403, detail="Access denied: group_id mismatch")
    
    conn = get_db()
    try:
        with conn.cursor() as c:
            c.execute("SELECT id, name, description, created_at, updated_at FROM ttyd_groups WHERE id=%s", (group_id,))
            group = c.fetchone()
            if not group:
                raise HTTPException(status_code=404, detail="Group not found")
            if group.get("created_at"):
                group["created_at"] = group["created_at"].isoformat()
            if group.get("updated_at"):
                group["updated_at"] = group["updated_at"].isoformat()
            c.execute(
                "SELECT id, pane_id, pos_x, pos_y, width, height, z_index FROM ttyd_group_panes WHERE group_id=%s ORDER BY z_index",
                (group_id,)
            )
            group["panes"] = c.fetchall()
            return format_response(group, request)
    finally:
        conn.close()


@router.patch("/{group_id}")
async def update_group(group_id: int, body: GroupPatch, request: Request):
    """Rename or update description."""
    updates = {}
    if body.name is not None:
        updates["name"] = body.name
    if body.description is not None:
        updates["description"] = body.description
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    conn = get_db()
    try:
        with conn.cursor() as c:
            set_clause = ", ".join(f"{k}=%s" for k in updates)
            c.execute(
                f"UPDATE ttyd_groups SET {set_clause} WHERE id=%s",
                list(updates.values()) + [group_id]
            )
            if c.rowcount == 0:
                raise HTTPException(status_code=404, detail="Group not found")
            conn.commit()
            return format_response({"success": True, "group_id": group_id, "updated": updates}, request)
    finally:
        conn.close()


@router.delete("/{group_id}")
async def delete_group(group_id: int, request: Request):
    """Delete a group (CASCADE deletes pane associations)."""
    conn = get_db()
    try:
        with conn.cursor() as c:
            c.execute("DELETE FROM ttyd_groups WHERE id=%s", (group_id,))
            if c.rowcount == 0:
                raise HTTPException(status_code=404, detail="Group not found")
            conn.commit()
            return format_response({"success": True, "group_id": group_id}, request)
    finally:
        conn.close()


@router.put("/{group_id}/panes")
async def replace_panes(group_id: int, body: PaneIdList, request: Request):
    """Full replacement of panes in a group."""
    conn = get_db()
    try:
        with conn.cursor() as c:
            c.execute("SELECT id FROM ttyd_groups WHERE id=%s", (group_id,))
            if not c.fetchone():
                raise HTTPException(status_code=404, detail="Group not found")
            c.execute("DELETE FROM ttyd_group_panes WHERE group_id=%s", (group_id,))
            for pane_id in body.pane_ids:
                c.execute(
                    "INSERT INTO ttyd_group_panes (group_id, pane_id) VALUES (%s, %s)",
                    (group_id, pane_id)
                )
            conn.commit()
            return format_response({"success": True, "group_id": group_id, "pane_count": len(body.pane_ids)}, request)
    finally:
        conn.close()


@router.post("/{group_id}/panes/{pane_id:path}")
async def add_pane(group_id: int, pane_id: str, request: Request):
    """Add a single pane to a group."""
    conn = get_db()
    try:
        with conn.cursor() as c:
            c.execute("SELECT id FROM ttyd_groups WHERE id=%s", (group_id,))
            if not c.fetchone():
                raise HTTPException(status_code=404, detail="Group not found")
            try:
                c.execute(
                    "INSERT INTO ttyd_group_panes (group_id, pane_id) VALUES (%s, %s)",
                    (group_id, pane_id)
                )
                conn.commit()
            except pymysql.err.IntegrityError:
                pass  # Already exists - idempotent
            return format_response({"success": True, "group_id": group_id, "pane_id": pane_id}, request)
    finally:
        conn.close()


@router.delete("/{group_id}/panes/{pane_id:path}")
async def remove_pane(group_id: int, pane_id: str, request: Request):
    """Remove a single pane from a group."""
    conn = get_db()
    try:
        with conn.cursor() as c:
            c.execute(
                "DELETE FROM ttyd_group_panes WHERE group_id=%s AND pane_id=%s",
                (group_id, pane_id)
            )
            conn.commit()
            return format_response({"success": True, "group_id": group_id, "pane_id": pane_id}, request)
    finally:
        conn.close()


@router.patch("/{group_id}/panes/{pane_id:path}/layout")
async def update_pane_layout(group_id: int, pane_id: str, body: LayoutPatch, request: Request):
    """Save a single pane's position/size."""
    updates = {}
    if body.pos_x is not None:
        updates["pos_x"] = body.pos_x
    if body.pos_y is not None:
        updates["pos_y"] = body.pos_y
    if body.width is not None:
        updates["width"] = body.width
    if body.height is not None:
        updates["height"] = body.height
    if body.z_index is not None:
        updates["z_index"] = body.z_index
    if not updates:
        raise HTTPException(status_code=400, detail="No layout fields to update")
    conn = get_db()
    try:
        with conn.cursor() as c:
            set_clause = ", ".join(f"{k}=%s" for k in updates)
            c.execute(
                f"UPDATE ttyd_group_panes SET {set_clause} WHERE group_id=%s AND pane_id=%s",
                list(updates.values()) + [group_id, pane_id]
            )
            conn.commit()
            return format_response({"success": True, "group_id": group_id, "pane_id": pane_id}, request)
    finally:
        conn.close()


@router.patch("/{group_id}/layout")
async def batch_update_layout(group_id: int, body: BatchLayoutPatch, request: Request):
    """Batch save all pane layouts (called after Auto-grid)."""
    conn = get_db()
    try:
        with conn.cursor() as c:
            for p in body.panes:
                c.execute(
                    """UPDATE ttyd_group_panes
                       SET pos_x=%s, pos_y=%s, width=%s, height=%s, z_index=%s
                       WHERE group_id=%s AND pane_id=%s""",
                    (p.pos_x, p.pos_y, p.width, p.height, p.z_index, group_id, p.pane_id)
                )
            conn.commit()
            return format_response({"success": True, "group_id": group_id, "updated": len(body.panes)}, request)
    finally:
        conn.close()


@router.patch("/{group_id}/state")
async def update_group_state(group_id: int, body: GroupStatePatch, request: Request):
    """Save group state (activePane, layoutMode) - currently stored in localStorage on client."""
    # Note: This endpoint accepts the state but doesn't persist to DB yet.
    # State is primarily managed in localStorage on the client side.
    # In a future enhancement, we could add a ttyd_group_state table.
    return format_response({
        "success": True,
        "group_id": group_id,
        "message": "State cached on client (localStorage)"
    }, request)
