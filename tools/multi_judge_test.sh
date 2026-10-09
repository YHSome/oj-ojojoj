#!/usr/bin/env bash
# ==========================================================================
#  多机共判实机验证：同机起 2 台判题机（不同 judge.id），投递一批任务，
#  检查是否被均摊、有没有重复判、有没有漏任务。
#
#    bash tools/multi_judge_test.sh [每台workers数] [投递数]
# ==========================================================================
set -u
export HOME=/c/Users/Administrator
cd /d/OJ || exit 1
PY=/c/Users/Administrator/.dsh/dsh-runtimes/dsh-primary-runtime/dependencies/python/python.exe
W=${1:-2}
N=${2:-8}
LOGD=data/tmp/multijudge

mkdir -p "$LOGD" data/state

kill_judges() {
  pkill -f "daemon.py" 2>/dev/null
  if [ $? -ne 0 ]; then
    powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { \$_.CommandLine -like '*daemon.py*' } | ForEach-Object { Stop-Process -Id \$_.ProcessId -Force -ErrorAction SilentlyContinue }" >/dev/null 2>&1
  fi
}

echo "=== 0) 停掉已有判题机（避免干扰） ==="
kill_judges
sleep 2
echo "  完成清理"

echo
echo "=== 1) 起两台判题机（各 $W 个 worker，auto 分单模式） ==="
env PYTHONUTF8=1 "$PY" backend/daemon.py --workers "$W" --allow-multi \
    --set judge.id=JUDGE-A --set judge.share_mode=auto > "$LOGD/A.log" 2>&1 &
A=$!
env PYTHONUTF8=1 "$PY" backend/daemon.py --workers "$W" --allow-multi \
    --set judge.id=JUDGE-B --set judge.share_mode=auto > "$LOGD/B.log" 2>&1 &
B=$!
echo "  JUDGE-A pid=$A   JUDGE-B pid=$B"
sleep 8

echo
echo "=== 2) 集群视图 ==="
env PYTHONUTF8=1 "$PY" - <<'EOF'
import os, sys
sys.path.insert(0, "backend")
import config as ojconfig
from store import Store
from twdb import TinyWebDB
cfg = ojconfig.load()
db = TinyWebDB(cfg.getv("api.base"), cfg.getv("api.user"), cfg.getv("api.secret"),
               min_interval_s=0.45, retries=4)
st = Store(db, cfg)
s = st.cluster_summary()
print("  在线判题机: %d 台  总 worker: %d  空闲: %d  语言: %s"
      % (s["judges"], s["workers"], s["free"], ",".join(s["langs"])))
for r in s["rows"]:
    print("    %-10s host=%-14s free=%d/%d load=%d%% 分单比例=%s 已判=%d"
          % (r["id"], r["host"], r["free"], r["workers"], r["load_pct"],
             r.get("share", "-"), r["judged"]))
EOF

echo
echo "=== 3) 投递 $N 个混合任务（ac/tle/ce/py） ==="
env PYTHONUTF8=1 "$PY" tools/burst_submit.py --count "$N" --mix --timeout 300

echo
echo "=== 4) 投递后的集群视图（分单比例应已收敛到 ~0.5） ==="
env PYTHONUTF8=1 "$PY" - <<'EOF'
import sys
sys.path.insert(0, "backend")
import config as ojconfig
from store import Store
from twdb import TinyWebDB
cfg = ojconfig.load()
db = TinyWebDB(cfg.getv("api.base"), cfg.getv("api.user"), cfg.getv("api.secret"),
               min_interval_s=0.45, retries=4)
st = Store(db, cfg)
s = st.cluster_summary()
for r in s["rows"]:
    print("    %-10s free=%d/%d load=%d%% 分单比例=%-6s 已判=%d 队列=%d"
          % (r["id"], r["free"], r["workers"], r["load_pct"], r.get("share"),
             r["judged"], r["queue"]))
EOF

echo
echo "=== 5) 两台各自的判题计数 ==="
echo "  --- JUDGE-A ---"; grep -c "判题完成" "$LOGD/A.log" || true
echo "  --- JUDGE-B ---"; grep -c "判题完成" "$LOGD/B.log" || true
echo "  --- 争抢/续租痕迹 ---"
grep -h "续租失败\|被别人抢到" "$LOGD"/A.log "$LOGD"/B.log 2>/dev/null | head -5 || echo "  （无）"

echo
echo "=== 6) 收工（停掉测试用判题机） ==="
kill $A $B 2>/dev/null
kill_judges
sleep 1
echo "  已停止。日志：$LOGD/A.log  $LOGD/B.log"
