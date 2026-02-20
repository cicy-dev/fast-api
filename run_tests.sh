#!/bin/bash
# fast-api/run_tests.sh
# 全量测试入口 — pre-commit 前必须通过
# AI Agent 规范: 见 DOCS/TDD.md
set -euo pipefail

cd "$(dirname "$0")"

FAIL=0

echo "========================================"
echo "  fast-api TDD 测试套件"
echo "========================================"

# 0. 确认服务运行中
echo ""
echo "--- 服务健康检查 ---"
if ! curl -sf http://localhost:14444/health > /dev/null 2>&1; then
  echo "ERROR: fast-api (port 14444) 未运行"
  echo "  → 启动: docker compose up -d"
  exit 1
fi
echo "  ✓ fast-api port 14444 ok"

# 1. curl API 测试
echo ""
echo "--- curl API 测试 ---"
for script in tests/curl/test_*.sh; do
  [ -f "$script" ] || continue
  echo ""
  if bash "$script"; then
    :
  else
    echo "  SUITE FAILED: $script"
    FAIL=$((FAIL+1))
  fi
done

# 2. pytest 集成测试（容器内）
echo ""
echo "--- pytest 集成测试 ---"
if docker exec fast-api python -m pytest tests/ -v --tb=short -q 2>&1; then
  echo "  ✓ pytest passed"
else
  echo "  SUITE FAILED: pytest"
  FAIL=$((FAIL+1))
fi

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
  echo "  → 规范: DOCS/TDD.md"
  echo "========================================"
  exit 1
fi
