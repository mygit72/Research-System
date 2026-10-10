# Run Research Intelligence on your own computer, with a local model (Windows).
#
#   powershell -ExecutionPolicy Bypass -File scripts\run-local.ps1                 # default model
#   powershell -ExecutionPolicy Bypass -File scripts\run-local.ps1 -Model llama3.2:3b
#   powershell -ExecutionPolicy Bypass -File scripts\run-local.ps1 -CheckOnly      # check, change nothing
#
# What it does: checks Python 3.12+, Node 20+ and Ollama; the first time, writes backend\.env
# (your model, local models allowed, a random secret) and installs everything; pulls the model
# into Ollama; then starts the app at http://localhost:5173. Everything stays on this computer.
# Any model you pull later (ollama pull <name>) can be chosen in Settings -> AI.
param(
    [string]$Model = 'qwen2.5:3b',
    [switch]$CheckOnly,
    [switch]$NoML  # skip PyTorch + embedding models (~1 GB); search then falls back to keywords
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root 'backend'
$frontend = Join-Path $root 'frontend'
$envFile = Join-Path $backend '.env'

function Find-Command($name) { $c = Get-Command $name -ErrorAction SilentlyContinue; if ($c) { $c.Source } }

function Get-Version($exe, $arg) {
    try { $out = & $exe $arg 2>&1 | Out-String } catch { return $null }
    if ($out -match '(\d+)\.(\d+)') { return [version]"$($Matches[1]).$($Matches[2])" }
    return $null
}

$problems = @()
$python = Find-Command 'python'
$pyVersion = if ($python) { Get-Version $python '--version' } else { $null }
if (-not $pyVersion -or $pyVersion -lt [version]'3.12') {
    $problems += 'Python 3.12 or newer: https://www.python.org/downloads/ (tick "Add python.exe to PATH")'
}
$node = Find-Command 'node'
$nodeVersion = if ($node) { Get-Version $node '--version' } else { $null }
if (-not $nodeVersion -or $nodeVersion -lt [version]'20.0') {
    $problems += 'Node.js 20 or newer: https://nodejs.org/'
}
$ollama = Find-Command 'ollama'
if (-not $ollama) {
    $guess = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'
    if (Test-Path $guess) { $ollama = $guess }
}

Write-Host ''
Write-Host 'Research Intelligence - local install' -ForegroundColor Cyan
Write-Host ("  Python : {0}" -f $(if ($pyVersion) { $pyVersion } else { 'missing' }))
Write-Host ("  Node   : {0}" -f $(if ($nodeVersion) { $nodeVersion } else { 'missing' }))
Write-Host ("  Ollama : {0}" -f $(if ($ollama) { 'found' } else { 'missing (optional: you can use an API key in Settings -> AI instead)' }))
Write-Host ("  Model  : {0}" -f $Model)
if ($problems.Count -gt 0) {
    Write-Host ''
    Write-Host 'Install these first, then run this script again:' -ForegroundColor Yellow
    $problems | ForEach-Object { Write-Host "  - $_" }
    exit 1
}
if ($CheckOnly) {
    Write-Host ''
    Write-Host 'Everything needed is installed. Run again without -CheckOnly to install and start.'
    exit 0
}

# --- first run: settings ------------------------------------------------------------------------
if (-not (Test-Path $envFile)) {
    $bytes = New-Object byte[] 48
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $secret = [Convert]::ToBase64String($bytes)
    $lines = @(
        '# Written by scripts/run-local.ps1 for a private install on this computer.',
        'LLM_PROVIDER=ollama',
        "LLM_MODEL=$Model",
        'OLLAMA_BASE_URL=http://127.0.0.1:11434',
        'ALLOW_LOCAL_MODELS=true',
        "JWT_SECRET=$secret"
    )
    # UTF-8 without a byte-order mark (Set-Content -Encoding utf8 adds one in Windows PowerShell).
    [IO.File]::WriteAllLines($envFile, [string[]]$lines, (New-Object Text.UTF8Encoding $false))
    Write-Host "Wrote $envFile"
} else {
    Write-Host "Keeping your existing $envFile"
}

# --- first run: install -------------------------------------------------------------------------
$venvPython = Join-Path $backend '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPython)) {
    Write-Host 'Installing the backend (a few minutes the first time)...'
    & $python -m venv (Join-Path $backend '.venv')
    & $venvPython -m pip install --upgrade pip
    if (-not $NoML) {
        & $venvPython -m pip install torch --index-url https://download.pytorch.org/whl/cpu
        & $venvPython -m pip install -e "${backend}[worker,ml]"
    } else {
        & $venvPython -m pip install -e "${backend}[worker]"
    }
}
if (-not (Test-Path (Join-Path $frontend 'node_modules'))) {
    Write-Host 'Installing the frontend...'
    Push-Location $frontend; npm install; Pop-Location
}

# --- the model ----------------------------------------------------------------------------------
function Get-OllamaModels {
    # Asks Ollama's API (2 s timeout) instead of `ollama list`, which can wait on a stopped server.
    # 127.0.0.1, not localhost: Windows tries IPv6 first and Ollama listens on IPv4 (a 2 s delay).
    try { return @((Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 2).models | ForEach-Object { $_.name }) }
    catch { return $null }
}
if ($ollama) {
    $models = Get-OllamaModels
    if ($null -eq $models) {
        Write-Host 'Starting Ollama...'
        Start-Process -FilePath $ollama -ArgumentList 'serve' -WindowStyle Hidden
        for ($i = 0; $i -lt 30 -and $null -eq $models; $i++) { Start-Sleep -Seconds 1; $models = Get-OllamaModels }
    }
    if ($null -eq $models) {
        Write-Host 'Ollama did not start. Start it yourself (the Ollama app), then run this again.' -ForegroundColor Yellow
    } elseif (-not ($models -contains $Model -or $models -contains "${Model}:latest")) {
        Write-Host "Downloading $Model into Ollama (once)..."
        & $ollama pull $Model
    } else {
        Write-Host "Ollama has $Model."
    }
} else {
    Write-Host 'Ollama is not installed: answers need an API key (Settings -> AI) until you install it.' -ForegroundColor Yellow
}

Write-Host ''
Write-Host 'Starting... open http://localhost:5173 and create an account (it stays on this computer).' -ForegroundColor Green
& (Join-Path $PSScriptRoot 'dev.ps1')
