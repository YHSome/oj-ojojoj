#!/usr/bin/env bash
# 找找机器上有没有已存在的 SSH 私钥（看是否与你给的指纹匹配）
export HOME=/c/Users/Administrator
TARGET="SHA256:CsmjAM27mYTj8lrPIsACkNKC1j+NQh7hNUE3uCqL8J8"
KEYGEN=/usr/bin/ssh-keygen

echo "搜索目标指纹: $TARGET"
echo

found=0
for d in "$HOME/.ssh" "$HOME/AppData/Roaming/ssh" "/d/OJ/data/state/ssh" "/c/ProgramData/ssh" \
         "$HOME/Documents" "$HOME/Desktop" "/d/keys" "/d/OJ"; do
  [ -d "$d" ] || continue
  while IFS= read -r k; do
    case "$k" in *.pub) continue;; esac
    fp=$("$KEYGEN" -lf "$k" 2>/dev/null | awk '{print $2}')
    [ -z "$fp" ] && continue
    found=1
    if [ "$fp" = "$TARGET" ]; then
      echo "  ★ 命中！ $k"
      echo "     指纹: $fp"
    else
      echo "    $k"
      echo "     指纹: $fp"
    fi
  done < <(find "$d" -maxdepth 3 -type f \( -name "id_*" -o -name "*_ed25519" -o -name "*_rsa" \) 2>/dev/null)
done

[ "$found" = "0" ] && echo "  没有找到任何私钥文件"

echo
echo "=== 顺带确认：能否写入 ~/.ssh ==="
mkdir -p "$HOME/.ssh" 2>&1 | head -2 && echo "  可写" || echo "  不可写（沙箱限制，所以本方案把密钥放在 D:\\OJ\\data\\state\\ssh）"
