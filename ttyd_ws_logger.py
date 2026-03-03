#!/usr/bin/env python3
import asyncio
import websockets
import sys
import base64
import json
from datetime import datetime

async def log_ttyd_output(port: int, token: str, pane_id: str, log_file: str):
    auth = base64.b64encode(f"user:{token}".encode()).decode()
    uri = f"ws://127.0.0.1:{port}/ws"
    
    with open(log_file, 'a') as f:
        f.write(f"\n=== Connecting to {uri} at {datetime.now().isoformat()} ===\n")
        f.flush()
    
    try:
        async with websockets.connect(
            uri,
            additional_headers={"Authorization": f"Basic {auth}"}
        ) as ws:
            # Send terminal size (ttyd protocol requirement)
            await ws.send(json.dumps({"AuthToken": token, "columns": 120, "rows": 30}))
            
            with open(log_file, 'a') as f:
                f.write(f"=== Connected successfully ===\n")
                f.flush()
                async for msg in ws:
                    if isinstance(msg, str):
                        f.write(msg)
                        f.flush()
                    elif isinstance(msg, bytes):
                        try:
                            # ttyd protocol: first byte is message type
                            # '0' (0x30) = terminal output
                            if len(msg) > 1 and msg[0] == ord('0'):
                                text = msg[1:].decode('utf-8', errors='replace')
                                f.write(text)
                                f.flush()
                        except Exception as e:
                            f.write(f"\n=== Decode error: {e} ===\n")
                            f.flush()
    except Exception as e:
        with open(log_file, 'a') as f:
            f.write(f"\n=== Connection error: {e} ===\n")
            f.flush()

if __name__ == "__main__":
    port = int(sys.argv[1])
    token = sys.argv[2]
    pane_id = sys.argv[3]
    log_file = sys.argv[4]
    asyncio.run(log_ttyd_output(port, token, pane_id, log_file))
