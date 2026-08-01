# 仅用于周末或节假日测试，不得用于正式定时任务

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$proxy = "http://127.0.0.1:7897"
$PythonPath = $env:DAILY_STOCK_PYTHON
if ([string]::IsNullOrWhiteSpace($PythonPath)) {
    $PythonPath = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
}
$MainScript = Join-Path $ProjectRoot "main.py"
$stocks = "002714,300498,000876,605296,159867"
$logDirectory = Join-Path $ProjectRoot "logs"
$startedAt = Get-Date
$stopwatch = [System.Diagnostics.Stopwatch]::StartNew()

Set-Location $ProjectRoot

New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
Get-ChildItem -LiteralPath $logDirectory -Filter "*.log" -File -ErrorAction SilentlyContinue |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-30) } |
    Remove-Item -Force

$logPath = Join-Path $logDirectory ("run_weekend_test_{0}.log" -f $startedAt.ToString("yyyyMMdd_HHmmss"))

function Write-RunLog {
    param([string]$Message)

    $Message | Tee-Object -FilePath $logPath -Append
}

$proxyHost = "127.0.0.1"
$proxyPort = 7897
$proxyCheckIntervalSeconds = 15
$proxyMaxWaitSeconds = 600
$proxyFailureExitCode = 2
$proxyReadyMessage = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("Q2xhc2gg5Luj55CG5bey5bCx57uq"))
$proxyWaitingMessage = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("5q2j5Zyo562J5b6FIENsYXNoIOS7o+eQhuerr+WPoyA3ODk3IOWwsee7qg=="))
$proxyTimeoutMessage = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("Q2xhc2gg5Luj55CG56uv5Y+jIDc4OTcg5pyq5bCx57uq77yM5pys5qyh5Y+W5raI6L+Q6KGM"))

$env:HTTP_PROXY = $proxy
$env:HTTPS_PROXY = $proxy
$env:ALL_PROXY = $proxy
$env:http_proxy = $proxy
$env:https_proxy = $proxy
$env:all_proxy = $proxy

Write-RunLog ("Script start time: {0}" -f $startedAt.ToString("yyyy-MM-dd HH:mm:ss"))
Write-RunLog "Run type: weekend test"

$proxyReady = $false
$waitedSeconds = 0
while ($waitedSeconds -lt $proxyMaxWaitSeconds) {
    if (Test-NetConnection $proxyHost -Port $proxyPort -InformationLevel Quiet) {
        $proxyReady = $true
        Write-RunLog $proxyReadyMessage
        break
    }

    Write-RunLog ("{0} (elapsed: {1}/{2} seconds)" -f $proxyWaitingMessage, $waitedSeconds, $proxyMaxWaitSeconds)
    Start-Sleep -Seconds $proxyCheckIntervalSeconds
    $waitedSeconds += $proxyCheckIntervalSeconds
}

if (-not $proxyReady) {
    Write-RunLog $proxyTimeoutMessage
    Write-RunLog ("Script exit code: {0}" -f $proxyFailureExitCode)
    $stopwatch.Stop()
    $endedAt = Get-Date
    Write-RunLog ("Script end time: {0}" -f $endedAt.ToString("yyyy-MM-dd HH:mm:ss"))
    Write-RunLog ("Total duration: {0:N2} seconds" -f $stopwatch.Elapsed.TotalSeconds)
    exit $proxyFailureExitCode
}

& $PythonPath $MainScript `
    --stocks $stocks `
    --no-market-review `
    --force-run `
    --no-notify 2>&1 |
    Tee-Object -FilePath $logPath -Append

$pythonExitCode = $LASTEXITCODE
$stopwatch.Stop()
$endedAt = Get-Date

Write-RunLog ("Python exit code: {0}" -f $pythonExitCode)
Write-RunLog ("Script end time: {0}" -f $endedAt.ToString("yyyy-MM-dd HH:mm:ss"))
Write-RunLog ("Total duration: {0:N2} seconds" -f $stopwatch.Elapsed.TotalSeconds)

exit $pythonExitCode
