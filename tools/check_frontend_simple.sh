#!/usr/bin/env bash
# 简化后前端自检：语法 + app.js 引用的 DOM id 是否都在 index.html + 是否残留已删除的元素
export HOME=/c/Users/Administrator
cd /d/OJ || exit 1
N=/c/Users/Administrator/.dsh/dsh-runtimes/dsh-primary-runtime/dependencies/node/bin/node.exe
JS=frontend/assets/app.js
HTML=frontend/index.html

echo "=== JS 语法 ==="
"$N" --check "$JS" && echo "  app.js OK"

echo
echo "=== app.js 里引用的 #id 是否都在 index.html（缺的会报出来） ==="
mkdir -p data/tmp
grep -o "\$('#[a-zA-Z0-9_-]*')" "$JS" | sed "s/\\\$('#//;s/')//" | sort -u > data/tmp/used_ids.txt
miss=0
while read -r id; do
  [ -z "$id" ] && continue
  if ! grep -q "id=\"$id\"" "$HTML"; then
    echo "  ? 缺少: #$id"
    miss=$((miss+1))
  fi
done < data/tmp/used_ids.txt
if [ "$miss" = "0" ]; then
  echo "  ✔ 全部存在（共 $(wc -l < data/tmp/used_ids.txt) 个）"
else
  echo "  （注：若该 id 是在 JS 里动态生成的，出现「缺少」属正常）"
fi

echo
echo "=== 不该再出现的元素（已被简化掉） ==="
for id in health judgekey btn-refresh-key btn-judge-status judge-status setup-status cfg-api cfg-user cfg-secret btn-save-creds btn-test-creds btn-clear-creds btn-clear-log; do
  n=$(grep -c "id=\"$id\"" "$HTML")
  [ "$n" = "0" ] && printf "  ✔ 已移除 #%-18s\n" "$id" || printf "  ✘ 仍存在 #%s\n" "$id"
done

echo
echo "=== 标签页 ==="
grep -o 'data-tab="[a-z]*"' "$HTML" | sed 's/^/  /'
echo "=== 面板 ==="
grep -o 'data-panel="[a-z]*"' "$HTML" | sed 's/^/  /'

echo
echo "=== 应当保留的关键元素 ==="
for id in login-user login-pass btn-login btn-register problem-list mine-list rank-body rank-head btn-submit code p-pid p-title; do
  n=$(grep -c "id=\"$id\"" "$HTML")
  [ "$n" != "0" ] && printf "  ✔ #%-16s\n" "$id" || printf "  ✘ 缺少 #%s\n" "$id"
done

echo
echo "=== 是否还残留已删除的函数 ==="
for fn in renderSetup saveCredentials testCredentials loadJudgeStatus; do
  n=$(grep -c "function $fn" "$JS")
  [ "$n" = "0" ] && printf "  ✔ 已删除 %s\n" "$fn" || printf "  ✘ 仍存在 %s\n" "$fn"
done
