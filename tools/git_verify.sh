#!/usr/bin/env bash
# 发布前最终复核
set -u
export HOME=/c/Users/Administrator
cd /d/OJ || exit 1

echo "=== 1) 工作区是否干净 ==="
git status --porcelain | head -10
echo "  （空 = 干净；只应看到被忽略的文件不出现）"

echo
echo "=== 2) 仓库体积 ==="
git count-objects -vH | grep -E "size-pack|count|size:"

echo
echo "=== 3) 敏感信息扫描（tracked 文件） ==="
for pat in "8dc7ae54" "ojojoj" "BEGIN RSA" "judge_key.json\":" "PRIVATE KEY"; do
  n=$(git grep -I -l -e "$pat" -- . 2>/dev/null | wc -l)
  printf "  %-18s 命中 %s 个文件\n" "$pat" "$n"
  git grep -I -n -e "$pat" -- . 2>/dev/null | head -3
done

echo
echo "=== 4) 不该入库的路径 ==="
git ls-files | grep -E 'data/(work|state|cache|tmp)/|^logs/|judge_key|oj_config\.local\.json|assets/config\.js$|w64devkit|git-portable|third_party' || echo "  ✔ 无"

echo
echo "=== 5) 顶层结构 ==="
git ls-files | awk -F/ '{print $1}' | sort | uniq -c | sort -rn

echo
echo "=== 6) 文件总大小 ==="
git ls-files -z | xargs -0 du -ch 2>/dev/null | tail -1
