param(
  [Parameter(Mandatory = $true)]
  [string]$OutputPath
)

$ErrorActionPreference = 'Stop'
$localAppData = [Environment]::GetFolderPath([Environment+SpecialFolder]::LocalApplicationData)
$root = Join-Path $localAppData 'qoderwake'
$application = Join-Path $root 'app-0.1.0-beta25'
$uninstallKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\qoderwake'

function File-Snapshot([string]$Path) {
  if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
  $item = Get-Item -LiteralPath $Path
  return [ordered]@{
    path = $item.FullName
    length = $item.Length
    sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash
    lastWriteUtc = $item.LastWriteTimeUtc.ToString('o')
  }
}

$uninstall = if (Test-Path -LiteralPath $uninstallKey) {
  $value = Get-ItemProperty -LiteralPath $uninstallKey
  [ordered]@{
    displayName = $value.DisplayName
    displayVersion = $value.DisplayVersion
    installLocation = $value.InstallLocation
    uninstallString = $value.UninstallString
  }
} else { $null }

$processes = @(
  Get-CimInstance Win32_Process |
    Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($root, [StringComparison]::OrdinalIgnoreCase) } |
    ForEach-Object {
      [ordered]@{
        processId = $_.ProcessId
        name = $_.Name
        executablePath = $_.ExecutablePath
      }
    }
)

$result = [ordered]@{
  observedAtUtc = [DateTime]::UtcNow.ToString('o')
  user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
  localAppData = $localAppData
  root = $root
  rootExists = Test-Path -LiteralPath $root -PathType Container
  deadMarker = Test-Path -LiteralPath (Join-Path $root '.dead') -PathType Leaf
  uninstall = $uninstall
  executable = File-Snapshot (Join-Path $application 'QoderWake.exe')
  appAsar = File-Snapshot (Join-Path $application 'resources\app.asar')
  nativeHost = File-Snapshot (Join-Path $application 'resources\QoderWakeBrowserNativeHost.exe')
  uninstallCleanup = File-Snapshot (Join-Path $application 'resources\QoderWakeUninstallCleanup.exe')
  processes = $processes
}

$parent = Split-Path -Parent $OutputPath
if ($parent) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
$result | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $OutputPath -Encoding UTF8
