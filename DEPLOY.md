# Fast API 部署文档

## 环境要求

- Python 3.8+
- MySQL 5.7+
- tmux
- supervisor

## 安装步骤

### 1. 安装系统依赖

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv tmux supervisor mysql-client
```

### 2. 创建虚拟环境

```bash
cd /home/w3c_offical/projects/ai-workers/fast-api
python3 -m venv venv
source venv/bin/activate
```

### 3. 安装 Python 依赖

```bash
pip install -r requirements.txt
```

主要依赖：
- `fastapi` - Web 框架
- `uvicorn` - ASGI 服务器
- `pymysql` - MySQL 连接
- `python-dotenv` - 环境变量管理
- `requests` - HTTP 客户端

### 4. 配置环境变量

复制示例配置：
```bash
cp .env.example .env
```

编辑 `.env` 文件：
```bash
# MySQL 配置
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=your_password
MYSQL_DATABASE=tts_bot

# API 认证
API_TOKEN=your_secret_token

# Cloudflare AI（可选）
CLOUDFLARE_ACCOUNT_ID=xxx
CLOUDFLARE_API_TOKEN=xxx
```

### 5. 数据库初始化

```bash
# 创建数据库
mysql -u root -p -e "CREATE DATABASE IF NOT EXISTS tts_bot;"

# 导入表结构
mysql -u root -p tts_bot < schema_users.sql
```

## 启动服务

### 方式 1: Supervisor（推荐生产环境）

1. 复制配置文件：
```bash
sudo cp supervisor.conf /etc/supervisor/conf.d/fast-api.conf
```

2. 修改配置文件路径（如果需要）：
```bash
sudo nano /etc/supervisor/conf.d/fast-api.conf
```

3. 重载 supervisor 配置：
```bash
sudo supervisorctl reread
sudo supervisorctl update
```

4. 启动服务：
```bash
sudo supervisorctl start fast-api
```

5. 查看状态：
```bash
sudo supervisorctl status fast-api
```

6. 查看日志：
```bash
sudo supervisorctl tail -f fast-api
# 或
tail -f /home/w3c_offical/projects/ai-workers/fast-api/fast-api.log
```

### 方式 2: 手动启动（开发环境）

```bash
cd /home/w3c_offical/projects/ai-workers/fast-api
source venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 14444 --reload
```

## Cron 自动处理服务

### 功能

- **Auto-trust**: 自动处理 kiro-cli 授权提示（发送 `t`）
- **Auto-compact**: 当 context usage > 70% 时自动执行 `/compact`

### 启动 Cron

#### 方式 1: 后台运行

```bash
cd /home/w3c_offical/projects/ai-workers/fast-api
sudo -u w3c_offical python3 cron_pane_handler.py > ~/cron_pane.log 2>&1 &
```

#### 方式 2: Supervisor（推荐）

创建 supervisor 配置 `/etc/supervisor/conf.d/pane-cron.conf`：

```ini
[program:pane-cron]
command=/home/w3c_offical/projects/ai-workers/fast-api/venv/bin/python3 cron_pane_handler.py
directory=/home/w3c_offical/projects/ai-workers/fast-api
user=w3c_offical
autostart=true
autorestart=true
stdout_logfile=/home/w3c_offical/cron_pane.log
stderr_logfile=/home/w3c_offical/cron_pane_error.log
environment=PANE_CHECK_INTERVAL="30",COMPACT_THRESHOLD="70"
```

启动：
```bash
sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl start pane-cron
```

#### 方式 3: systemd

创建 `/etc/systemd/system/pane-cron.service`：

```ini
[Unit]
Description=Pane Auto Handler
After=network.target mysql.service

[Service]
Type=simple
User=w3c_offical
WorkingDirectory=/home/w3c_offical/projects/ai-workers/fast-api
Environment="PANE_CHECK_INTERVAL=30"
Environment="COMPACT_THRESHOLD=70"
ExecStart=/home/w3c_offical/projects/ai-workers/fast-api/venv/bin/python3 cron_pane_handler.py
Restart=always
RestartSec=10
StandardOutput=append:/home/w3c_offical/cron_pane.log
StandardError=append:/home/w3c_offical/cron_pane_error.log

[Install]
WantedBy=multi-user.target
```

启动：
```bash
sudo systemctl daemon-reload
sudo systemctl enable pane-cron
sudo systemctl start pane-cron
sudo systemctl status pane-cron
```

### 配置参数

通过环境变量调整：

- `PANE_CHECK_INTERVAL`: 检查间隔（秒），默认 30
- `COMPACT_THRESHOLD`: 触发 compact 的 context usage 阈值（%），默认 70

示例：
```bash
PANE_CHECK_INTERVAL=10 COMPACT_THRESHOLD=80 python3 cron_pane_handler.py
```

### 查看日志

```bash
# 实时查看
tail -f ~/cron_pane.log

# 查看最近的处理记录
tail -50 ~/cron_pane.log | grep -E "(wait_auth|compact)"
```

## 常用命令

### Supervisor 管理

```bash
# 查看所有服务状态
sudo supervisorctl status

# 重启服务
sudo supervisorctl restart fast-api
sudo supervisorctl restart pane-cron

# 停止服务
sudo supervisorctl stop fast-api

# 查看日志
sudo supervisorctl tail -f fast-api
```

### 测试 API

```bash
# 健康检查
curl http://localhost:14444/health

# 测试 pane 状态检测
curl -H "Authorization: Bearer your_token" \
  http://localhost:14444/api/tmux/pane/agent/status/w-10001
```

## 故障排查

### 服务无法启动

1. 检查端口占用：
```bash
sudo lsof -i :14444
```

2. 检查日志：
```bash
tail -100 /home/w3c_offical/projects/ai-workers/fast-api/fast-api-error.log
```

3. 检查 MySQL 连接：
```bash
mysql -h 127.0.0.1 -u root -p -e "SELECT 1;"
```

### Cron 不工作

1. 检查进程：
```bash
ps aux | grep cron_pane_handler
```

2. 检查日志：
```bash
tail -50 ~/cron_pane.log
```

3. 手动测试：
```bash
cd /home/w3c_offical/projects/ai-workers/fast-api
sudo -u w3c_offical python3 cron_pane_handler.py
```

4. 检查 tmux 权限：
```bash
sudo -u w3c_offical tmux list-sessions
```

## 更新部署

```bash
# 1. 拉取最新代码
cd /home/w3c_offical/projects/ai-workers/fast-api
git pull

# 2. 更新依赖
source venv/bin/activate
pip install -r requirements.txt

# 3. 重启服务
sudo supervisorctl restart fast-api
sudo supervisorctl restart pane-cron

# 4. 检查状态
sudo supervisorctl status
```

## 安全建议

1. 使用强 API Token
2. 限制 API 访问 IP（通过 nginx/防火墙）
3. 定期更新依赖：`pip list --outdated`
4. 定期备份数据库
5. 监控日志文件大小，配置 logrotate

## 性能优化

1. 使用 gunicorn 多进程：
```bash
gunicorn main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:14444
```

2. 配置数据库连接池（已在 `db_pool.py` 中实现）

3. 启用 Redis 缓存（可选）
