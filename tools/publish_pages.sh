#!/usr/bin/env bash
# ==========================================================================
#  把 frontend/ 发布到 GitHub Pages（gh-pages 分支，站点根目录）
#
#    bash tools/publish_pages.sh                # 发布
#    bash tools/publish_pages.sh --check        # 只看当前 Pages 状态
#
#  原理：直接用 git plumbing 把 main 里的 frontend/ 子树做成一个提交，
#        不改工作区、不需要切换分支，推上去就是 Pages 站点。
# ==========================================================================
set -u
export HOME=/c/Users/Administrator
cd /d/OJ || exit 1

REPO="${OJ_REPO:-YHSome/oj-ojojoj}"
BRANCH="${OJ_PAGES_BRANCH:-gh-pages}"
KEY=/d/OJ/data/state/ssh/github_ed25519
KNOWN=/d/OJ/data/state/ssh/known_hosts
SSH=/usr/bin/ssh

export GIT_SSH_COMMAND="$SSH -i $KEY -o UserKnownHostsFile=$KNOWN -o IdentitiesOnly=yes"

check_pages() {
  local py=/c/Users/Administrator/.dsh/dsh-runtimes/dsh-primary-runtime/dependencies/python/python.exe
  "$py" - "$REPO" <<'PYEOF'
import json, sys, urllib.request
repo = sys.argv[1]
owner, name = repo.split("/", 1)
for url in ("https://api.github.com/repos/%s/pages" % repo,):
    try:
        with urllib.request.urlopen(urllib.request.Request(
                url, headers={"User-Agent": "oj"}), timeout=20) as r:
            d = json.loads(r.read().decode())
        print("  Pages 状态: 已启用")
        print("    站点地址 : %s" % d.get("html_url"))
        print("    来源     : %s / %s" % (d.get("source", {}).get("branch"),
                                          d.get("source", {}).get("path")))
        print("    状态     : %s" % d.get("status"))
    except Exception as e:
        print("  Pages 状态: 未启用或查不到（%s）" % str(e)[:80])
        print("    站点地址 : https://%s.github.io/%s/" % (owner.lower(), name))
PYEOF
}

if [ "${1:-}" = "--check" ]; then
  echo "=== Pages 状态 ==="
  check_pages
  exit 0
fi

echo "=== 0) 工作区检查 ==="
if [ -n "$(git status --porcelain)" ]; then
  echo "  有未提交改动，先提交："
  git status --short | head -10
  exit 3
fi
echo "  ✔ 干净（$(git rev-list --count HEAD) 个提交）"

echo
echo "=== 1) 给前端资源打版本号（破 CDN 缓存）并同步 main ==="
PY=/c/Users/Administrator/.dsh/dsh-runtimes/dsh-primary-runtime/dependencies/python/python.exe
VER="p$(git rev-parse --short HEAD)"
if [ -n "$(git status --porcelain frontend/index.html)" ]; then
  echo "  index.html 有未提交改动，先提交它"
  git add frontend/index.html
  git commit -q -m "chore(frontend): 提交 index.html 改动"
fi
env PYTHONUTF8=1 "$PY" tools/bump_frontend_version.py "$VER"
if [ -n "$(git status --porcelain frontend/index.html)" ]; then
  git add frontend/index.html
  git commit -q -m "chore(frontend): 资源版本号 $VER（改前端后立刻生效，不受 CDN 缓存影响）"
  echo "  已提交版本号变更"
fi
git push origin main 2>&1 | tail -2
TREE=$(git rev-parse "main:frontend") || { echo "  取不到 main:frontend"; exit 4; }
COMMIT=$(git commit-tree "$TREE" -m "pages: 发布纯静态前端到 GitHub Pages

来源：main 分支的 frontend/ 目录（含 .nojekyll）
说明：页面不含任何云端密钥，首次访问请在「连接设置」里填入自己的 TinyWebDB 实例。")
git update-ref "refs/heads/$BRANCH" "$COMMIT"
echo "  分支 $BRANCH -> $COMMIT"
echo "  内容："
git ls-tree -r --name-only "$COMMIT" | sed 's/^/    /'

echo
echo "=== 2) 推送 $BRANCH ==="
git push -f -u origin "$BRANCH" 2>&1 | tail -4

echo
echo "=== 3) Pages 状态 ==="
sleep 3
check_pages

echo
echo "=== 4) 站点自检 ==="
"/c/Users/Administrator/.dsh/dsh-runtimes/dsh-primary-runtime/dependencies/python/python.exe" - <<PYEOF
import urllib.request
owner, name = "${REPO}".split("/", 1)

# 4.1 官方 Pages（需要先在 Settings -> Pages 选 gh-pages 分支，一次性设置）
url_pages = "https://%s.github.io/%s/" % (owner.lower(), name)
try:
    with urllib.request.urlopen(urllib.request.Request(url_pages, headers={"User-Agent": "oj"}),
                                timeout=20) as r:
        print("  [官方 Pages] HTTP %s  %s" % (r.status, url_pages))
except Exception as e:
    print("  [官方 Pages] 还没启用/没好: %s" % str(e)[:60])
    print("               启用方法：Settings -> Pages -> Deploy from a branch -> %s / (root)" % "${BRANCH}")

# 4.2 免设置的镜像入口（raw.githack，仓库更新后自动跟随）
base = "https://raw.githack.com/%s/%s/main/frontend/" % (owner, name)
try:
    with urllib.request.urlopen(urllib.request.Request(base + "index.html",
                                                       headers={"User-Agent": "oj"}), timeout=20) as r:
        body = r.read(2000).decode("utf-8", "replace")
        print("  [githack 镜像] HTTP %s  text/html: %s" % (r.status, "<!DOCTYPE html>" in body))
        print("                 %sindex.html" % base)
except Exception as e:
    print("  [githack 镜像] 失败: %s" % str(e)[:60])
PYEOF

