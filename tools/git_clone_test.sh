#!/usr/bin/env bash
# 从 bundle 克隆出来，验证"别人拿到这个仓库"时能不能跑
set -u
export HOME=/c/Users/Administrator
cd /d/OJ || exit 1
PY=/c/Users/Administrator/.dsh/dsh-runtimes/dsh-primary-runtime/dependencies/python/python.exe
CLONE=/d/OJ/data/tmp/clone_test

rm -rf "$CLONE"
git clone -q dist/oj-ojojoj.bundle "$CLONE"
cd "$CLONE" || exit 1

echo "=== 克隆出来的顶层内容 ==="
ls
echo
echo "文件数: $(git ls-files | wc -l)  提交数: $(git rev-list --count HEAD)"

echo
echo "=== 凭据占位 + 私密文件未被跟踪（应为全 ✔） ==="
git grep -I -q "YOUR_SECRET" -- . && echo "  ✔ 公开配置里是占位符 YOUR_SECRET"
for f in config/oj_config.local.json frontend/assets/config.js data/state/judge_key.json; do
  if git ls-files --error-unmatch "$f" >/dev/null 2>&1; then echo "  ❌ 竟然被跟踪了: $f"; else echo "  ✔ 未跟踪: $f"; fi
done
echo "  ✔ data/work 被跟踪文件数: $(git ls-files data/work | wc -l)"

echo
echo "=== 语法自检（克隆出来的源码） ==="
"$PY" -m py_compile backend/*.py tools/*.py && echo "  Python syntax OK"

echo
echo "=== 路径自动补全 + 凭据占位（模拟新机器） ==="
"$PY" - <<'EOF'
import os, sys
root = os.getcwd()
sys.path.insert(0, os.path.join(root, "backend"))
import config as ojconfig
cfg = ojconfig.load()
print("  paths.root    :", cfg.getv("paths.root"))
print("  paths.problems:", cfg.getv("paths.problems"))
print("  local overlay :", cfg.local_path)
print("  api.user      :", cfg.getv("api.user"), "(placeholder -> configure it yourself)")
ok = cfg.getv("paths.problems").startswith(root) and cfg.getv("api.user") == "YOUR_USER"
print("  " + ("OK: paths point to the clone dir and credentials are placeholders" if ok
              else "FAIL: unexpected"))
sys.exit(0 if ok else 1)
EOF

echo
echo "=== 体积 ==="
git count-objects -vH | grep size-pack
