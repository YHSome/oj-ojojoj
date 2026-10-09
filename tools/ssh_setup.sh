#!/usr/bin/env bash
# 在仓库内生成/检查 GitHub SSH 密钥，并完成推送前的全部准备
export HOME=/c/Users/Administrator
cd /d/OJ || exit 1

SSHDIR=/d/OJ/data/state/ssh
KEY="$SSHDIR/github_ed25519"
KNOWN="$SSHDIR/known_hosts"
KEYGEN=/usr/bin/ssh-keygen
SSH=/usr/bin/ssh
mkdir -p "$SSHDIR"

echo "=== 1) 生成密钥（若无） ==="
if [ -f "$KEY" ]; then
  echo "  已存在: $KEY"
else
  "$KEYGEN" -t ed25519 -C "oj-ojojoj@$(hostname)" -f "$KEY" -N "" -q
  echo "  已生成: $KEY（无口令，方便非交互推送）"
fi
chmod 600 "$KEY" 2>/dev/null
echo
echo "  私钥: $KEY       （务必保密；在 data/state/ 下已被 .gitignore 排除）"
echo "  公钥: $KEY.pub"

echo
echo "=== 2) 本机公钥内容（要贴到 GitHub 的那一行） ==="
cat "$KEY.pub"

echo
echo "=== 3) 公钥指纹（用于与 GitHub 上的显示核对） ==="
"$KEYGEN" -lf "$KEY.pub"

echo
echo "=== 4) 抓取并核对 GitHub 主机公钥（防中间人） ==="
SSHOPTS="-o UserKnownHostsFile=$KNOWN -o StrictHostKeyChecking=accept-new -o ConnectTimeout=12 -o IdentitiesOnly=yes -i $KEY"
rm -f "$KNOWN"
timeout 20 $SSH $SSHOPTS -T git@github.com >/dev/null 2>&1
if [ -f "$KNOWN" ]; then
  echo "  实际收到的 GitHub 主机指纹："
  "$KEYGEN" -lf "$KNOWN" | sed 's/^/    /'
  echo
  echo "  GitHub 官方公布的指纹（请人工比对）："
  echo "    ED25519  SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU"
  echo "    RSA      SHA256:uNiVztksCsDhcc0u9e8BujQXVUpKZIDTMczCvj3tD2s"
  echo "    ECDSA    SHA256:p2QAMXNIC1TJYWeIOttrVc98/R1BUFWu3/LiyKgUfQM"
else
  echo "  未能记录 known_hosts"
fi

echo
echo "=== 5) 当前认证状态 ==="
out=$(timeout 20 $SSH $SSHOPTS -T git@github.com 2>&1 | head -2)
echo "  $out"

echo
echo "=== 6) 给本仓库配置 SSH（只影响这个仓库） ==="
git config core.sshCommand "$SSH -i $KEY -o UserKnownHostsFile=$KNOWN -o IdentitiesOnly=yes"
echo "  core.sshCommand = $(git config core.sshCommand)"

echo
echo "=== 7) 顺带再测一次 HTTPS（若也通，就可以用 PAT 推送） ==="
if timeout 20 git ls-remote https://github.com/git/git.git HEAD >/dev/null 2>&1; then
  echo "  ✔ HTTPS 也通"
else
  echo "  ✘ HTTPS 仍不通（只能用 SSH）"
fi
