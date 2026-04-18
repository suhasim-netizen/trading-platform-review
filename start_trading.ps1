# Start all three trading strategies as independent processes
# Each gets its own Python process with no shared memory

Write-Host "Starting trading platform..." -ForegroundColor Green

# Strategy 002 - Equity Momentum
Start-Process powershell -ArgumentList @(
    '-NoExit',
    '-Command',
    'cd C:\workspace\ClaudeCode\trading-platform; .venv\Scripts\Activate.ps1; python -m src.execution.runner --tenant director --strategy strategy_002 --mode paper --symbol AVGO,LLY,TSM,GEV'
) -WindowStyle Normal

Start-Sleep -Seconds 8

# Strategy 004 - Equity Swing  
Start-Process powershell -ArgumentList @(
    '-NoExit',
    '-Command',
    'cd C:\workspace\ClaudeCode\trading-platform; .venv\Scripts\Activate.ps1; python -m src.execution.runner --tenant director --strategy strategy_004 --mode paper --symbol LASR,LITE,COHR,SNDK,STRL'
) -WindowStyle Normal

Start-Sleep -Seconds 8

# Strategy 006 - Futures Intraday
Start-Process powershell -ArgumentList @(
    '-NoExit',
    '-Command',
    'cd C:\workspace\ClaudeCode\trading-platform; .venv\Scripts\Activate.ps1; python -m src.execution.runner --tenant director --strategy strategy_006 --mode paper --symbol "@ES,@NQ"'
) -WindowStyle Normal

Write-Host "All three strategies launched in separate windows." -ForegroundColor Green
Write-Host "Each window is independent — closing one does not affect others." -ForegroundColor Green
