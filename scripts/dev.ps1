<#
.SYNOPSIS
  Starts the agent runtime sidecar and the API for local development.

.DESCRIPTION
  Reads backend/.env so both processes see the same gateway credentials and
  shared token. Logs land in .logs/ at the repository root. Run stop-dev.ps1
  to shut both down.

  Keep this file ASCII-only: Windows PowerShell 5.1 reads scripts using the
  system ANSI code page, and UTF-8 text breaks the parser on CJK locales.
#>
[CmdletBinding()]
param(
  [int]$ApiPort = 8000,
  [int]$RuntimePort = 8721
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$logs = Join-Path $root '.logs'
New-Item -ItemType Directory -Force -Path $logs | Out-Null

$envFile = Join-Path $root 'backend\.env'
if (-not (Test-Path $envFile)) {
  throw 'Missing backend\.env. Copy .env.example and fill in the gateway key.'
}

$settings = @{}
foreach ($line in Get-Content $envFile) {
  if ($line -match '^\s*#' -or $line -notmatch '=') { continue }
  $pair = $line -split '=', 2
  $settings[$pair[0].Trim()] = $pair[1].Trim()
}

# Validate before stopping an existing local process. Never print credentials.
foreach ($name in @('ATOM_SECRET', 'ATOM_RUNTIME_TOKEN')) {
  $value = $settings[$name]
  if ($value -notmatch '^[\x21-\x7e]{32,512}$' -or $value -match 'change-me|dev-secret') {
    throw "$name must contain a generated 32-512 character secret. See docs/configuration.md."
  }
}
if ($settings['ATOM_SECRET'] -eq $settings['ATOM_RUNTIME_TOKEN']) {
  throw 'Session and runtime credentials must differ.'
}

function Stop-Port([int]$port) {
  Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
}

Stop-Port $RuntimePort
Stop-Port $ApiPort

$runtimeDir = Join-Path $root 'runtime'
$env:ATOM_RUNTIME_PORT = $RuntimePort
$env:ATOM_RUNTIME_TOKEN = $settings['ATOM_RUNTIME_TOKEN']
$env:ATOM_ENVIRONMENT = if ($settings['ATOM_ENVIRONMENT']) { $settings['ATOM_ENVIRONMENT'] } else { 'development' }
$env:WORKDUDE_PI_CACHE_REPOSITORY_ROOT = $runtimeDir

$sidecar = Start-Process -FilePath 'node' `
  -ArgumentList '--import', 'tsx', 'src/server.ts' `
  -WorkingDirectory $runtimeDir `
  -WindowStyle Hidden -PassThru `
  -RedirectStandardOutput (Join-Path $logs 'runtime.log') `
  -RedirectStandardError (Join-Path $logs 'runtime.err.log')

$api = Start-Process -FilePath 'uv' `
  -ArgumentList 'run', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', $ApiPort `
  -WorkingDirectory (Join-Path $root 'backend') `
  -WindowStyle Hidden -PassThru `
  -RedirectStandardOutput (Join-Path $logs 'api.log') `
  -RedirectStandardError (Join-Path $logs 'api.err.log')

Set-Content -Path (Join-Path $logs 'pids.txt') -Value @($sidecar.Id, $api.Id)

Write-Host ('runtime pid {0}  ->  http://127.0.0.1:{1}' -f $sidecar.Id, $RuntimePort)
Write-Host ('api     pid {0}  ->  http://127.0.0.1:{1}' -f $api.Id, $ApiPort)
Write-Host ('logs in {0}' -f $logs)
