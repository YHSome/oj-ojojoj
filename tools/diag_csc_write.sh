#!/usr/bin/env bash
# 定位"csc 写不了 D:\OJ"
export HOME=/c/Users/Administrator
cd /d/OJ || exit 1
CSC="/c/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe"
SRC="D:\\OJ\\tools\\launcher\\OJLauncher.cs"

echo "=== 1) Python 写 D:\\OJ（对照） ==="
env PYTHONUTF8=1 /c/Users/Administrator/.dsh/dsh-runtimes/dsh-primary-runtime/dependencies/python/python.exe -c "open(r'D:\\OJ\\_probe.txt','w').write('x'); print('  python 写入 OK')"

echo
echo "=== 2) csc 写到 D:\\OJ（从 bash 直接调） ==="
"$CSC" /nologo /target:winexe /codepage:65001 "/out:D:\\OJ\\_probe1.exe" \
  /reference:System.dll /reference:System.Drawing.dll /reference:System.Windows.Forms.dll \
  "$SRC" 2>&1 | head -3
ls -la /d/OJ/_probe1.exe 2>/dev/null && echo "  ✔ 生成成功" || echo "  ✘ 没生成"

echo
echo "=== 3) csc 写到 C:\\Users\\Administrator\\AppData\\Local\\Temp ==="
TMPWIN=$(cmd /c "echo %TEMP%" 2>/dev/null | tr -d '\r')
echo "  TEMP=$TMPWIN"
"$CSC" /nologo /target:winexe /codepage:65001 "/out:$TMPWIN\\_probe2.exe" \
  /reference:System.dll /reference:System.Drawing.dll /reference:System.Windows.Forms.dll \
  "$SRC" 2>&1 | head -3
ls -la "$(cygpath -u "$TMPWIN")/_probe2.exe" 2>/dev/null && echo "  ✔ 生成成功" || echo "  ✘ 没生成"

echo
echo "=== 4) 目录权限 ==="
ls -ld /d/OJ
icacls "D:\\OJ" 2>/dev/null | head -5

rm -f /d/OJ/_probe.txt /d/OJ/_probe1.exe "$(cygpath -u "$TMPWIN")/_probe2.exe" 2>/dev/null
