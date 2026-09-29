<#
.SYNOPSIS
  Stops whatever dev.ps1 started.
#>
$root = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $root '.logs\pids.txt'

if (Test-Path $pidFile) {
  foreach ($id in Get-Content $pidFile) {
    if ($id) { Stop-Process -Id ([int]$id) -Force -ErrorAction SilentlyContinue }
  }
  Remove-Item $pidFile -Force
}

foreach ($port in 8000, 8721) {
  Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
}

Write-Host 'stopped'
