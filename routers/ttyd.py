#!/usr/bin/env python3
"""
Ttyd Service - 按需启动 ttyd
"""

import os
import secrets
import subprocess
import pymysql
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse
import yaml

router = APIRouter(prefix="/api/ttyd", tags=["ttyd"])

MYSQL_HOST = os.getenv("MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "tts_bot")

TTYD_PORT_RANGE_DEV = os.getenv("TTYD_PORT_RANGE_DEV", "16100-16200")
TTYD_PORT_RANGE_PROD = os.getenv("TTYD_PORT_RANGE_PROD", "15100-15300")

TMUX_SOCKET = os.getenv("TMUX_SOCKET", "/home/w3c_offical/.tmux/default")
TTYD_BASE_URL = os.getenv("TTYD_BASE_URL", "")

def get_db():
    return pymysql.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DATABASE,
        cursorclass=pymysql.cursors.DictCursor
    )

def format_response(data: dict, request: Request):
    accept = request.headers.get("accept", "")
    if "application/json" in accept.lower():
        return data
    yaml_str = yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)
    return PlainTextResponse(yaml_str, media_type="application/yaml")

def run_tmux(cmd):
    result = subprocess.run(["tmux", "-S", TMUX_SOCKET] + cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise HTTPException(status_code=400, detail=result.stderr.strip())
    return result.stdout.strip()

def is_port_listening(port: int) -> bool:
    result = subprocess.run(["ss", "-tln"], capture_output=True, text=True)
    return f":{port}" in result.stdout

def parse_port_range(port_range: str):
    start, end = port_range.split("-")
    return range(int(start), int(end) + 1)

@router.post("/start/{pane_id:path}")
async def start_ttyd(pane_id: str, request: Request):
    """按需启动 ttyd，如果已运行则返回现有配置"""
    conn = get_db()
    try:
        with conn.cursor() as c:
            c.execute("SELECT * FROM ttyd_config WHERE pane_id=%s", (pane_id,))
            row = c.fetchone()
            
            if not row:
                raise HTTPException(status_code=404, detail=f"pane_id {pane_id} not found")
            
            port = row["ttyd_port"]
            token = row["ttyd_token"]
            title = row.get("title", pane_id)
            workspace = row.get("workspace")
            init_script = row.get("init_script")
            tg_token = row.get("tg_token")
            tg_chat_id = row.get("tg_chat_id")
            tg_enable = row.get("tg_enable", False)
            
            if is_port_listening(port):
                return format_response({
                    "pane_id": pane_id,
                    "title": title,
                    "port": port,
                    "token": token,
                    "url": row.get("url"),
                    "workspace": workspace,
                    "init_script": init_script,
                    "tg_token": tg_token,
                    "tg_chat_id": tg_chat_id,
                    "tg_enable": tg_enable,
                    "status": "running"
                }, request)
            
            run_tmux(["send-keys", "-t", pane_id, f"ttyd -W -p {port} -c user:{token} tmux attach -t {pane_id} &", "Enter"])
            
            return format_response({
                "pane_id": pane_id,
                "title": title,
                "port": port,
                "token": token,
                "url": row.get("url"),
                "workspace": workspace,
                "init_script": init_script,
                "tg_token": tg_token,
                "tg_chat_id": tg_chat_id,
                "tg_enable": tg_enable,
                "status": "started"
            }, request)
    finally:
        conn.close()

@router.get("/status/{pane_id:path}")
async def get_status(pane_id: str, request: Request):
    """检查 ttyd 是否已启动"""
    conn = get_db()
    try:
        with conn.cursor() as c:
            c.execute("SELECT ttyd_port FROM ttyd_config WHERE pane_id=%s", (pane_id,))
            row = c.fetchone()
            
            if not row:
                raise HTTPException(status_code=404, detail="pane_id not found")
            
            port = row["ttyd_port"]
            listening = is_port_listening(port)
            
            return format_response({
                "pane_id": pane_id,
                "port": port,
                "ready": listening
            }, request)
    finally:
        conn.close()

@router.get("/by-name/{name}")
async def get_by_name(name: str, request: Request):
    conn = get_db()
    try:
        with conn.cursor() as c:
            c.execute("SELECT * FROM ttyd_config WHERE pane_id=%s", (name,))
            row = c.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="not found")
            return format_response({
                "pane_id": row["pane_id"],
                "port": row["ttyd_port"],
                "token": row["ttyd_token"],
                "url": row.get("url")
            }, request)
    finally:
        conn.close()

@router.get("/list")
async def list_configs(request: Request):
    conn = get_db()
    try:
        with conn.cursor() as c:
            c.execute("SELECT pane_id, title, ttyd_port, ttyd_token FROM ttyd_config ORDER BY ttyd_port")
            rows = c.fetchall()
            return format_response({"configs": rows}, request)
    finally:
        conn.close()

@router.delete("/config/{pane_id:path}")
async def delete_config(pane_id: str, request: Request):
    conn = get_db()
    try:
        with conn.cursor() as c:
            c.execute("DELETE FROM ttyd_config WHERE pane_id=%s", (pane_id,))
            conn.commit()
            return format_response({"success": True, "pane_id": pane_id}, request)
    finally:
        conn.close()
