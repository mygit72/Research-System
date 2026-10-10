# Starts backend (:8000) and frontend (:5173) for local development on Windows.
# Usage: powershell -ExecutionPolicy Bypass -File scripts/dev.ps1
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root 'backend'
$frontend = Join-Path $root 'frontend'

if (-not (Test-Path (Join-Path $backend '.venv'))) {
    Write-Host 'Creating Python virtual environment...'
    python -m venv (Join-Path $backend '.venv')
    & (Join-Path $backend '.venv\Scripts\python.exe') -m pip install -e "${backend}[dev,worker]"
}
if (-not (Test-Path (Join-Path $frontend 'node_modules'))) {
    Push-Location $frontend; npm install; Pop-Location
}

Push-Location $backend
& .\.venv\Scripts\alembic.exe upgrade head
Pop-Location

$api = Start-Process -PassThru -NoNewWindow -WorkingDirectory $backend `
    -FilePath (Join-Path $backend '.venv\Scripts\python.exe') `
    -ArgumentList '-m', 'uvicorn', 'app.main:app', '--reload', '--port', '8000'
try {
    Push-Location $frontend
    npm run dev
} finally {
    Pop-Location
    Stop-Process -Id $api.Id -ErrorAction SilentlyContinue
}
