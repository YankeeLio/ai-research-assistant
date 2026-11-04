# 启动 SciLoom（后端 8000 + 前端 3000），日志写到 docs/
# 用法：powershell -ExecutionPolicy Bypass -File scripts\start.ps1

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$logDir = Join-Path $root "docs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

function Test-Port($port) {
    return [bool](Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
}

if (Test-Port 8000) {
    Write-Host "后端已在 8000 运行，跳过启动" -ForegroundColor Yellow
} else {
    Start-Process -WindowStyle Hidden `
        -FilePath (Join-Path $root "apps\api\.venv\Scripts\python.exe") `
        -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000" `
        -WorkingDirectory (Join-Path $root "apps\api") `
        -RedirectStandardOutput (Join-Path $logDir "server.log") `
        -RedirectStandardError (Join-Path $logDir "server.err.log")
    Write-Host "后端启动中（加载 BGE-M3 约需 15 秒）..."
}

if (Test-Port 3000) {
    Write-Host "前端已在 3000 运行，跳过启动" -ForegroundColor Yellow
} else {
    Start-Process -WindowStyle Hidden `
        -FilePath "cmd.exe" `
        -ArgumentList "/c", "npm run dev > `"$logDir\web.log`" 2>&1" `
        -WorkingDirectory (Join-Path $root "apps\web")
    Write-Host "前端启动中..."
}

Start-Sleep -Seconds 18
try {
    $h = Invoke-RestMethod "http://127.0.0.1:8000/api/health" -TimeoutSec 10
    Write-Host "后端就绪: $($h.status)  模型: $($h.model)" -ForegroundColor Green
} catch {
    Write-Host "后端未就绪，请查看 docs\server.err.log" -ForegroundColor Red
}
Write-Host "打开 http://localhost:3000"
