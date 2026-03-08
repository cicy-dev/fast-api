#!/usr/bin/env python3
"""
Group Management API
prefix: /api/groups

统一窗口模型: group_windows 表
win_type: agent_ttyd | app_frame
"""

import os
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from typing import List, Optional
import yaml
from db_pool import get_db

router = APIRouter(prefix="/api/groups", tags=["groups"])


def _check_group_permission(request: Request, group_id: int):
    from routers.auth import _verify_token_from_db
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.replace("Bearer ", "").strip() if auth_header.startswith("Bearer ") else None
    if token:
        token_info = _verify_token_from_db(token)
        if token_info and token_info.get("valid"):
            perms = token_info.get("perms", [])
            if "api_full" in perms:
                return
            token_group_id = token_info.get("group_id")
            if token_group_id is not None and token_group_id != group_id:
                raise HTTPException(status_code=403, detail="Access denied: group_id mismatch")


def format_response(data, request: Request = None):
    if request and "application/yaml" in request.headers.get("accept", "").lower():
        return PlainTextResponse(
            yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False),
            media_type="application/yaml",
        )
    return data


# --- Pydantic models ---

class GroupCreate(BaseModel):
    name: str
    description: Optional[str] = ""

class GroupPatch(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None

class LayoutPatch(BaseModel):
    pos_x: Optional[float] = None
    pos_y: Optional[float] = None
    width: Optional[float] = None
    height: Optional[float] = None
    z_index: Optional[int] = None

class WindowLayoutItem(BaseModel):
    win_id: str
    pos_x: float
    pos_y: float
    width: float
    height: float
    z_index: int = 1

class BatchLayoutPatch(BaseModel):
    panes: List[WindowLayoutItem]

class AddWindowBody(BaseModel):
    win_id: str
    win_type: str = "agent_ttyd"
    ref_id: Optional[str] = None


# --- Group CRUD ---

@router.get("")
async def list_groups(request: Request):
    from routers.auth import _verify_token_from_db
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.replace("Bearer ", "").strip() if auth_header.startswith("Bearer ") else None
    token_group_id = None
    is_superadmin = False
    if token:
        token_info = _verify_token_from_db(token)
        if token_info and token_info.get("valid"):
            token_group_id = token_info.get("group_id")
            is_superadmin = "api_full" in token_info.get("perms", [])

    conn = get_db()
    try:
        with conn.cursor() as c:
            if token_group_id is not None and not is_superadmin:
                c.execute("SELECT id, name, description, created_at, updated_at FROM ttyd_groups WHERE id=%s", (token_group_id,))
            else:
                c.execute("SELECT id, name, description, created_at, updated_at FROM ttyd_groups ORDER BY id")
            groups = c.fetchall()
            for g in groups:
                c.execute("SELECT win_id FROM group_windows WHERE group_id=%s", (g["id"],))
                wins = c.fetchall()
                g["pane_ids"] = [r["win_id"] for r in wins]
                g["pane_count"] = len(wins)
                if g.get("created_at"): g["created_at"] = g["created_at"].isoformat()
                if g.get("updated_at"): g["updated_at"] = g["updated_at"].isoformat()
            return format_response({"groups": groups}, request)
    finally:
        conn.close()


@router.post("")
async def create_group(body: GroupCreate, request: Request):
    conn = get_db()
    try:
        with conn.cursor() as c:
            c.execute("INSERT INTO ttyd_groups (name, description) VALUES (%s, %s)", (body.name, body.description or ""))
            conn.commit()
            group_id = c.lastrowid
            c.execute("SELECT id, name, description, created_at, updated_at FROM ttyd_groups WHERE id=%s", (group_id,))
            row = c.fetchone()
            if row.get("created_at"): row["created_at"] = row["created_at"].isoformat()
            if row.get("updated_at"): row["updated_at"] = row["updated_at"].isoformat()
            row["pane_ids"] = []
            row["pane_count"] = 0
            return format_response(row, request)
    finally:
        conn.close()


@router.get("/{group_id}")
async def get_group(group_id: int, request: Request):
    """获取 group 详情，返回统一的 windows 列表，同时保持 panes/apps 兼容字段"""
    _check_group_permission(request, group_id)
    conn = get_db()
    try:
        with conn.cursor() as c:
            c.execute("SELECT id, name, description, created_at, updated_at FROM ttyd_groups WHERE id=%s", (group_id,))
            group = c.fetchone()
            if not group:
                raise HTTPException(status_code=404, detail="Group not found")
            if group.get("created_at"): group["created_at"] = group["created_at"].isoformat()
            if group.get("updated_at"): group["updated_at"] = group["updated_at"].isoformat()

            # 统一查询所有窗口
            c.execute(
                "SELECT id, win_id, win_type, ref_id, pos_x, pos_y, width, height, z_index FROM group_windows WHERE group_id=%s ORDER BY z_index",
                (group_id,),
            )
            windows = c.fetchall()
            group["windows"] = windows

            # 兼容旧前端: panes 和 apps
            group["panes"] = [
                {"id": w["id"], "pane_id": w["win_id"], "pos_x": w["pos_x"], "pos_y": w["pos_y"],
                 "width": w["width"], "height": w["height"], "z_index": w["z_index"]}
                for w in windows if w["win_type"] == "agent_ttyd"
            ]
            # app 需要 join desktop_apps 获取 name/url/icon
            app_wins = [w for w in windows if w["win_type"] == "app_frame"]
            apps = []
            if app_wins:
                app_ids = [w["ref_id"] for w in app_wins if w["ref_id"]]
                if app_ids:
                    placeholders = ",".join(["%s"] * len(app_ids))
                    c.execute(f"SELECT id, name, url, icon FROM desktop_apps WHERE id IN ({placeholders})", app_ids)
                    app_map = {str(a["id"]): a for a in c.fetchall()}
                    for w in app_wins:
                        a = app_map.get(w["ref_id"])
                        if a:
                            apps.append({**a, "pos_x": w["pos_x"], "pos_y": w["pos_y"],
                                         "width": w["width"], "height": w["height"], "z_index": w["z_index"]})
            group["apps"] = apps

            return format_response(group, request)
    finally:
        conn.close()


@router.patch("/{group_id}")
async def update_group(group_id: int, body: GroupPatch, request: Request):
    _check_group_permission(request, group_id)
    updates = {}
    if body.name is not None: updates["name"] = body.name
    if body.description is not None: updates["description"] = body.description
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    conn = get_db()
    try:
        with conn.cursor() as c:
            set_clause = ", ".join(f"{k}=%s" for k in updates)
            c.execute(f"UPDATE ttyd_groups SET {set_clause} WHERE id=%s", list(updates.values()) + [group_id])
            if c.rowcount == 0:
                raise HTTPException(status_code=404, detail="Group not found")
            conn.commit()
            return format_response({"success": True, "group_id": group_id, "updated": updates}, request)
    finally:
        conn.close()


@router.delete("/{group_id}")
async def delete_group(group_id: int, request: Request):
    _check_group_permission(request, group_id)
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


# --- 统一窗口 API ---

@router.post("/{group_id}/windows")
async def add_window(group_id: int, body: AddWindowBody, request: Request):
    """添加窗口到 group"""
    _check_group_permission(request, group_id)
    conn = get_db()
    try:
        with conn.cursor() as c:
            try:
                c.execute(
                    "INSERT INTO group_windows (group_id, win_id, win_type, ref_id) VALUES (%s, %s, %s, %s)",
                    (group_id, body.win_id, body.win_type, body.ref_id or body.win_id),
                )
                conn.commit()
            except pymysql.err.IntegrityError:
                pass
            return format_response({"success": True, "group_id": group_id, "win_id": body.win_id}, request)
    finally:
        conn.close()


@router.delete("/{group_id}/windows/{win_id:path}")
async def remove_window(group_id: int, win_id: str, request: Request):
    """从 group 移除窗口（统一接口）"""
    _check_group_permission(request, group_id)
    conn = get_db()
    try:
        with conn.cursor() as c:
            c.execute("DELETE FROM group_windows WHERE group_id=%s AND win_id=%s", (group_id, win_id))
            conn.commit()
            return format_response({"success": True, "group_id": group_id, "win_id": win_id}, request)
    finally:
        conn.close()


@router.patch("/{group_id}/windows/{win_id:path}/layout")
async def update_window_layout(group_id: int, win_id: str, body: LayoutPatch, request: Request):
    _check_group_permission(request, group_id)
    updates = {}
    if body.pos_x is not None: updates["pos_x"] = body.pos_x
    if body.pos_y is not None: updates["pos_y"] = body.pos_y
    if body.width is not None: updates["width"] = body.width
    if body.height is not None: updates["height"] = body.height
    if body.z_index is not None: updates["z_index"] = body.z_index
    if not updates:
        raise HTTPException(status_code=400, detail="No layout fields to update")
    conn = get_db()
    try:
        with conn.cursor() as c:
            set_clause = ", ".join(f"{k}=%s" for k in updates)
            c.execute(f"UPDATE group_windows SET {set_clause} WHERE group_id=%s AND win_id=%s",
                      list(updates.values()) + [group_id, win_id])
            conn.commit()
            return format_response({"success": True, "group_id": group_id, "win_id": win_id}, request)
    finally:
        conn.close()


@router.patch("/{group_id}/layout")
async def batch_update_layout(group_id: int, body: BatchLayoutPatch, request: Request):
    _check_group_permission(request, group_id)
    conn = get_db()
    try:
        with conn.cursor() as c:
            for p in body.panes:
                c.execute(
                    "UPDATE group_windows SET pos_x=%s, pos_y=%s, width=%s, height=%s, z_index=%s WHERE group_id=%s AND win_id=%s",
                    (p.pos_x, p.pos_y, p.width, p.height, p.z_index, group_id, p.win_id),
                )
            conn.commit()
            return format_response({"success": True, "group_id": group_id, "updated": len(body.panes)}, request)
    finally:
        conn.close()


# --- 兼容旧 API（转发到统一窗口逻辑）---

@router.post("/{group_id}/panes/{pane_id:path}")
async def add_pane_compat(group_id: int, pane_id: str, request: Request):
    """兼容旧 API: 添加 pane"""
    _check_group_permission(request, group_id)
    conn = get_db()
    try:
        with conn.cursor() as c:
            try:
                c.execute(
                    "INSERT INTO group_windows (group_id, win_id, win_type, ref_id) VALUES (%s, %s, 'agent_ttyd', %s)",
                    (group_id, pane_id, pane_id),
                )
                conn.commit()
            except pymysql.err.IntegrityError:
                pass
            return format_response({"success": True, "group_id": group_id, "pane_id": pane_id}, request)
    finally:
        conn.close()


@router.delete("/{group_id}/panes/{pane_id:path}")
async def remove_pane_compat(group_id: int, pane_id: str, request: Request):
    """兼容旧 API: 移除 pane"""
    _check_group_permission(request, group_id)
    conn = get_db()
    try:
        with conn.cursor() as c:
            c.execute("DELETE FROM group_windows WHERE group_id=%s AND win_id=%s", (group_id, pane_id))
            conn.commit()
            return format_response({"success": True, "group_id": group_id, "pane_id": pane_id}, request)
    finally:
        conn.close()


@router.patch("/{group_id}/panes/{pane_id:path}/layout")
async def update_pane_layout_compat(group_id: int, pane_id: str, body: LayoutPatch, request: Request):
    """兼容旧 API: 更新 pane layout"""
    _check_group_permission(request, group_id)
    updates = {}
    if body.pos_x is not None: updates["pos_x"] = body.pos_x
    if body.pos_y is not None: updates["pos_y"] = body.pos_y
    if body.width is not None: updates["width"] = body.width
    if body.height is not None: updates["height"] = body.height
    if body.z_index is not None: updates["z_index"] = body.z_index
    if not updates:
        raise HTTPException(status_code=400, detail="No layout fields to update")
    conn = get_db()
    try:
        with conn.cursor() as c:
            set_clause = ", ".join(f"{k}=%s" for k in updates)
            c.execute(f"UPDATE group_windows SET {set_clause} WHERE group_id=%s AND win_id=%s",
                      list(updates.values()) + [group_id, pane_id])
            conn.commit()
            return format_response({"success": True, "group_id": group_id, "pane_id": pane_id}, request)
    finally:
        conn.close()


@router.post("/{group_id}/apps/{app_id}")
async def add_app_compat(group_id: int, app_id: int, request: Request):
    """兼容旧 API: 添加 app"""
    _check_group_permission(request, group_id)
    win_id = f"app-{app_id}"
    conn = get_db()
    try:
        with conn.cursor() as c:
            try:
                c.execute(
                    "INSERT INTO group_windows (group_id, win_id, win_type, ref_id) VALUES (%s, %s, 'app_frame', %s)",
                    (group_id, win_id, str(app_id)),
                )
                conn.commit()
            except pymysql.err.IntegrityError:
                pass
            return format_response({"success": True, "group_id": group_id, "app_id": app_id}, request)
    finally:
        conn.close()


@router.delete("/{group_id}/apps/{app_id}")
async def remove_app_compat(group_id: int, app_id: int, request: Request):
    """兼容旧 API: 移除 app"""
    _check_group_permission(request, group_id)
    win_id = f"app-{app_id}"
    conn = get_db()
    try:
        with conn.cursor() as c:
            c.execute("DELETE FROM group_windows WHERE group_id=%s AND win_id=%s", (group_id, win_id))
            conn.commit()
            return format_response({"success": True, "group_id": group_id, "app_id": app_id}, request)
    finally:
        conn.close()
