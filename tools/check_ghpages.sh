#!/usr/bin/env bash
cd /d/OJ || exit 1
export HOME=/c/Users/Administrator
export GIT_SSH_COMMAND="/usr/bin/ssh -i /d/OJ/data/state/ssh/github_ed25519 -o UserKnownHostsFile=/d/OJ/data/state/ssh/known_hosts -o IdentitiesOnly=yes"

echo "=== 远端分支 ==="
git ls-remote --heads origin

echo
echo "=== 本地 gh-pages 分支 ==="
git branch -v | head -5

echo
echo "=== gh-pages 里 index.html 是否含「连接设置」 ==="
git show gh-pages:index.html 2>/dev/null | grep -c "连接设置" || echo "  取不到"
echo "=== gh-pages 里的文件清单 ==="
git ls-tree -r --name-only gh-pages 2>/dev/null || echo "  没有本地 gh-pages 分支"
