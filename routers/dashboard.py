#!/usr/bin/env python3
"""
Dashboard API - requires api_full permission
prefix: /api/dashboard
"""

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


def get_db():
    from db_pool import get_db as _get_db
    return _get_db()


def _check_api_full_permission(request: Request) -> str:
    """Check if token has api_full permission. Returns token string. Raises 403 if denied."""
    from routers.auth import _verify_token_from_db
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.replace("Bearer ", "").strip() if auth_header.startswith("Bearer ") else None
    
    if not token:
        raise HTTPException(status_code=403, detail="No token provided")
    
    token_info = _verify_token_from_db(token)
    if not token_info or not token_info.get("valid"):
        raise HTTPException(status_code=403, detail="Invalid token")
    
    perms = token_info.get("perms", [])
    if "api_full" not in perms:
        raise HTTPException(status_code=403, detail="Requires api_full permission")
    
    return token


@router.get("")
async def get_dashboard(request: Request):
    """
    Get dashboard data: agents and apps.
    Requires api_full permission.
    
    Returns:
    {
        "agents": [{"pane_id": "w-20074:main.0", "title": "...", "ttyd_url": "https://...", "group_id": 1}],
        "apps": [{"id": 3, "name": "CodeServer", "url": "https://..."}]
    }
    """
    token = _check_api_full_permission(request)
    
    conn = get_db()
    try:
        with conn.cursor() as c:
            # Get agents from ttyd_config JOIN group_windows
            c.execute("""
                SELECT t.pane_id, t.title, gp.group_id
                FROM ttyd_config t
                LEFT JOIN group_windows gp ON t.pane_id = gp.win_id
                WHERE t.active = 1
                ORDER BY t.created_at DESC
            """)
            agent_rows = c.fetchall()
            
            agents = []
            for row in agent_rows:
                pane_id = row["pane_id"]
                # Strip :main.0 or similar suffix for URL
                pane_base = pane_id.split(":")[0] if ":" in pane_id else pane_id
                ttyd_url = f"https://ttyd-proxy.cicy.de5.net/ttyd/{pane_base}/?token={token}"
                
                agents.append({
                    "pane_id": pane_id,
                    "title": row.get("title") or pane_id,
                    "ttyd_url": ttyd_url,
                    "group_id": row.get("group_id")
                })
            
            # Get apps from desktop_apps table
            c.execute("""
                SELECT id, name, url, icon
                FROM desktop_apps
                ORDER BY id
            """)
            app_rows = c.fetchall()
            
            apps = []
            for row in app_rows:
                apps.append({
                    "id": row["id"],
                    "name": row["name"],
                    "url": row["url"],
                    "icon": row.get("icon")
                })
            
            return {
                "agents": agents,
                "apps": apps
            }
    finally:
        conn.close()
