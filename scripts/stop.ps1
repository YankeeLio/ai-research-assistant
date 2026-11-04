# 停止 SciLoom（释放 8000 / 3000）
# 用法：powershell -ExecutionPolicy Bypass -File scripts\stop.ps1

foreach ($port in 8000, 3000) {
    $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if (-not $conns) {
        Write-Host "端口 $port 未被占用" -ForegroundColor DarkGray
        continue
    }
    foreach ($c in $conns) {
        $proc = Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue
        if ($proc) {
            Stop-Process -Id $proc.Id -Force
            Write-Host "已停止 $($proc.ProcessName) (PID $($proc.Id))，释放端口 $port" -ForegroundColor Green
        }
    }
}

# 索引与数据库可能正在写盘，留出缓冲时间再退出
Start-Sleep -Seconds 2
Write-Host "完成。"
