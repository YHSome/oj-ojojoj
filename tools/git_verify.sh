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
# 关键：不要把真实凭据写进本脚本（否则脚本自己就泄露了）。
# 从本地私密配置里读出真实值当搜索词，只在内存里用。
PY=/c/Users/Administrator/.dsh/dsh-runtimes/dsh-primary-runtime/dependencies/python/python.exe
PATTERNS=$("$PY" - <<'PYEOF'
import json, os
out = []
for path in ("config/oj_config.local.json", "frontend/assets/config.js"):
    if not os.path.isfile(path):
        continue
    txt = open(path, encoding="utf-8").read()
    if path.endswith(".json"):
        try:
            d = json.loads(txt)
            a = d.get("api", {})
            out += [a.get("user", ""), a.get("secret", ""),
                    (d.get("auth", {}) or {}).get("admin_key", "")]
            b = a.get("browse", "")
            if "/" in b:
                out.append(b.rsplit("/", 1)[-1])
        except ValueError:
            pass
    else:
        for key in ("user", "secret"):
            i = txt.find(key + ":")
            if i >= 0:
                seg = txt[i:].split("'", 2)
                if len(seg) > 1:
                    out.append(seg[1])
print("\n".join(x for x in out if x and len(x) > 3))
PYEOF
)
idx=0
while IFS= read -r pat; do
  [ -z "$pat" ] && continue
  idx=$((idx+1))
  n=$(git grep -I -l -e "$pat" -- . 2>/dev/null | wc -l)
  echo "  凭据#$idx  命中 $n 个文件  $([ "$n" = "0" ] && echo '✔' || echo '❌ 需要处理')"
  git grep -I -n -e "$pat" -- . 2>/dev/null | head -3
done <<< "$PATTERNS"
[ "$idx" = "0" ] && echo "  （没有本地私密配置可读，跳过；通用模式检查如下）"
git grep -I -n -e "PRIVATE KEY" -- . 2>/dev/null | grep -v "GitHub发布指南" | head -3 || true

echo
echo "=== 4) 不该入库的路径 ==="
git ls-files | grep -E 'data/(work|state|cache|tmp)/|^logs/|judge_key|oj_config\.local\.json|assets/config\.js$|w64devkit|git-portable|third_party' || echo "  ✔ 无"

echo
echo "=== 5) 顶层结构 ==="
git ls-files | awk -F/ '{print $1}' | sort | uniq -c | sort -rn

echo
echo "=== 6) 文件总大小 ==="
git ls-files -z | xargs -0 du -ch 2>/dev/null | tail -1
