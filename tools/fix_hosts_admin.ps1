# ============================================================================
#  永久修复 github.com 无法访问（DNS 污染）
#
#    双击 fix_hosts_admin.cmd 即可（会自动申请管理员权限）
#    还原：fix_hosts_admin.cmd revert
#    预览：fix_hosts_admin.cmd dry
#
#  原理：被污染时 github.com 会被解析到死 IP（例如 20.27.177.113）。
#        这里把它钉到实测可用的 GitHub 官方 IP（api.github.com/meta 网段内）。
# ============================================================================
param([string]$Mode = "")

$ErrorActionPreference = 'Stop'
$Ip    = '20.205.243.166'
$Hosts = Join-Path $env:windir 'System32\drivers\etc\hosts'
$Begin = '# === OJ github hosts fix (begin) ==='
$End   = '# === OJ github hosts fix (end) ==='
$Domains = @('github.com', 'www.github.com')

Write-Host '---------------------------------------------'
Write-Host ' 当前 DNS 解析 github.com：'
try {
  $ips = (Resolve-DnsName github.com -Type A -ErrorAction Stop |
          Where-Object { $_.IPAddress }).IPAddress -join ', '
  Write-Host ("   " + $ips)
} catch { Write-Host '   解析失败' }
Write-Host '---------------------------------------------'

$text = Get-Content -LiteralPath $Hosts -Raw
$hasBlock = $text -like "*$Begin*"

function Show-Dry {
  Write-Host "[dry-run] 将写入 $Hosts ："
  Write-Host "    $Begin"
  $Domains | ForEach-Object { Write-Host ("    {0,-16} {1}" -f $Ip, $_) }
  Write-Host "    $End"
  Write-Host '[dry-run] 之后执行 ipconfig /flushdns'
}

function Test-Host([string]$Host_) {
  try {
    $r = Invoke-WebRequest -Uri "https://$Host_" -Method Head -TimeoutSec 15 -UseBasicParsing
    Write-Host ("   https://{0,-16} OK {1}" -f $Host_, $r.StatusCode) -ForegroundColor Green
    return $true
  } catch {
    Write-Host ("   https://{0,-16} 失败: {1}" -f $Host_, $_.Exception.Message) -ForegroundColor Red
    return $false
  }
}

if ($Mode -eq 'dry') { Show-Dry; exit 0 }

if ($Mode -eq 'revert') {
  if (-not $hasBlock) { Write-Host '没有找到本工具写入的段落，无需还原。'; exit 0 }
  Copy-Item -LiteralPath $Hosts -Destination "$Hosts.ojbak2" -Force
  $pattern = "(?s)\r?\n?# === OJ github hosts fix \(begin\) ===.*?# === OJ github hosts fix \(end\) ===\r?\n?"
  $new = [regex]::Replace($text, $pattern, "`r`n")
  Set-Content -LiteralPath $Hosts -Value $new -Encoding ASCII -NoNewline
  Write-Host '已删除修复段落。' -ForegroundColor Green
  ipconfig /flushdns | Out-Null
  Test-Host 'github.com' | Out-Null
  exit 0
}

if ($hasBlock) {
  Write-Host '已经修复过，跳过写入。' -ForegroundColor Yellow
} else {
  Copy-Item -LiteralPath $Hosts -Destination "$Hosts.ojbak" -Force
  Write-Host ("已备份 -> {0}.ojbak" -f $Hosts)
  $block = "`r`n$Begin`r`n" + (($Domains | ForEach-Object { "$Ip $_" }) -join "`r`n") + "`r`n$End`r`n"
  Set-Content -LiteralPath $Hosts -Value ($text.TrimEnd() + "`r`n" + $block) -Encoding ASCII
  Write-Host '已写入 hosts：' -ForegroundColor Green
  $Domains | ForEach-Object { Write-Host ("    {0,-16} {1}" -f $Ip, $_) }
}

ipconfig /flushdns | Out-Null
Start-Sleep -Seconds 1
Write-Host ''
Write-Host '验证：'
$ok = $true
foreach ($d in $Domains) { if (-not (Test-Host $d)) { $ok = $false } }
Write-Host ''
if ($ok) {
  Write-Host '修复完成：现在可以直接打开 https://github.com 了。' -ForegroundColor Green
} else {
  Write-Host '仍不通：可能是该 IP 也被临时阻断，换一个 IP 试试：' -ForegroundColor Yellow
  Write-Host '  140.82.113.3 github.com'
  Write-Host '也可以改用本机代理： python tools\github_proxy.py'
}
Write-Host '还原命令： fix_hosts_admin.cmd revert'
