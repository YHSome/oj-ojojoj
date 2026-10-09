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
echo "=== 1) 用 main 的 frontend/ 子树生成 Pages 提交 ==="
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
echo "=== 4) 站点自检（构建可能要等 1 分钟） ==="
"/c/Users/Administrator/.dsh/dsh-runtimes/dsh-primary-runtime/dependencies/python/python.exe" - <<PYEOF
import time, urllib.request
url = "https://%s.github.io/%s/" % ("${REPO%%/*}".lower(), "${REPO##*/}")
for i in range(6):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "oj"}),
                                    timeout=20) as r:
            body = r.read(4000).decode("utf-8", "replace")
        print("  ✔ %s  HTTP %s  含 index 标题: %s" % (url, r.status, "OJ-OJOJOJ" in body))
        break
    except Exception as e:
        print("  … 第 %d 次还没好（%s）" % (i + 1, str(e)[:60]))
        time.sleep(15)
else:
    print("  站点还没构建好，稍后再刷：%s" % url)
PYEOF
