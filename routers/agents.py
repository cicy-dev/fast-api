from fastapi import APIRouter, Depends, HTTPException
from typing import List, Optional
from db_pool import get_db
from routers.auth import get_current_user

router = APIRouter(prefix="/api/agents", tags=["agents"])

@router.get("/pane/{pane_id}")
async def get_pane_agents(pane_id: str):
    """Get all agents bound to a specific pane"""
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, pane_id, agent_name as name, status FROM pane_agents WHERE pane_id = %s",
                (pane_id,)
            )
            agents = cur.fetchall()
            return agents
    finally:
        conn.close()

@router.post("/bind")
async def bind_agent(data: dict):
    """Bind an agent to a pane"""
    pane_id = data.get("pane_id")
    agent_name = data.get("agent_name")
    
    if not pane_id or not agent_name:
        raise HTTPException(status_code=400, detail="pane_id and agent_name required")
    
    conn = get_db()
    try:
        with conn.cursor() as cur:
            # Check if already bound
            cur.execute(
                "SELECT id FROM pane_agents WHERE pane_id = %s AND agent_name = %s",
                (pane_id, agent_name)
            )
            existing = cur.fetchone()
            if existing:
                raise HTTPException(status_code=400, detail="Agent already bound to this pane")
            
            # Insert binding
            cur.execute(
                "INSERT INTO pane_agents (pane_id, agent_name, status) VALUES (%s, %s, 'active')",
                (pane_id, agent_name)
            )
            conn.commit()
            return {"success": True, "id": cur.lastrowid}
    finally:
        conn.close()

@router.delete("/unbind/{agent_id}")
async def unbind_agent(agent_id: int):
    """Unbind an agent from a pane"""
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM pane_agents WHERE id = %s", (agent_id,))
            conn.commit()
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Agent binding not found")
            return {"success": True}
    finally:
        conn.close()
