#!/usr/bin/env bash
# ==========================================================================
#  一键推送到 GitHub
#     bash tools/push_github.sh <owner>/<repo> [分支名]
#  例：bash tools/push_github.sh yhs/oj-ojojoj
#
#  依赖：仓库内已配置 SSH 密钥（tools/ssh_setup.sh 生成）
#       或设置环境变量 GITHUB_TOKEN 走 HTTPS（PAT，需要 repo 权限）
# ==========================================================================
set -u
export HOME=/c/Users/Administrator
cd /d/OJ || exit 1

TARGET="${1:-}"
BRANCH="${2:-main}"
SSHDIR=/d/OJ/data/state/ssh
KEY="$SSHDIR/github_ed25519"
KNOWN="$SSHDIR/known_hosts"
SSH=/usr/bin/ssh

if [ -z "$TARGET" ]; then
  echo "用法: bash tools/push_github.sh <owner>/<repo> [分支]"
  echo "  例: bash tools/push_github.sh yhs/oj-ojojoj"
  exit 2
fi

echo "=== 0) 提交前检查 ==="
if [ -n "$(git status --porcelain)" ]; then
  echo "  工作区不干净，先提交："
  git status --short | head -10
  exit 3
fi
echo "  ✔ 工作区干净（$(git rev-list --count HEAD) 个提交 / $(git ls-files | wc -l) 个文件）"

echo
echo "=== 1) 配置远端 ==="
if [ -n "${GITHUB_TOKEN:-}" ]; then
  URL="https://x-access-token:${GITHUB_TOKEN}@github.com/${TARGET}.git"
  echo "  使用 HTTPS + PAT"
else
  URL="git@github.com:${TARGET}.git"
  git config core.sshCommand "$SSH -i $KEY -o UserKnownHostsFile=$KNOWN -o IdentitiesOnly=yes"
  echo "  使用 SSH（密钥 $KEY）"
fi
git remote remove origin 2>/dev/null
git remote add origin "$URL"
echo "  origin = $(echo "$URL" | sed 's#//[^@]*@#//***@#')"

echo
echo "=== 2) 测试认证 ==="
if [ -n "${GITHUB_TOKEN:-}" ]; then
  if timeout 30 git ls-remote origin >/dev/null 2>&1; then
    echo "  ✔ 认证成功"
  else
    echo "  ✘ 认证失败：PAT 无效或没有该仓库权限"
    exit 4
  fi
else
  who=$(timeout 25 $SSH -i "$KEY" -o UserKnownHostsFile="$KNOWN" -o IdentitiesOnly=yes -T git@github.com 2>&1 | head -1)
  echo "  $who"
  case "$who" in
    Hi*) echo "  ✔ 认证成功" ;;
    *) echo "  ✘ 认证失败：请先把以下公钥加到 GitHub → Settings → SSH and GPG keys"
       cat "$KEY.pub"
       exit 4 ;;
  esac
fi

echo
echo "=== 3) 推送 ==="
git branch -M "$BRANCH"
git push -u origin "$BRANCH" 2>&1 | tail -5
git push origin --tags 2>&1 | tail -2

echo
echo "=== 4) 结果 ==="
git remote -v | sed 's#//[^@]*@#//***@#'
echo "本地 HEAD: $(git log --oneline -1)"
echo "远端 HEAD: $(timeout 30 git ls-remote origin "refs/heads/$BRANCH" 2>/dev/null | awk '{print $1}')"
echo
echo "完成！仓库地址: https://github.com/${TARGET}"
