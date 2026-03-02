"""
WebSocket Agent Router for CentralPrompt
"""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from typing import Dict, Set
import json
import asyncio

router = APIRouter()

# Store active connections: {group_id: Set[WebSocket]}
active_connections: Dict[int, Set[WebSocket]] = {}

@router.websocket("/ws/agent/{group_id}")
async def websocket_agent(websocket: WebSocket, group_id: int, token: str = Query(...)):
    """
    WebSocket endpoint for CentralPrompt
    - Clients connect with group_id and token
    - Receives prompts from users
    - Broadcasts messages to all clients in the same group
    """
    # Verify token
    from routers.auth import _verify_token_from_db
    auth_result = _verify_token_from_db(token)
    
    if not auth_result or not auth_result.get("valid"):
        # Fallback: super token
        import json as _json, os
        for path in ["/home/w3c_offical/global.json", os.path.expanduser("~/global.json")]:
            try:
                with open(path) as f:
                    if _json.load(f).get("api_token") == token:
                        auth_result = {"valid": True, "perms": ["api_full", "ttyd_read", "ttyd_write", "prompt", "pane_manage", "app_manage", "agent_manage", "desktop_manage", "vnc_read", "vnc_manage", "voice_to_text"], "group_id": None}
                        break
            except Exception:
                pass
    
    if not auth_result or not auth_result.get("valid"):
        await websocket.close(code=1008, reason="Invalid token")
        return
    
    # Check if token has prompt permission (for sending) or just read (for receiving)
    perms = auth_result.get("perms", [])
    
    # Check group_id permission
    token_group_id = auth_result.get("group_id")
    if token_group_id is not None and token_group_id != group_id:
        await websocket.close(code=1008, reason="Access denied to this group")
        return
    
    await websocket.accept()
    
    # Add to active connections
    if group_id not in active_connections:
        active_connections[group_id] = set()
    active_connections[group_id].add(websocket)
    
    try:
        # Send welcome message
        await websocket.send_json({
            "type": "connected",
            "group_id": group_id,
            "permissions": perms
        })
        
        while True:
            # Receive message from client
            data = await websocket.receive_text()
            message = json.loads(data)
            
            # Check if user has prompt permission to send
            if message.get("type") == "prompt":
                if "prompt" not in perms:
                    await websocket.send_json({
                        "type": "error",
                        "content": "You don't have permission to send prompts"
                    })
                    continue
                
                # Call AI and stream response
                content = message.get('content', '')
                try:
                    from services.cf_ai import ask_text
                    reply = await ask_text(content)
                    await websocket.send_json({
                        "type": "message",
                        "role": "assistant",
                        "content": reply or "（AI 无响应）"
                    })
                except Exception as ai_err:
                    await websocket.send_json({
                        "type": "message",
                        "role": "assistant",
                        "content": f"AI error: {ai_err}"
                    })
                
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"[WebSocket] Error: {e}")
    finally:
        # Remove from active connections
        if group_id in active_connections:
            active_connections[group_id].discard(websocket)
            if not active_connections[group_id]:
                del active_connections[group_id]

async def broadcast_to_group(group_id: int, message: dict):
    """Broadcast message to all connections in a group"""
    if group_id not in active_connections:
        return
    
    disconnected = set()
    for connection in active_connections[group_id]:
        try:
            await connection.send_json(message)
        except:
            disconnected.add(connection)
    
    # Clean up disconnected
    for conn in disconnected:
        active_connections[group_id].discard(conn)
