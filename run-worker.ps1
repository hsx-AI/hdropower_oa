$ErrorActionPreference='Stop'
Set-Location $PSScriptRoot
. "$PSScriptRoot/backend/env.local.ps1"
& "$PSScriptRoot/.venv/Scripts/python.exe" -m backend.sync worker
exit $LASTEXITCODE
