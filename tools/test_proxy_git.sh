#!/usr/bin/env bash
# 验证：在 DNS 被污染的情况下，通过本机代理能否正常访问 GitHub（含 git HTTPS）
cd /d/OJ || exit 1
export HOME=/c/Users/Administrator

echo "=== 当前 DNS ==="
"/c/Users/Administrator/.dsh/dsh-runtimes/dsh-primary-runtime/dependencies/python/python.exe" -c "import socket;print(sorted({i[4][0] for i in socket.getaddrinfo('github.com',443)}))"

echo
echo "=== 1) 直连 HTTPS（预期失败） ==="
timeout 20 git ls-remote https://github.com/YHSome/oj-ojojoj.git HEAD 2>&1 | head -2
echo "   exit=$?"

echo
echo "=== 2) 走本机代理 127.0.0.1:8899 的 HTTPS ==="
timeout 40 env GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=http.proxy GIT_CONFIG_VALUE_0=http://127.0.0.1:8899 \
  git ls-remote https://github.com/YHSome/oj-ojojoj.git HEAD 2>&1 | head -3

echo
echo "=== 3) 走代理下载一个文件（模拟浏览器看仓库） ==="
timeout 40 env GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=http.proxy GIT_CONFIG_VALUE_0=http://127.0.0.1:8899 \
  git ls-remote https://github.com/YHSome/oj-ojojoj.git refs/heads/main 2>&1 | head -2

echo
echo "=== 4) 顺带确认 SSH 一直可用（推送用的就是它） ==="
timeout 20 /usr/bin/ssh -i /d/OJ/data/state/ssh/github_ed25519 \
  -o UserKnownHostsFile=/d/OJ/data/state/ssh/known_hosts -o IdentitiesOnly=yes -T git@github.com 2>&1 | head -1
