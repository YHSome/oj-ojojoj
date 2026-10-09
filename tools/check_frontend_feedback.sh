#!/usr/bin/env bash
# 前端反馈改动的自检（语法 + DOM id 对齐 + 关键字）
export HOME=/c/Users/Administrator
cd /d/OJ || exit 1
N=/c/Users/Administrator/.dsh/dsh-runtimes/dsh-primary-runtime/dependencies/node/bin/node.exe

echo "=== JS 语法 ==="
"$N" --check frontend/assets/app.js && echo "  app.js OK"
"$N" --check frontend/assets/tinywebdb.js && echo "  tinywebdb.js OK"
"$N" --check frontend/assets/crypto.js && echo "  crypto.js OK"

echo
echo "=== app.js 引用的 DOM id 是否都在 index.html 里 ==="
for id in auth-status auth-progress auth-status-text btn-login btn-register btn-submit login-user login-pass; do
  a=$(grep -c "\\$('#$id')" frontend/assets/app.js)
  h=$(grep -c "id=\"$id\"" frontend/index.html)
  st="OK"
  [ "$h" = "0" ] && st="!! index.html 里没有这个 id"
  printf "  %-18s app.js引用=%s  html定义=%s  %s\n" "$id" "$a" "$h" "$st"
done

echo
echo "=== 关键反馈点 ==="
for kw in "busy('#btn-login'" "busyAll" "slowWatcher" "progress('#auth-progress'" "已等 " "正在把请求写入云端"; do
  n=$(grep -c "$kw" frontend/assets/app.js)
  printf "  %-28s %s 处\n" "$kw" "$n"
done

echo
echo "=== CSS 新增类 ==="
for c in btn-busy status-line progress-bar oj-spin oj-slide oj-pulse; do
  n=$(grep -c "$c" frontend/assets/style.css)
  printf "  %-16s %s 处\n" "$c" "$n"
done
