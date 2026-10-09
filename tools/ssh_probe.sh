#!/usr/bin/env bash
# SSH 推送可行性探测
export HOME=/c/Users/Administrator
cd /d/OJ || exit 1
SSHDIR="$HOME/.ssh"

echo "=== 1) ~/.ssh 内容 ==="
if [ -d "$SSHDIR" ]; then ls -la "$SSHDIR"; else echo "  不存在（还没有任何 SSH 密钥）"; fi

# ssh 工具位置（PortableGit 自带）
SSH=$(command -v ssh || echo /d/OJ/tools/git-portable/usr/bin/ssh.exe)
KEYGEN=$(command -v ssh-keygen || echo /d/OJ/tools/git-portable/usr/bin/ssh-keygen.exe)
echo
echo "ssh      : $SSH"
echo "ssh-keygen: $KEYGEN"

echo
echo "=== 2) 现有公钥指纹（与你给的 SHA256:... 对比） ==="
found=0
for k in "$SSHDIR"/*.pub; do
  [ -e "$k" ] || continue
  found=1
  printf "  %-40s " "$(basename "$k")"
  "$KEYGEN" -lf "$k" 2>/dev/null | awk '{print $2}'
done
[ "$found" = "0" ] && echo "  没有任何 .pub 公钥文件"

echo
echo "=== 3) GitHub SSH 连通性 ==="
echo "-- 端口 22 --"
timeout 15 "$SSH" -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 \
  -T git@github.com 2>&1 | head -3
echo "-- 端口 443 (ssh.github.com) --"
timeout 15 "$SSH" -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 \
  -p 443 -T git@ssh.github.com 2>&1 | head -3

echo
echo "=== 4) 已知主机指纹（第一次连接会记录，可用于核对） ==="
timeout 15 "$SSH" -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -T git@github.com 2>/dev/null >/dev/null
"$KEYGEN" -lf "$SSHDIR/known_hosts" 2>/dev/null | head -5 || echo "  known_hosts 为空"
