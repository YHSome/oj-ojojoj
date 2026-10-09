#!/usr/bin/env bash
# ==========================================================================
#  OJ-OJOJOJ 后端快捷脚本（Git Bash 用）
#    bash tools/oj.sh <命令> [参数...]
#  命令：selfcheck seed daemon once demo probe stats list rank inspect rejudge gc
# ==========================================================================
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"     # 仓库根（Git Bash 下形如 /d/OJ）
WROOT="$(cygpath -w "$ROOT" 2>/dev/null || echo "$ROOT")"   # Windows 形式路径

# 依次探测可用解释器
PY="${OJ_PY:-}"
if [ -z "$PY" ]; then
  for c in \
    "/c/Users/Administrator/.dsh/dsh-runtimes/dsh-primary-runtime/dependencies/python/python.exe" \
    "$(command -v python 2>/dev/null)" "$(command -v python3 2>/dev/null)"; do
    if [ -n "$c" ] && [ -x "$c" ]; then PY="$c"; break; fi
  done
fi
[ -n "$PY" ] || { echo "找不到 python，请设置 OJ_PY=/path/to/python.exe"; exit 1; }

export PYTHONIOENCODING=utf-8
export PYTHONUTF8=1
export TMP="$WROOT\\data\\tmp" TEMP="$WROOT\\data\\tmp" TMPDIR="$WROOT\\data\\tmp"
mkdir -p "$ROOT/data/tmp"

B="$ROOT/backend"
T="$ROOT/tools"

run() { echo ">> $PY $*"; "$PY" "$@"; }

case "${1:-help}" in
  selfcheck) shift; run "$T/selfcheck.py" --fix-hint "$@";;
  seed)      shift; run "$B/admin_cli.py" seed "$@";;
  probe)     shift; run "$B/admin_cli.py" probe "$@";;
  stats)     shift; run "$B/admin_cli.py" stats "$@";;
  list)      shift; run "$B/admin_cli.py" list "$@";;
  rank)      shift; run "$B/admin_cli.py" rank "$@";;
  inspect)   shift; run "$B/admin_cli.py" inspect "$@";;
  rejudge)   shift; run "$B/admin_cli.py" rejudge "$@";;
  gc)        shift; run "$B/admin_cli.py" gc "$@";;
  admin)     shift; run "$B/admin_cli.py" "$@";;
  client)    shift; run "$T/mock_client.py" "$@";;
  demo)      shift; run "$T/mock_client.py" demo "$@";;
  once)      shift; run "$B/daemon.py" --once --quiet "$@";;
  daemon)    shift; run "$B/daemon.py" --workers 4 -v "$@";;
  web)       shift; run "$T/serve_frontend.py" "$@";;               # 前端静态站点
  console)   shift; run "$T/console.py" "$@";;                       # 判题机中控台
  ctl)       shift; run "$T/test_console.py" "$@";;                  # 中控台自测
  e2e)       shift; "C:/Users/Administrator/.dsh/dsh-runtimes/dsh-primary-runtime/dependencies/node/bin/node.exe" "$T/e2e_frontend.js" "$@";;
  keygen)    shift; run "$B/admin_cli.py" keygen "$@";;
  pubkey)    shift; run "$B/admin_cli.py" pubkey "$@";;
  proxy)     shift; run "$T/github_proxy.py" "$@";;                 # 本机 GitHub 代理（DNS 型污染时有效）
  ghnet)     shift; run "$T/diag_github_net.py" "$@";;              # GitHub 网络三层诊断
  ghscan)    shift; run "$T/scan_github_channels.py" "$@";;         # 多 IP × 多 SNI 扫描幸存通道
  ghfix)     shift; run "$T/fix_github_hosts.py" "$@";;             # hosts 修复（需管理员）
  ghzip)     shift; run "$T/get_repo_zip.py" "$@";;                 # 网页打不开也能下载仓库
  cryptotest) shift; run "$T/test_crypto_python.py" "$@";;          # 前后端加密互通测试
  py)        shift; run "$@";;                 # 直接跑任意 python 脚本
  *)
    cat <<EOF
用法: bash tools/oj.sh <命令> [参数]

  selfcheck            环境自检（API / 编译器 / 沙箱 / 目录）
  seed                 把本地题库推到云端
  probe                云端连通性 + 题目一览
  stats                题库/用户/语言/API 统计
  list --what subs     列表（problems|subs|queue|judges|users|cmds）
  inspect --sid X      查看某个提交的详情（--code 带源码）
  rejudge --pid P1001  批量重测
  rank                 刷新并打印排行榜
  gc                   崩溃恢复 + 清理会话 + 刷榜
  demo --pid P1001     端到端自测（模拟 App Inventor 前端）
  client <子命令>      前端模拟客户端（register/login/submit/wait/rank）
  web                  启动前端静态站点（http://127.0.0.1:8000）
  console              启动判题机中控台（http://127.0.0.1:8090，一键开关+调参）
  ctl                  中控台 API 自测
  e2e <PID> <sample>   用真实前端 JS 跑加密端到端（ac/wa/ce）
  keygen / pubkey      生成并发布判题机密钥对 / 查看公钥
  proxy                启动本机 GitHub 代理（DNS 型污染时有效，浏览器设 127.0.0.1:8899）
  ghnet / ghscan       GitHub 网络三层诊断 / 多 IP×SNI 扫描
  ghzip [--extract]    绕过网页下载仓库 zip（codeload→ghproxy 自动切换）
  cryptotest           前后端加密互通测试（Python ↔ 浏览器 WebCrypto）
  daemon               启动判题机（常驻，Ctrl+C 退出）
  once                 判完当前队列就退出
  admin <子命令>       直接透传给 backend/admin_cli.py
  py <脚本> [参数]     用同一解释器跑任意脚本

当前解释器: $PY
EOF
    ;;
esac
