#!/usr/bin/env bash
# 验证配置 JSON + 再跑一次多机共判（验证自适应节流）
export HOME=/c/Users/Administrator
cd /d/OJ || exit 1
PY=/c/Users/Administrator/.dsh/dsh-runtimes/dsh-primary-runtime/dependencies/python/python.exe

echo "=== 配置校验 ==="
env PYTHONUTF8=1 "$PY" tools/check_config_json.py || exit 1

echo
bash tools/multi_judge_test.sh 2 6 2>&1 | grep -v "^\[twdb\]" | tail -45
