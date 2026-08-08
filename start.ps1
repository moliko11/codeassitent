# ez-interview one-click launcher (PowerShell)
# start.bat is a thin wrapper that calls this file.
$ErrorActionPreference = 'SilentlyContinue'
$root = $PSScriptRoot
Set-Location $root

# ---- locate Python 3.12 ----
function Get-Python {
    param([string[]]$Candidates)
    foreach ($c in $Candidates) {
        if ([string]::IsNullOrWhiteSpace($c)) { continue }
        $code = & $c -c "import sys; sys.exit(0 if sys.version_info >= (3,12) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) { return $c }
    }
    return $null
}

$py = Get-Python @(
    $env:EZ_PYTHON, $env:PYTHON, 'python',
    (Join-Path $root '..\agent_leaning\.venv\Scripts\python.exe'),
    (Join-Path $root '.venv\Scripts\python.exe')
)
if (-not $py) {
    Write-Host "[ERROR] Python 3.12 not found. Install 3.12 or set EZ_PYTHON to python.exe"
    exit 1
}
Write-Host "[OK]   Python : $py"
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Write-Host "[WARN] node not found - npm run dev will fail"
}
if (-not (Test-Path (Join-Path $root '.env'))) {
    Write-Host "[WARN] .env missing - backend will fail to start"
}

# ---- helpers ----
function Test-Port {
    param([int]$Port)
    $hit = netstat -ano 2>$null | Select-String -Pattern (":$Port\s.*LISTENING")
    if ($hit) { Write-Host "  [BUSY]  port $Port in use" }
}

function Start-SvcWindow {
    param([string]$Title, [string]$Dir, [string]$CommandLine)
    $inner = "title $Title & cd /d `"$Dir`" & $CommandLine"
    Start-Process -FilePath 'cmd.exe' -ArgumentList '/k', $inner | Out-Null
    Write-Host "  [start] $Title"
}

function Start-Web {
    Test-Port 8000
    Start-SvcWindow 'Web backend :8000' $root "`"$py`" -m chatweb.backend.server"
    Test-Port 3000
    Start-SvcWindow 'Web frontend :3000' (Join-Path $root 'chatweb\frontend') 'npm run dev'
}

function Start-Monitor {
    Test-Port 8002
    Start-SvcWindow 'Monitor backend :8002' $root "`"$py`" -m monitor.backend.server"
    Test-Port 5173
    Start-SvcWindow 'Monitor frontend :5173' (Join-Path $root 'monitor\frontend') 'npm run dev'
}

function Start-Desktop {
    if (-not (Test-Path (Join-Path $root 'chatweb\frontend\out\index.html'))) {
        Write-Host "  [WARN] Desktop needs the frontend build. Run first:"
        Write-Host "         cd chatweb\frontend; npm run build"
    }
    Test-Port 8000
    Start-SvcWindow 'Desktop app :4173' (Join-Path $root 'desktop') 'npm start'
}

function Start-Repl {
    Start-SvcWindow 'Agent REPL' $root "`"$py`" -m agent.agentloop"
}

function Show-Check {
    Write-Host ""
    Write-Host "  ---- Environment check ----"
    Write-Host "  Python  : $py"
    $nodeVer = (& node -v 2>$null)
    if ($nodeVer) { Write-Host "  node    : $nodeVer" } else { Write-Host "  node    : not found" }
    if (Test-Path (Join-Path $root '.env')) { Write-Host "  .env    : present" } else { Write-Host "  .env    : MISSING" }
    if (Test-Path (Join-Path $root 'chatweb\frontend\out\index.html')) {
        Write-Host "  frontend: built"
    } else {
        Write-Host "  frontend: NOT built - desktop needs it"
    }
    Write-Host "  Ports in use:"
    Test-Port 8000
    Test-Port 3000
    Test-Port 8002
    Test-Port 5173
    Test-Port 4173
}

# ---- dispatch ----
$action = $args[0]
if (-not $action) {
    Write-Host ""
    Write-Host "  ez-interview one-click launcher"
    Write-Host "  [1] Web       backend :8000 + frontend :3000"
    Write-Host "  [2] Monitor   backend :8002 + frontend :5173"
    Write-Host "  [3] Desktop   auto backend :8000 + static :4173"
    Write-Host "  [4] Agent REPL   (TUI, no port)"
    Write-Host "  [a] All       1 + 2 + 3 + 4"
    Write-Host "  [c] Check     env / port status, no start"
    Write-Host "  [0] Exit"
    Write-Host ""
    $choice = Read-Host "Choice (Enter = 1)"
    if ([string]::IsNullOrWhiteSpace($choice)) { $choice = '1' }
    $action = $choice
}

$started = $false
switch ($action.ToLower()) {
    'web'      { Start-Web; $started = $true; break }
    'monitor'  { Start-Monitor; $started = $true; break }
    'desktop'  { Start-Desktop; $started = $true; break }
    'repl'     { Start-Repl; $started = $true; break }
    'all'      { Start-Web; Start-Monitor; Start-Desktop; Start-Repl; $started = $true; break }
    'a'        { Start-Web; Start-Monitor; Start-Desktop; Start-Repl; $started = $true; break }
    'check'    { Show-Check; break }
    '0'        { exit 0 }
    default    { Write-Host "[ERROR] Unknown action '$action'. Use: web | monitor | desktop | repl | all | check" }
}

if ($started) {
    Write-Host ""
    Write-Host "  --------------------------------------------------"
    Write-Host "  Started. Each service runs in its own window."
    Write-Host "  Closing a window stops that service."
    Write-Host "    Web     : http://localhost:3000   (backend :8000)"
    Write-Host "    Monitor : http://localhost:5173   (backend :8002)"
    Write-Host "    Desktop : http://127.0.0.1:4173   (backend :8000)"
    Write-Host "    REPL    : its own window"
    Write-Host "  --------------------------------------------------"
    Read-Host "Press Enter to close this launcher"
}
