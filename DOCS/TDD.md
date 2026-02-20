# TDD 开发规范 — fast-api

> **强制执行**：所有向此项目贡献代码的 AI Agent 必须完整遵守本规范。
> **核心原则**：先写测试，再写实现；测试不通过，不允许提交代码。

---

## 1. 工具链

| 工具 | 用途 | 安装 |
|------|------|------|
| `curl` | API 端点测试（curl-RPC 风格） | 系统内置 |
| `pytest` | Python 单元 / 集成测试 | `pip install pytest` |
| `docker exec fast-api` | 在容器内运行测试 | Docker 运行中 |

> fast-api 是纯 HTTP API 服务，无前端，**不使用** electron-mcp / curl-rpc。
> 所有测试均通过 `curl` 或 `pytest` 完成。

---

## 2. TDD 工作流（强制）

```
┌─────────────────────────────────────────────────┐
│  RED → GREEN → REFACTOR → TEST PASS → COMMIT    │
└─────────────────────────────────────────────────┘
```

### 每次开发必须按以下顺序进行：

```
Step 1  写 curl 测试脚本（tests/curl/test_<feature>.sh）
Step 2  写 pytest 测试（tests/test_<feature>.py）
Step 3  运行测试 → 确认 RED（测试应该失败）
Step 4  写实现代码
Step 5  运行测试 → 确认 GREEN（测试通过）
Step 6  运行 pre-commit 检查
Step 7  通过后才允许 git commit
```

---

## 3. 测试文件组织

```
fast-api/
├── tests/
│   ├── curl/                      # curl API 测试脚本
│   │   ├── test_health.sh
│   │   ├── test_auth.sh
│   │   ├── test_tmux.sh
│   │   ├── test_ttyd.sh
│   │   └── test_services.sh
│   ├── test_health.py             # pytest 测试
│   ├── test_auth.py
│   ├── test_tmux.py
│   ├── test_ttyd.py
│   ├── test_services.py
│   └── test_create_window.py      # 集成测试（已有）
└── run_tests.sh                   # 全量测试入口（pre-commit 调用）
```

---

## 4. curl 测试规范

### 4.1 脚本格式（必须遵守）

每个 curl 测试脚本必须：
- 以 `#!/bin/bash` 开头
- 定义 `PASS=0 FAIL=0` 计数器
- 每个测试用 `assert_*` 函数验证结果
- 脚本退出码：`FAIL > 0` 时退出码为 1
- 最后打印 `PASS: X  FAIL: Y` 汇总

### 4.2 标准模板

```bash
#!/bin/bash
# tests/curl/test_<feature>.sh
set -euo pipefail

BASE=${FAST_API_URL:-http://localhost:14444}
TOKEN=$(python3 -c "import json; print(json.load(open('/home/w3c_offical/global.json'))['api_token'])")
H_AUTH="Authorization: Bearer $TOKEN"
H_JSON="Content-Type: application/json"
H_ACCEPT="Accept: application/json"

PASS=0; FAIL=0

pass() { echo "  ✓ $1"; ((PASS++)); }
fail() { echo "  ✗ $1: $2"; ((FAIL++)); }

assert_status() {
  local desc="$1" expected="$2" actual="$3"
  [ "$actual" = "$expected" ] && pass "$desc" || fail "$desc" "expected $expected got $actual"
}

assert_contains() {
  local desc="$1" needle="$2" haystack="$3"
  echo "$haystack" | grep -q "$needle" && pass "$desc" || fail "$desc" "expected '$needle' in response"
}

echo "=== $(basename $0) ==="

# --- Tests go here ---

# Example:
echo "[health] GET /health"
RESP=$(curl -sf -w '\n%{http_code}' "$BASE/health")
CODE=$(echo "$RESP" | tail -1)
BODY=$(echo "$RESP" | head -1)
assert_status "HTTP 200" "200" "$CODE"
assert_contains "status ok" '"status"' "$BODY"

# --- Summary ---
echo ""
echo "PASS: $PASS  FAIL: $FAIL"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
```

### 4.3 各模块必须覆盖的测试用例

#### test_health.sh
```
GET /health                    → 200, {"status":"ok"}
GET /api/health                → 200, {"status":"ok","source":"fast-api"}
GET /ping                      → 200, 含 server_datetime
GET /api/auth/verify (无 token) → 403/401
GET /api/auth/verify (有效token) → 200, {"valid":true}
GET /api/auth/verify (无效token) → 401
```

#### test_tmux.sh
```
GET /api/tmux/sessions                     → 200, 含 sessions 字段
GET /api/tmux/tree                         → 200, 含 tree 字段
POST /api/tmux (无 token)                  → 401
POST /api/tmux (缺 target)                 → 200, success:false
POST /api/tmux/panes/{不存在pane}/restart  → 200, success:false
```

#### test_ttyd.sh
```
GET /api/ttyd/list             → 200, 含 configs 字段
GET /api/ttyd/status/{有效id}  → 200, 含 ready 字段
GET /api/ttyd/by-name/{有效id} → 200, 含 port/token/url
GET /api/ttyd/by-name/{不存在} → 404
```

#### test_services.sh
```
GET  /api/services             → 200, 含 services 字段
POST /api/services (新增)      → 200, success:true
GET  /api/services/{port}      → 200, 含该端口数据
DELETE /api/services/{port}    → 200, success:true
```

---

## 5. pytest 测试规范

### 5.1 基础结构

```python
# tests/test_<feature>.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from fastapi.testclient import TestClient
from main import app, AUTH_TOKEN

@pytest.fixture
def client():
    return TestClient(app)

@pytest.fixture
def auth(client):
    return {"Authorization": f"Bearer {AUTH_TOKEN}", "Accept": "application/json"}
```

### 5.2 命名约定

- 文件：`test_<module>.py`
- 类：`Test<Module>`（可选）
- 函数：`test_<action>_<scenario>`

```python
def test_health_returns_ok(client):          # 正常路径
def test_auth_verify_invalid_token(client):  # 错误路径
def test_tmux_create_window_success(client, auth): # 成功场景
```

### 5.3 每个新路由必须的测试覆盖

```python
# 对每个新 API endpoint，必须编写：
# 1. 正常响应测试（HTTP 200，字段检查）
# 2. 未认证测试（HTTP 401）
# 3. 参数缺失/非法测试（HTTP 400/422）
# 4. 资源不存在测试（HTTP 404）
```

---

## 6. pre-commit 检查脚本

### 6.1 创建 `run_tests.sh`

```bash
#!/bin/bash
# fast-api/run_tests.sh
# 全量测试 - pre-commit 前必须通过
set -euo pipefail

cd "$(dirname "$0")"

FAIL=0

echo "========================================"
echo "  fast-api TDD 测试套件"
echo "========================================"

# 1. curl API 测试
echo ""
echo "--- curl API 测试 ---"
for script in tests/curl/test_*.sh; do
  [ -f "$script" ] || continue
  bash "$script" || { echo "FAILED: $script"; FAIL=$((FAIL+1)); }
done

# 2. pytest 单元/集成测试
echo ""
echo "--- pytest 测试 ---"
docker exec fast-api python -m pytest tests/ -v --tb=short -q || FAIL=$((FAIL+1))

# 3. 汇总
echo ""
echo "========================================"
if [ "$FAIL" -eq 0 ]; then
  echo "  ALL TESTS PASSED ✓"
  echo "========================================"
  exit 0
else
  echo "  FAILED: $FAIL test suite(s)"
  echo "  → 禁止提交代码，请修复测试后重试"
  echo "========================================"
  exit 1
fi
```

### 6.2 安装 git pre-commit hook

```bash
# 在 fast-api 目录执行（首次初始化时运行一次）
cat > /home/w3c_offical/projects/fast-api/.git/hooks/pre-commit << 'EOF'
#!/bin/bash
cd "$(git rev-parse --show-toplevel)"
echo "[pre-commit] 运行 TDD 测试..."
bash run_tests.sh
if [ $? -ne 0 ]; then
  echo "[pre-commit] 测试未通过，提交被拒绝。"
  exit 1
fi
EOF
chmod +x /home/w3c_offical/projects/fast-api/.git/hooks/pre-commit
```

---

## 7. AI Agent 开发流程（逐步检查单）

开发新功能或修复 Bug 时，必须按顺序完成以下步骤：

```
[ ] Step 1: 阅读本规范（TDD.md）和 ARCHITECTURE.md
[ ] Step 2: 在 tests/curl/ 创建或更新 curl 测试脚本
[ ] Step 3: 在 tests/ 创建或更新 pytest 测试文件
[ ] Step 4: 运行测试，确认新测试 RED（失败）
            bash tests/curl/test_<feature>.sh  → 期望 FAIL > 0
            docker exec fast-api python -m pytest tests/test_<feature>.py -v
[ ] Step 5: 编写实现代码（main.py 或 routers/）
[ ] Step 6: 运行测试，确认 GREEN（通过）
            bash tests/curl/test_<feature>.sh  → 期望 FAIL = 0
            docker exec fast-api python -m pytest tests/test_<feature>.py -v
[ ] Step 7: 运行全量测试
            bash run_tests.sh
[ ] Step 8: 全量通过后才能 git commit
            git add <files>
            git commit -m "feat/fix: <描述>"
```

---

## 8. 禁止行为

以下行为**严格禁止**：

```
✗ 跳过测试直接 commit
✗ 仅手动验证，不写自动化测试
✗ 注释掉失败的测试来通过 pre-commit
✗ 使用 git commit --no-verify 绕过 hook
✗ 测试覆盖率低于已有 API 数量（每个 endpoint 至少 1 个 curl 测试）
✗ 不更新测试直接修改已有 API 的响应格式
```

---

## 9. 快速参考：常用测试命令

```bash
# 获取 token
TOKEN=$(python3 -c "import json; print(json.load(open('/home/w3c_offical/global.json'))['api_token'])")

# 单个 curl 测试
bash tests/curl/test_health.sh

# 全部 curl 测试
for f in tests/curl/test_*.sh; do bash "$f"; done

# pytest（宿主机）
cd ~/projects/fast-api && pip install pytest httpx && pytest tests/ -v

# pytest（容器内）
docker exec fast-api python -m pytest tests/ -v

# 全量（pre-commit 等价）
bash run_tests.sh

# 查看 API 文档
curl http://localhost:14444/openapi.json | python3 -m json.tool | grep '"path"'
```

---

## 10. 新增路由 Checklist

每次向 `main.py` 或 `routers/` 添加新路由时：

```
路由: GET /api/example

测试文件:
  tests/curl/test_example.sh     ← 必须创建
  tests/test_example.py          ← 必须创建

curl 测试必须包含:
  [ ] 正常调用（有效 token）→ 检查 HTTP 200 + 响应字段
  [ ] 无 token 调用         → 检查 HTTP 401/403
  [ ] 参数非法调用           → 检查 HTTP 400/422
  [ ] 资源不存在调用         → 检查 HTTP 404（如适用）

pytest 测试必须包含:
  [ ] test_example_success()
  [ ] test_example_no_auth()
  [ ] test_example_invalid_params()（如适用）
```
