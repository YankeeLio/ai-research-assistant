# 启动 SciLoom（后端 8000 + 前端 3000），日志写入 docs/
# 用法：右键"使用 PowerShell 运行"，或 & .\scripts\start.ps1

$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
$logDir = Join-Path $root "docs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

function Test-Port([int]$port) {
    return [bool](Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
}

if (Test-Port 8000) {
    Write-Host "[skip] 后端已在 8000 运行"
} else {
    $api = Join-Path $root "apps\api"
    $py = Join-Path $api ".venv\Scripts\python.exe"
    if (-not (Test-Path $py)) {
        Write-Host "[error] 未找到虚拟环境：$py" -ForegroundColor Red
        exit 1
    }
    $cmd = "cd /d `"$api`" && `"$py`" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 > `"$logDir\server.log`" 2>`"$logDir\server.err.log`""
    Start-Process -WindowStyle Hidden -FilePath "cmd.exe" -ArgumentList "/c", $cmd
    Write-Host "[start] 后端启动中（加载 BGE-M3 约需 15-20 秒）"
}

if (Test-Port 3000) {
    Write-Host "[skip] 前端已在 3000 运行"
} else {
    $web = Join-Path $root "apps\web"
    $cmd2 = "cd /d `"$web`" && npm run dev > `"$logDir\web.log`" 2>&1"
    Start-Process -WindowStyle Hidden -FilePath "cmd.exe" -ArgumentList "/c", $cmd2
    Write-Host "[start] 前端启动中"
}

$ok = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 2
    try {
        $h = Invoke-RestMethod "http://127.0.0.1:8000/api/health" -TimeoutSec 5
        Write-Host "[ok] 后端就绪：$($h.status)  模型：$($h.model)" -ForegroundColor Green
        $ok = $true
        break
    } catch { }
}
if (-not $ok) {
    Write-Host "[fail] 后端 60 秒内未就绪，请查看 docs\server.err.log" -ForegroundColor Red
    exit 1
}
Write-Host "打开 http://localhost:3000"
