#!/usr/bin/env bash
# OJ-OJOJOJ 判题机启动脚本（Linux / WSL / Git-Bash）
set -e
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${OJ_PY:-python3}"
cd "$ROOT/backend"
echo "[OJ] python = $PY"
echo "[OJ] root   = $ROOT"
"$PY" "$ROOT/tools/selfcheck.py" || true
echo
echo "[OJ] 启动判题机（workers=4）..."
exec "$PY" "$ROOT/backend/daemon.py" --workers 4 -v "$@"
