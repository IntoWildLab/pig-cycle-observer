$project = "D:\daily_stock_analysis-main"
$proxy = "http://127.0.0.1:7897"
$python = "C:\Users\11941\venvs\daily_stock_analysis\Scripts\python.exe"
$stocks = "002714,300498,000876,605296,159867"
$logDirectory = Join-Path $project "logs"
$startedAt = Get-Date
$stopwatch = [System.Diagnostics.Stopwatch]::StartNew()

Set-Location $project

New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
Get-ChildItem -LiteralPath $logDirectory -Filter "*.log" -File -ErrorAction SilentlyContinue |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-30) } |
    Remove-Item -Force

$logPath = Join-Path $logDirectory ("run_daily_{0}.log" -f $startedAt.ToString("yyyyMMdd_HHmmss"))

function Write-RunLog {
    param([string]$Message)

    $Message | Tee-Object -FilePath $logPath -Append
}

$env:HTTP_PROXY = $proxy
$env:HTTPS_PROXY = $proxy
$env:ALL_PROXY = $proxy
$env:http_proxy = $proxy
$env:https_proxy = $proxy
$env:all_proxy = $proxy

Write-RunLog ("Script start time: {0}" -f $startedAt.ToString("yyyy-MM-dd HH:mm:ss"))
Write-RunLog "Run type: daily"

& $python main.py `
    --stocks $stocks `
    --no-market-review 2>&1 |
    Tee-Object -FilePath $logPath -Append

$pythonExitCode = $LASTEXITCODE
$stopwatch.Stop()
$endedAt = Get-Date

Write-RunLog ("Python exit code: {0}" -f $pythonExitCode)
Write-RunLog ("Script end time: {0}" -f $endedAt.ToString("yyyy-MM-dd HH:mm:ss"))
Write-RunLog ("Total duration: {0:N2} seconds" -f $stopwatch.Elapsed.TotalSeconds)

exit $pythonExitCode
