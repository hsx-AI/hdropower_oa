$ErrorActionPreference='Stop'
Set-Location $PSScriptRoot
. "$PSScriptRoot/backend/env.local.ps1"
& "$PSScriptRoot/.venv/Scripts/python.exe" -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
exit $LASTEXITCODE
