# Pane 状态检测服务 - 需求文档

## 1. 概述

### 1.1 目标
实现一个统一的 pane 状态检测服务，能够获取所有已注册 agent pane 的工作状态，包括：是否激活、是否空闲、是否在工作、当前工作的 agent 类型等。

### 1.2 适用范围
- FastAPI 后端服务
- 涉及 tmux session 管理和 ttyd web terminal

---

## 2. 数据库改动

### 2.1 ttyd_config 表新增字段

```sql
ALTER TABLE ttyd_config ADD COLUMN agent_type VARCHAR(50) DEFAULT NULL;
```

**字段说明：**

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| agent_type | VARCHAR(50) | NULL | Agent 类型标识 |

**可选值：**

| 值 | 说明 |
|-----|------|
| kiro-cli | Kiro CLI 工具 |
| opencode | OpenCode AI 助手 |
| claude_code | Claude Code CLI |
| gemini | Google Gemini CLI |
| claude-sonnet | Claude Sonnet |
| (其他) | 可后续扩展 |

---

## 3. 服务接口设计

### 3.1 标准化返回格式

所有状态检测接口返回统一的 JSON 格式：

```json
{
  "pane_id": "w-10001",
  "agent_type": "kiro-cli",
  "active": true,
  
  "status": "idle" | "thinking" | "wait_auth" | "wait_startup" | "compacting" | null,
  "isThinking": true | false | null,
  "isWaitingAuth": true | false | null,
  "isCompacting": true | false | null,
  "isWaitStartup": true | false | null,
  "isIdle": true | false | null,
  
  "contextUsage": 34 | null,
  "credits": 0.57 | null,
  "elapsedTime": 10 | null,
  
  "raw": "最后 N 行内容",
  "currentTask": "当前任务描述" | null
}
```

**字段说明：**

| 字段 | 类型 | 说明 |
|------|------|------|
| pane_id | string | Pane 标识 |
| agent_type | string | Agent 类型 (从数据库读取) |
| active | bool | tmux session 是否存在 |
| status | string/null | 工作状态 |
| isThinking | bool/null | 是否在思考 |
| isWaitingAuth | bool/null | 是否等待授权 |
| isCompacting | bool/null | 是否在压缩上下文 |
| isWaitStartup | bool/null | 是否等待启动 |
| isIdle | bool/null | 是否空闲 |
| contextUsage | int/null | 上下文使用率 (%) |
| credits | float/null | 消耗积分 (kiro-cli) |
| elapsedTime | int/null | 耗时 (秒) |
| raw | string/null | 终端内容预览 |
| currentTask | string/null | 当前任务描述 |

---

## 4. 服务层实现

### 4.1 文件位置
`services/pane_status.py`

### 4.2 核心函数

#### 4.2.1 `check_pane(pane_id: str, lines: int = 4) -> dict`

检测单个 pane 状态。

**参数：**
- `pane_id`: Pane ID (如 "w-10001" 或 "w-10001:main.0")
- `lines`: 截取最后 N 行内容，默认 4

**返回：** 标准化状态 dict

---

#### 4.2.2 `get_all_panes_status(lines: int = 4, include_inactive: bool = False, agent_type: str = None) -> list[dict]`

获取所有 pane 状态。

**参数：**
- `lines`: 截取最后 N 行内容，默认 4
- `include_inactive`: 是否包含未激活的 pane (数据库有记录但 tmux session 不存在)
- `agent_type`: 过滤特定 agent 类型

**返回：** List of pane status dicts

---

#### 4.2.3 `get_pane_config(pane_id: str) -> dict | None`

从 ttyd_config 表获取 pane 配置信息。

**返回：**
```json
{
  "pane_id": "w-10001",
  "title": "Agent 标题",
  "agent_type": "kiro-cli",
  "agent_duty": "agent 职责描述"
}
```

---

### 4.3 Agent 类型解析器

每种 agent_type 有独立的解析函数，遵循统一返回标准。

#### 4.3.1 解析器注册表

```python
PARSERS = {
    "kiro-cli": _parse_kiro_status,
    "opencode": _parse_opencode_status,
    "claude_code": _parse_claude_status,
    "gemini": _parse_gemini_status,
}
```

#### 4.3.2 解析器模板

```python
def _make_status(agent_type: str = None, active: bool = True) -> dict:
    """返回标准化状态模板"""
    return {
        "pane_id": None,
        "agent_type": agent_type,
        "active": active,
        "status": None,
        "isThinking": None,
        "isWaitingAuth": None,
        "isCompacting": None,
        "isWaitStartup": None,
        "isIdle": None,
        "contextUsage": None,
        "credits": None,
        "elapsedTime": None,
        "raw": None,
        "currentTask": None,
    }
```

#### 4.3.3 状态检测规则

| 状态 | 检测条件 |
|------|----------|
| idle | 提示符以 `>` 或 `$` 结尾 |
| thinking | 包含思考符号 `⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏` 且非 idle |
| wait_auth | 包含 `Allow this action` 或 `[y/n/t]` |
| wait_startup | 无输出或等待启动 |
| compacting | 包含 `Creating summary` 或 `/compact` |
| null | 无法确定状态时返回 null |

---

### 4.4 各 Agent 类型解析逻辑

#### 4.4.1 kiro-cli

**检测特征：**
- 提示符: `\d+% >` 或 `\d+% !>`
- Credits 信息: `Credits: X.XX`
- Time 信息: `Time: Xs`

**特有字段：**
- `credits`: 消耗积分
- `elapsedTime`: 耗时(秒)
- `contextUsage`: 上下文使用率 (如 `34%`)

**示例输出：**
```
 ▸ Credits: 0.57 • Time: 10s
34% >
```

---

#### 4.4.2 opencode

**检测特征：**
- Thinking 提示: `Thinking:`
- 构建信息: `Build · minimax`
- LSP 状态: `LSP`, `LSPs will activate`
- 思考符号: `⬝⬝■■`

**特有字段：**
- `contextUsage`: 上下文使用率
- `currentTask`: 当前任务描述

**示例输出：**
```
┃  Thinking: 用户想要删除 GCP 实例。

┃  Context: 14,628 tokens
┃  7% used

     ▣  Build · minimax-m2.5-free · 16.1s
```

---

#### 4.4.3 claude_code (预留)

待后续完善解析逻辑。

---

#### 4.4.4 gemini (预留)

待后续完善解析逻辑。

---

#### 4.4.5 默认解析器 (fallback)

当 agent_type 为空或不在注册表中时，使用默认解析器：
- 仅包含基础状态检测
- 特有字段返回 null

---

## 5. API 接口设计

### 5.1 单 Pane 状态接口 (已有，兼容)

**GET** `/api/tmux/pane/agent/status/{pane_id}`

- 调用 `check_pane(pane_id, lines=4)`
- 返回单个 pane 状态

**Query Parameters:**
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| lines | int | 4 | 截取最后 N 行 |

---

### 5.2 全量 Panes 状态接口 (新增)

**GET** `/api/panes/status`

**Query Parameters：**
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| lines | int | 4 | 截取最后 N 行 |
| include_inactive | bool | false | 包含未激活的 pane |
| agent_type | string | null | 过滤 agent 类型 |

**返回：**
```json
{
  "panes": [
    {
      "pane_id": "w-10001",
      "agent_type": "kiro-cli",
      "active": true,
      "status": "idle",
      "isThinking": false,
      "isWaitingAuth": false,
      "isCompacting": false,
      "isWaitStartup": false,
      "isIdle": true,
      "contextUsage": 34,
      "credits": null,
      "elapsedTime": null,
      "raw": "...",
      "currentTask": null
    }
  ]
}
```

---

## 6. CLI 命令设计

### 6.1 命令行调用支持

提供 CLI 入口脚本，可在服务器命令行直接调用。

#### 6.1.1 查看单个 Pane 状态

```bash
# 查看指定 pane 状态
python -m services.pane_status --pane w-10001

# 指定截取行数
python -m services.pane_status --pane w-10001 --lines 10
```

**输出示例：**
```
pane_id:     w-10001
agent_type:  kiro-cli
active:      true
status:      idle
isIdle:      true
isThinking:  false
context:     34%
credits:     0.57
time:        10s
```

---

#### 6.1.2 查看所有 Panes 状态

```bash
# 查看所有激活 panes
python -m services.pane_status --all

# 包含未激活的
python -m services.pane_status --all --include-inactive

# 过滤 agent 类型
python -m services.pane_status --all --agent-type kiro-cli

# 指定输出格式 (json/table/plain)
python -m services.pane_status --all --format json
python -m services.pane_status --all --format table
```

**Table 格式输出示例：**
```
+----------+-----------+--------+----------+-----------+---------+
| Pane ID  | Type      | Active | Status   | Context   | Credits |
+----------+-----------+--------+----------+-----------+---------+
| w-10001  | kiro-cli  | true   | idle     | 34%       | 0.57    |
| w-20085  | opencode  | true   | thinking | 7%        | -       |
| w-20086  | unknown   | true   | null     | -         | -       |
| w-30001  | kiro-cli  | false  | -        | -         | -       |
+----------+-----------+--------+----------+-----------+---------+
```

---

#### 6.1.3 帮助信息

```bash
python -m services.pane_status --help
```

---

### 6.2 CLI 参数汇总

| 参数 | 简写 | 说明 |
|------|------|------|
| --pane | -p | 查看单个 pane 状态 |
| --all | -a | 查看所有 panes 状态 |
| --lines | -l | 截取最后 N 行 (默认 4) |
| --include-inactive | -i | 包含未激活的 pane |
| --agent-type | -t | 过滤 agent 类型 |
| --format | -f | 输出格式 (json/table/plain) |
| --help | -h | 显示帮助 |

---

## 7. 实现顺序

1. **数据库改动**: 添加 `agent_type` 字段
2. **服务层实现**:
   - 实现 `_make_status()` 模板函数
   - 实现各 agent 类型解析器
   - 实现 `check_pane()` 函数
   - 实现 `get_pane_config()` 函数
   - 实现 `get_all_panes_status()` 函数
3. **API 接口**:
   - 现有接口 `/api/tmux/pane/agent/status/{pane_id}` (保持兼容)
   - 新增 `/api/panes/status`
4. **CLI 命令**: 支持命令行调用
5. **测试验证**: 验证各 agent 类型状态检测

---

## 8. 后续扩展

- 新增 agent 类型只需在 PARSERS 注册表添加解析函数
- 支持更多状态字段
- 添加缓存机制优化性能

---

文档版本: v2.0
日期: 2026-03-03
