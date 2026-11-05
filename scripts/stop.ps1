# 停止 SciLoom（释放 8000 / 3000）
# 用法：& .\scripts\stop.ps1

foreach ($port in 8000, 3000) {
    $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if (-not $conns) {
        Write-Host "[skip] 端口 $port 未被占用"
        continue
    }
    foreach ($c in $conns) {
        $proc = Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue
        if ($proc) {
            Stop-Process -Id $proc.Id -Force
            Write-Host "[stop] $($proc.ProcessName) (PID $($proc.Id)) -> 释放端口 $port"
        }
    }
}
Start-Sleep -Seconds 2
Write-Host "完成。"
