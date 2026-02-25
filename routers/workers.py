"""
Worker 间通信 API
"""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/api/workers", tags=["workers"])

class WorkerMessage(BaseModel):
    from_worker: str
    to_worker: str
    message: str
    request_reply: Optional[bool] = False

class WorkerReply(BaseModel):
    from_worker: str
    to_worker: str
    reply: str
    ref_message: Optional[str] = None

@router.post("/message")
async def send_message(msg: WorkerMessage, request: Request):
    """Send message from one worker to another
    
    Uses tmux send API to deliver message to target worker's pane.
    Format: [from_worker → to_worker] message
    """
    # Format message
    prefix = "🔔 " if msg.request_reply else "💬 "
    formatted = f"{prefix}[{msg.from_worker} → {msg.to_worker}] {msg.message}"
    
    # Use internal send_short
    from routers.tmux.router import send_short
    
    result = await send_short(request, {
        "win_id": msg.to_worker,
        "text": formatted
    })
    
    return {
        "success": result.get("success", False),
        "from": msg.from_worker,
        "to": msg.to_worker,
        "delivered": result.get("success", False)
    }

@router.post("/reply")
async def send_reply(reply: WorkerReply, request: Request):
    """Send reply to a worker message"""
    # Format reply
    formatted = f"✅ [{reply.from_worker} → {reply.to_worker}] {reply.reply}"
    
    # Use internal send_short
    from routers.tmux.router import send_short
    
    result = await send_short(request, {
        "win_id": reply.to_worker,
        "text": formatted
    })
    
    return {
        "success": result.get("success", False),
        "from": reply.from_worker,
        "to": reply.to_worker,
        "delivered": result.get("success", False)
    }

@router.post("/broadcast")
async def broadcast_message(msg: dict, request: Request):
    """Broadcast message to multiple workers"""
    from_worker = msg.get("from_worker")
    to_workers = msg.get("to_workers", [])
    message = msg.get("message")
    
    if not all([from_worker, to_workers, message]):
        raise HTTPException(400, "Missing required fields")
    
    from routers.tmux.router import send_short
    
    results = []
    for to_worker in to_workers:
        formatted = f"📢 [{from_worker} → ALL] {message}"
        try:
            result = await send_short(request, {
                "win_id": to_worker,
                "text": formatted
            })
            results.append({
                "worker": to_worker,
                "success": result.get("success", False)
            })
        except:
            results.append({
                "worker": to_worker,
                "success": False
            })
    
    return {
        "success": True,
        "from": from_worker,
        "results": results
    }
