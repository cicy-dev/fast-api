# Tmux Pipe-Pane QA

## Q: tmux pipe-pane是怎么用的？

**A: 基本用法**

开启输出捕获到文件：
```bash
tmux pipe-pane -o 'cat >> ~/output.log'
```

关闭捕获：
```bash
tmux pipe-pane
```

捕获到命令（实时处理）：
```bash
tmux pipe-pane -o 'grep ERROR >> ~/errors.log'
```

**常用选项：**
- `-o` - 开启捕获（output）
- `-O` - 同时捕获stdout和stdin
- `-t target-pane` - 指定目标pane

---

## Q: 如何捕获特定窗口的输出？

**A: 使用完整的pane路径**

1. 查找窗口的完整路径：
```bash
tmux list-panes -a -F '#{session_name}:#{window_name}.#{pane_index}' | grep w-20077
# 输出: w-20077:main.0
```

2. 开启捕获：
```bash
tmux pipe-pane -t w-20077:main.0 -o 'cat >> /path/to/output.log'
```

3. 检查pipe状态：
```bash
tmux display-message -t w-20077:main.0 -p '#{pane_pipe}'
# 输出: 1 (激活) 或 0 (未激活)
```

---

## Q: pipe-pane会捕获什么内容？

**A: 捕获所有终端输出**

包括：
- 用户输入的命令
- 命令的输出结果
- 终端颜色代码（ANSI escape codes）
- 加载动画和进度条
- 所有可见的终端内容

示例捕获内容：
```
[0m[38;5;10mtmux pipe-pane -t w-20077:main.0
[0m[0m[0m
测试
> 你想测试什么？需要我：
1. 查看捕获的日志内容？
2. 停止pipe-pane捕获？
```

---

## Q: pipe-pane有什么实际应用场景？

**A: 常见用途**

1. **调试和排查问题** - 记录完整的会话历史
2. **监控长时间运行的任务** - 捕获所有输出用于后续分析
3. **自动化测试** - 验证命令输出
4. **审计日志** - 记录操作记录

**高级用法：**

只记录错误：
```bash
tmux pipe-pane -o 'grep -i error >> errors.log'
```

带时间戳的日志：
```bash
tmux pipe-pane -o 'ts "[%Y-%m-%d %H:%M:%S]" >> timestamped.log'
```

实时分析：
```bash
tmux pipe-pane -o 'tee >(grep WARNING >> warnings.log)'
```

---

## Q: 如何停止pipe-pane捕获？

**A: 不带参数执行pipe-pane**

```bash
# 停止当前pane的捕获
tmux pipe-pane

# 停止指定pane的捕获
tmux pipe-pane -t w-20077:main.0
```

---

## Q: 如何读取pipe-pane日志？

**A: 使用FastAPI的capture_pane接口**

fast-api项目自动为所有ttyd pane启用pipe-pane，日志保存在 `./logs/pipe-<pane_id>.log`

```bash
# 读取最后5行（默认）
fast-api /api/tmux/capture_pane '{"pane_id":"w-20077"}'

# 读取最后20行
fast-api /api/tmux/capture_pane '{"pane_id":"w-20077","lines":20}'
```

**特性：**
- 自动清理ANSI转义码
- 支持指定行数
- 返回纯文本输出

---

## 常见问题排查

**问题：执行pipe-pane后没有生成日志文件**

可能原因：
1. 目标路径不正确（使用绝对路径）
2. pane标识符不正确（使用 `list-panes` 确认）
3. pipe已经在运行（检查 `#{pane_pipe}` 状态）

**问题：日志文件包含大量乱码**

这是正常的ANSI颜色代码。可以：
- 使用 `cat` 查看（会显示颜色）
- 使用 `less -R` 查看
- 用工具清理：`cat log | sed 's/\x1b\[[0-9;]*m//g'`
- **推荐：使用 `/api/tmux/capture_pane` API（自动清理）**
