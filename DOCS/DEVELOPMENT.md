# fast-api 开发 / 测试 / 部署规范

## 1. 前置条件

| 工具 | 要求 | 说明 |
|------|------|------|
| Docker + Docker Compose | ≥ 24.x | 服务容器化运行 |
| MySQL | 3306 (host) | 数据库 `tts_bot` 必须存在且可连接 |
| tmux | 运行中（socket `~/.tmux/default`） | API 依赖宿主机 tmux server |
| ttyd | `~/.kiro` 或系统 PATH | fast-api 会在 host 上启动 ttyd 进程 |
| Cloudflare Tunnel | cloudflared 运行中 | 外网访问（开发可选） |

## 2. 开发环境启动

```bash
cd ~/projects/fast-api

# 首次启动（会构建镜像）
docker compose up --build

# 后续启动（镜像已存在）
docker compose up

# 后台运行
docker compose up -d

# 查看日志（实时）
docker logs -f fast-api
```

**服务访问地址：**

| 地址 | 说明 |
|------|------|
| http://localhost:14444 | 本地直连 |
| https://g-fast-api.cicy.de5.net | Cloudflare Tunnel 外网访问 |
| http://localhost:14444/docs | Swagger UI（自动生成）|
| http://localhost:14444/openapi.json | OpenAPI JSON |

### 2.1 热重载

uvicorn 以 `--reload` 模式运行，`/app` 目录通过 volume bind mount 到宿主机项目目录。修改任意 `.py` 文件后，uvicorn 自动检测并重启（约 1s），无需重建镜像。

```bash
# 验证热重载生效
docker logs -f fast-api | grep "Restarting"
```

### 2.2 环境变量配置

复制模板：
```bash
cp .env.example .env
```

编辑 `.env`：
```env
# tmux
TMUX_SOCKET=/home/w3c_offical/.tmux/default

# Host
HOST_UID=1001
HOST_GID=1002
HOST_HOME=/home/w3c_offical

# MySQL
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=your_password_here
MYSQL_DATABASE=tts_bot

# ttyd
TTYD_PORT_RANGE_PROD=15100-15300
TTYD_BASE_URL=https://g-ttyd-api.cicy.de5.net
```

> **重要**：`.env` 含密码，不提交 Git。使用 `.env.example` 作为模板。

### 2.3 数据库初始化

如果是首次部署，需创建数据表：

```sql
-- 连接 MySQL（在 host 上）
mysql -u root -p tts_bot

-- 创建 ttyd_config 表
CREATE TABLE IF NOT EXISTS ttyd_config (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    pane_id     VARCHAR(255) NOT NULL UNIQUE,
    title       VARCHAR(255),
    ttyd_port   INT NOT NULL,
    ttyd_token  VARCHAR(255) NOT NULL,
    url         VARCHAR(512),
    workspace   VARCHAR(500),
    init_script VARCHAR(500),
    proxy       VARCHAR(500),
    tg_token    VARCHAR(200),
    tg_chat_id  VARCHAR(100),
    tg_enable   TINYINT(1) DEFAULT 0,
    ttyd_pid    INT,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- 创建 local_services 表
CREATE TABLE IF NOT EXISTS local_services (
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

## 3. 代码规范

### 3.1 目录与文件

- **新增独立功能模块** → 在 `routers/` 下创建新文件（如 `routers/services.py`），在 `main.py` 中 `include_router`
- **小型辅助接口**（无独立路由逻辑）→ 直接在 `main.py` 添加
- **tmux 相关接口** → `routers/tmux/router.py`
- **ttyd 查询接口** → `routers/ttyd.py`

### 3.2 响应格式

所有接口统一支持 JSON / YAML 双格式：

```python
def format_response(data: dict, request: Request):
    accept = request.headers.get("accept", "")
    if "application/json" in accept.lower():
        return data
    yaml_str = yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)
    return PlainTextResponse(yaml_str, media_type="application/yaml")

@app.get("/api/example")
async def example(request: Request, token: str = Depends(verify_token)):
    return format_response({"key": "value"}, request)
```

### 3.3 认证

所有需要保护的路由必须添加 `token: str = Depends(verify_token)` 依赖：

```python
@app.get("/api/protected")
async def protected(request: Request, token: str = Depends(verify_token)):
    ...
```

无需认证的路由（如 `/health`、`/ping`）不加 `Depends`。

### 3.4 tmux 操作

所有 tmux 命令必须使用 `run_tmux()` 函数（使用正确的 socket），**不要直接调用** `subprocess.run(["tmux", ...])`：

```python
from routers.tmux.router import run_tmux

# 正确
run_tmux(["send-keys", "-t", pane_id, "echo hello", "Enter"])

# 错误（不指定 socket，在容器内找不到 host 上的 tmux server）
subprocess.run(["tmux", "send-keys", "-t", pane_id, "echo hello", "Enter"])
```

### 3.5 ttyd 进程管理

**启动**：通过 `tmux send-keys` 发送启动命令（在 host tmux session 内执行）。

**杀死**：通过 `tmux run-shell` 在 host 执行（绕过 Docker PID namespace）：

```python
run_tmux(["run-shell", (
    f"kill -9 $(lsof -ti:{port} 2>/dev/null) 2>/dev/null; "
    f"pkill -9 -f 'tmux attach -t {pane_id}' 2>/dev/null; "
    f"for i in $(seq 1 20); do lsof -ti:{port} >/dev/null 2>&1 || break; sleep 0.1; done; true"
)])
```

**不要使用** `os.kill()` 或 `subprocess.run(["kill", ...])` 直接杀进程，容器内看不到 host PID。

## 4. 测试

### 4.1 健康检查

```bash
TOKEN="6568a729f18c9903038ff71e70aa1685888d9e8f4ca34419b9a5d9cf784ffdf1"

# 无认证健康检查
curl http://localhost:14444/health
# 期望: {"status": "ok"}

# 认证验证
curl -H "Authorization: Bearer $TOKEN" http://localhost:14444/api/auth/verify
# 期望: {"valid": true, "token": "6568a729..."}
```

### 4.2 tmux API 测试

```bash
TOKEN="6568a729f18c9903038ff71e70aa1685888d9e8f4ca34419b9a5d9cf784ffdf1"

# 列出所有会话
curl -H "Authorization: Bearer $TOKEN" http://localhost:14444/api/tmux/sessions

# 会话树视图
curl -H "Authorization: Bearer $TOKEN" http://localhost:14444/api/tmux/tree

# tmux-list（镜像 tre 工具）
curl -H "Authorization: Bearer $TOKEN" http://localhost:14444/api/tmux-list

# 创建新 pane
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"win_name": "test", "session_name": "worker", "init_script": "pwd"}' \
  http://localhost:14444/api/tmux/create

# 重启 pane（注意 URL 编码冒号）
curl -X POST -H "Authorization: Bearer $TOKEN" \
  http://localhost:14444/api/tmux/panes/worker%3Atest.0/restart

# 删除 pane
curl -X DELETE -H "Authorization: Bearer $TOKEN" \
  http://localhost:14444/api/tmux/panes/worker%3Atest.0
```

### 4.3 ttyd API 测试

```bash
# 查询 pane 的 ttyd 配置
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:14444/api/ttyd/by-name/worker%3Ap1.0

# 检查 ttyd 是否就绪
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:14444/api/ttyd/status/worker%3Ap1.0
# 期望: {"ready": true/false}

# 列出所有 ttyd 配置
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:14444/api/ttyd/list
```

### 4.4 运行集成测试

```bash
# 在宿主机上（需要 pytest）
cd ~/projects/fast-api
pip install pytest
pytest tests/ -v

# 在容器内
docker exec fast-api python -m pytest tests/ -v
```

### 4.5 功能验证清单

**创建 pane 验证：**
- [ ] `POST /api/tmux/create` 返回 `ttyd_port`、`ttyd_token`
- [ ] `ss -tlnp | grep 151xx` 确认端口已监听
- [ ] `curl http://localhost:151xx/` 返回非 401（确认 ttyd 用正确 token 启动）
- [ ] `GET /api/ttyd/by-name/{pane_id}` token 与进程 cmdline 中 token 一致

**重启 pane 验证：**
- [ ] 旧端口上 ttyd 进程已终止（`lsof -i :{port}` 无输出）
- [ ] 新 ttyd 以新 token 绑定同一端口
- [ ] DB 中 ttyd_token 已更新（`GET /api/ttyd/by-name/{pane_id}`）
- [ ] 无僵尸进程（`ps aux | grep "tmux attach -t {pane_id}"` 仅一条记录）

**常见问题排查：**

| 现象 | 诊断命令 | 原因 |
|------|---------|------|
| create 超时（30s） | `cat /tmp/ttyd_{port}.log` | ttyd 无法绑定端口（端口被占用） |
| 多个 ttyd 进程 | `ps aux \| grep "tmux attach -t {pane_id}"` | 旧进程未被 kill（PID 隔离问题） |
| DB 与进程 token 不匹配 | 对比 `by-name` 返回 vs `ps aux` 进程 | restart 时 kill 未等待端口释放 |
| tmux 命令失败 | `tmux -S ~/.tmux/default list-sessions` | tmux server 未运行，需重建 |
| tmux server 重建 | 见下方 | 所有 pane 丢失，需全量重启 |

**tmux server 宕机恢复：**
```bash
# 重建 tmux server（在宿主机上）
rm -f ~/.tmux/default
tmux -S ~/.tmux/default new-session -d -s worker -n main

# 然后通过 API 重启所有 pane（fast-api 会重新创建 tmux window）
TOKEN="..."
for pane in "worker%3Ap1.0" "worker%3Atest2.0"; do
  curl -X POST -H "Authorization: Bearer $TOKEN" \
    http://localhost:14444/api/tmux/panes/${pane}/restart
done
```

## 5. 生产部署

### 5.1 部署步骤

```bash
cd ~/projects/fast-api

# 1. 确认 .env 配置正确
cat .env

# 2. 停止旧容器
docker compose down

# 3. 重建并启动（代码有变更时）
docker compose up --build -d

# 4. 无代码变更时仅重启
docker restart fast-api

# 5. 验证
curl http://localhost:14444/health
docker logs fast-api --tail 20
```

### 5.2 依赖变更（requirements.txt）

修改 `requirements.txt` 后**必须重建镜像**：

```bash
docker compose down
docker compose up --build -d
```

热重载只对 `.py` 文件有效，不涉及依赖安装。

### 5.3 Cloudflare Tunnel

```bash
# 查看当前路由
bash ~/.kiro/skills/cloudflared.sh list

# fast-api 路由配置
bash ~/.kiro/skills/cloudflared.sh add g-fast-api.cicy.de5.net localhost:14444
```

### 5.4 服务监控

```bash
# 容器状态
docker ps | grep fast-api

# 实时日志
docker logs -f fast-api

# 端口监听状态（验证 ttyd 进程）
ss -tlnp | grep -E "151[0-9]{2}"

# 检查 DB 中 pane 记录数
docker exec fast-api python3 -c "
import os, pymysql
conn = pymysql.connect(host='127.0.0.1', port=3306,
    user=os.environ['MYSQL_USER'], password=os.environ['MYSQL_PASSWORD'],
    database='tts_bot', cursorclass=pymysql.cursors.DictCursor)
with conn.cursor() as c:
    c.execute('SELECT pane_id, ttyd_port FROM ttyd_config')
    for r in c.fetchall(): print(r)
"
```

## 6. 添加新路由

1. **小型接口**（直接加到 `main.py`）：

```python
@app.get("/api/new-endpoint")
async def new_endpoint(request: Request, token: str = Depends(verify_token)):
    # 业务逻辑
    return format_response({"key": "value"}, request)
```

2. **独立模块**（在 `routers/` 下新建文件）：

```python
# routers/my_module.py
from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse
import yaml

router = APIRouter(prefix="/api/my-module", tags=["my-module"])

@router.get("/items")
async def list_items(request: Request):
    ...
```

然后在 `main.py` 中注册：
```python
from routers import my_module
app.include_router(my_module.router, dependencies=[Depends(verify_token)])
```

## 7. Git 工作流

```bash
cd ~/projects/fast-api

# 查看状态
git status

# 提交
git add main.py routers/...
git commit -m "feat/fix: 描述"

# 注意：不要提交
# - .env（含密码）
# - __pycache__/
```

`.gitignore` 应包含：
```
.env
__pycache__/
*.pyc
.pytest_cache/
```
