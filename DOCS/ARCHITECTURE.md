# fast-api 架构文档

## 1. 项目定位

fast-api 是整个系统的核心后端服务，负责：
- tmux 会话/窗口/pane 的生命周期管理
- ttyd 进程的端口分配、启动、重启、销毁
- 所有 pane 配置的持久化（MySQL）
- 英文纠错、bot 列表、local services 注册等通用 API
- 作为 ttyd-proxy server 的上游数据源（`/api/ttyd/by-name/{id}`）

## 2. 整体架构

```
                        ┌─────────────────────────────┐
  外部访问              │  Cloudflare Tunnel           │
  g-fast-api.           │  g-fast-api.cicy.de5.net    │
  cicy.de5.net          │  → localhost:14444           │
                        └──────────────┬──────────────┘
                                       │
                        ┌──────────────▼──────────────┐
                        │         fast-api             │
                        │   Python 3.12 / FastAPI      │
                        │   uvicorn --reload           │
                        │   port: 14444                │
                        │   network_mode: host         │
                        │   privileged: true           │
                        └──┬──────────┬───────────────┘
                           │          │
              tmux socket  │          │  MySQL
              ~/.tmux/     │          │  127.0.0.1:3306
              default      │          │  db: tts_bot
                    ┌──────▼──┐  ┌────▼─────────────┐
                    │  tmux   │  │     MySQL         │
                    │  (host) │  │  ttyd_config      │
                    └────┬────┘  │  local_services   │
                         │       └──────────────────-┘
              send-keys  │
                    ┌────▼──────────────────────────┐
                    │  ttyd 进程（host 上运行）      │
                    │  nohup ttyd -W -p 151xx        │
                    │  -c user:{token}               │
                    │  tmux attach -t {pane_id}      │
                    └───────────────────────────────┘
```

## 3. 模块结构

```
fast-api/
├── main.py                    # FastAPI app 主入口 + 通用路由
├── requirements.txt           # Python 依赖
├── Dockerfile                 # 容器镜像定义
├── docker-compose.yml         # 服务配置
├── .env                       # 环境变量（不提交 Git）
├── .env.example               # 环境变量模板
├── routers/
│   ├── __init__.py
│   ├── ttyd.py                # ttyd 查询/状态 API（/api/ttyd/*）
│   └── tmux/
│       ├── __init__.py
│       ├── router.py          # tmux 管理 API（/api/tmux/*）
│       └── README.md          # API 使用说明
├── tests/
│   └── test_create_window.py  # 集成测试
└── DOCS/
    ├── ARCHITECTURE.md        # 本文档
    └── DEVELOPMENT.md         # 开发测试部署规范
```

## 4. API 路由总览

### 4.1 main.py（通用路由）

| 路径 | 方法 | 认证 | 说明 |
|------|------|------|------|
| `/health` | GET | 否 | 健康检查 |
| `/api/health` | GET | 否 | 带 source 字段的健康检查 |
| `/ping` | GET | 否 | ping，返回服务器时间 |
| `/api/auth/verify` | GET | 是 | 验证 token 有效性 |
| `/api/services` | GET | 是 | 列出 local_services |
| `/api/services/{port}` | GET/POST/DELETE | 是 | local service CRUD |
| `/api/tmux` | POST | 是 | 发送文本到 tmux pane（兼容旧接口） |
| `/api/bots` | GET | 是 | 通过 docker exec 获取 bot 列表 |
| `/api/tmux-list` | GET | 是 | tmux 会话树（镜像 ~/tools/tre） |
| `/api/correctEnglish` | POST | 是 | HuggingFace 英文纠错（含正则 fallback） |

### 4.2 routers/ttyd.py（`/api/ttyd/*`）

| 路径 | 方法 | 说明 |
|------|------|------|
| `/api/ttyd/start/{pane_id}` | POST | 按需启动 ttyd（如未运行），返回配置 |
| `/api/ttyd/status/{pane_id}` | GET | 检查 ttyd 是否在对应端口监听（返回 `ready: bool`） |
| `/api/ttyd/by-name/{name}` | GET | 返回 `{port, token, url}`（供 ttyd-proxy 调用） |
| `/api/ttyd/list` | GET | 列出所有 ttyd 配置 |
| `/api/ttyd/config/{pane_id}` | DELETE | 删除 ttyd 配置记录 |

### 4.3 routers/tmux/router.py（`/api/tmux/*`）

| 路径 | 方法 | 说明 |
|------|------|------|
| `/api/tmux/send` | POST | 向任意 pane 发送（body: `{win_id, text/keys}`） |
| `/api/tmux/create` | POST | 创建 window + 启动 ttyd（主接口） |
| `/api/tmux/panes/{pane_id}` | GET | 获取 pane 配置 |
| `/api/tmux/panes/{pane_id}` | PATCH | 更新 pane 元数据（title/workspace/proxy 等） |
| `/api/tmux/panes/{pane_id}` | DELETE | 销毁 pane（kill tmux window + ttyd） |
| `/api/tmux/panes/{pane_id}/restart` | POST | 重启 pane（重建 window + 重启 ttyd） |
| `/api/tmux/capture_pane` | POST | 捕获 pane 终端输出 |
| `/api/tmux/tree` | GET | 返回 sessions/windows/panes 树结构 |
| `/api/tmux/clear` | POST | 清除所有会话 |

## 5. 数据库 Schema

数据库：`tts_bot`（MySQL 3306）

### ttyd_config（pane 配置）

```sql
CREATE TABLE ttyd_config (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    pane_id     VARCHAR(255) NOT NULL UNIQUE,  -- e.g. "worker:myapp.0"
    title       VARCHAR(255),
    ttyd_port   INT NOT NULL,                  -- e.g. 15103
    url         VARCHAR(512),                  -- 外部访问 URL
    workspace   VARCHAR(500),                  -- 工作目录
    init_script VARCHAR(500),                  -- 启动命令
    proxy       VARCHAR(500),                  -- HTTP 代理地址
    tg_token    VARCHAR(200),                  -- Telegram bot token
    tg_chat_id  VARCHAR(100),                  -- Telegram chat ID
    tg_enable   TINYINT(1) DEFAULT 0,
    ttyd_pid    INT,                           -- ttyd 进程 PID（参考用）
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);
```

### local_services（本地服务注册）

```sql
CREATE TABLE local_services (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    port        INT UNIQUE NOT NULL,
    name        VARCHAR(255) NOT NULL,
    description TEXT,
    url         VARCHAR(512),
    path        VARCHAR(512),
    status      VARCHAR(50) DEFAULT 'unknown',
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);
```

## 6. 核心实现机制

### 6.1 tmux 通信（Docker PID 隔离绕过）

fast-api 运行在 Docker 容器内（`network_mode: host`，`privileged: true`），但 tmux 服务器运行在 Host 上。

```python
# 所有 tmux 命令通过 socket 文件通信
TMUX_SOCKET = "/home/w3c_offical/.tmux/default"  # 宿主机 socket，容器内挂载

def run_tmux(cmd):
    result = subprocess.run(["tmux", "-S", TMUX_SOCKET] + cmd, ...)
```

**ttyd 进程杀死**（`os.kill()` 在容器内无法杀死 host 进程）：

```python
# 通过 tmux run-shell 在 host 上执行，绕过 PID namespace 隔离
run_tmux(["run-shell", (
    f"kill -9 $(lsof -ti:{port} 2>/dev/null) 2>/dev/null; "
    f"pkill -9 -f 'tmux attach -t {pane_id}' 2>/dev/null; "
    f"for i in $(seq 1 20); do lsof -ti:{port} >/dev/null 2>&1 || break; sleep 0.1; done; true"
)])
```

### 6.2 端口分配

```python
# 扫描 ttyd_config 表，找第一个未被占用的端口
for p in range(15100, 15301):
    if not db.exists(ttyd_port=p):
        port = p
        break
```

### 6.3 ttyd 启动

```python
# 通过 tmux send-keys 在对应 pane 内启动 ttyd
ttyd_cmd = f"nohup ttyd -W -p {port} -c user:{token} tmux attach -t {pane_id} > /tmp/ttyd_{port}.log 2>&1 &"
run_tmux(["send-keys", "-t", pane_id, ttyd_cmd, "Enter"])

# 等待端口就绪（最多 30s，每 0.5s 轮询）
while elapsed < 30:
    if socket.connect_ex(("127.0.0.1", port)) == 0:
        return {"port": port, "token": token, "url": url}
    time.sleep(0.5)
```

### 6.4 响应格式

所有接口支持 JSON / YAML 双格式：
- 请求头 `Accept: application/json` → 返回 JSON
- 其他（默认）→ 返回 YAML（适合命令行 curl 查看）

### 6.5 认证

```python
# ~/global.json 中读取 api_token（与 ttyd-proxy server、ttyd 进程共用同一 token）
AUTH_TOKEN = load_token()  # 64 字符 hex 字符串
security = HTTPBearer()

def verify_token(cred: HTTPAuthorizationCredentials = Depends(security)):
    if cred.credentials != AUTH_TOKEN:
        raise HTTPException(status_code=401, detail="invalid token")
```

**单 token 架构**：`~/global.json` 中的 `api_token` 同时用于：
- fast-api Bearer 认证
- ttyd 进程启动参数（`-c user:{api_token}`）
- ttyd-proxy 验证访问权限

不再有 per-pane token，数据库中无 `ttyd_token` 字段。

## 7. 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `TMUX_SOCKET` | `/home/w3c_offical/.tmux/default` | tmux socket 路径（宿主机） |
| `HOST_HOME` | `/home/w3c_offical` | 宿主机 home 目录 |
| `HOST_UID` | `1001` | 容器内用户 UID |
| `HOST_GID` | `1002` | 容器内用户 GID |
| `MYSQL_HOST` | `127.0.0.1` | MySQL 地址 |
| `MYSQL_PORT` | `3306` | MySQL 端口 |
| `MYSQL_USER` | `root` | MySQL 用户 |
| `MYSQL_PASSWORD` | — | MySQL 密码（必填） |
| `MYSQL_DATABASE` | `tts_bot` | 数据库名 |
| `TTYD_PORT_RANGE_PROD` | `15100-15300` | ttyd 端口分配范围 |
| `TTYD_BASE_URL` | `https://g-ttyd-api.cicy.de5.net` | ttyd 外部访问基础 URL |

## 8. 挂载依赖

| 宿主机路径 | 容器内路径 | 权限 | 用途 |
|-----------|-----------|------|------|
| `~/global.json` | `/home/w3c_offical/global.json` | ro | 读取 api_token |
| `~/personal/` | `/home/w3c_offical/personal/` | ro | 备用 global.json |
| `~/.kiro/` | `/home/w3c_offical/.kiro/` | ro | Skills 文档 |
| `~/workers/` | `/home/w3c_offical/workers/` | rw | pane 工作目录 |
| `~/tools/` | `/home/w3c_offical/tools/` | ro | tre 等工具 |
| `~/projects/` | `/home/w3c_offical/projects/` | ro | 项目代码（init_script 用） |
| `~/.tmux/` | `/home/w3c_offical/.tmux/` | rw | tmux socket |
| `/var/run/docker.sock` | `/var/run/docker.sock` | rw | docker exec 命令 |
