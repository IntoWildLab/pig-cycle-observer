$project = "D:\daily_stock_analysis-main"
$proxy = "http://127.0.0.1:7897"
$python = "C:\Users\11941\venvs\daily_stock_analysis\Scripts\python.exe"
$stocks = "002714,300498,000876,605296,159867"

Set-Location $project

$env:HTTP_PROXY = $proxy
$env:HTTPS_PROXY = $proxy
$env:ALL_PROXY = $proxy
$env:http_proxy = $proxy
$env:https_proxy = $proxy
$env:all_proxy = $proxy

& $python main.py `
    --stocks $stocks `
    --no-market-review

exit $LASTEXITCODE
