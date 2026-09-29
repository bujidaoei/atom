param(
  [Parameter(Mandatory = $true)]
  [string]$SetupPath,
  [Parameter(Mandatory = $true)]
  [string]$PackageRoot,
  [Parameter(Mandatory = $true)]
  [string]$HealthUserDataPath,
  [Parameter(Mandatory = $true)]
  [string]$OutputPath,
  [Parameter(Mandatory = $true)]
  [ValidatePattern('^[0-9a-fA-F]{64}$')]
  [string]$ExpectedSetupSha256,
  [switch]$Launch
)

$ErrorActionPreference = 'Stop'
$localAppData = [Environment]::GetFolderPath([Environment+SpecialFolder]::LocalApplicationData)
$installRoot = Join-Path $localAppData 'qoderwake'
$applicationRoot = Join-Path $installRoot 'app-0.1.0-beta25'
$uninstallKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\qoderwake'
$nativeRegistryKey = 'HKCU:\Software\Google\Chrome\NativeMessagingHosts\com.workdude.browser_connector'
$setup = [IO.Path]::GetFullPath($SetupPath)
$package = [IO.Path]::GetFullPath($PackageRoot)
$healthUserData = [IO.Path]::GetFullPath($HealthUserDataPath)
$output = [IO.Path]::GetFullPath($OutputPath)
$localAppDataRoot = [IO.Path]::GetFullPath($localAppData).TrimEnd('\') + '\'
if (-not $installRoot.StartsWith($localAppDataRoot, [StringComparison]::OrdinalIgnoreCase) -or
    (Split-Path -Leaf $installRoot) -ne 'qoderwake') {
  throw 'Candidate install root failed the LocalAppData safety boundary.'
}
$allowedHealthRoot = [IO.Path]::GetFullPath((Join-Path (Split-Path -Parent $output) '.'))
if (-not $healthUserData.StartsWith($allowedHealthRoot, [StringComparison]::OrdinalIgnoreCase)) {
  throw 'Health user-data path escaped the owned output directory.'
}
if (-not (Test-Path -LiteralPath $setup -PathType Leaf)) { throw 'Current Setup is missing.' }
if (-not (Test-Path -LiteralPath $package -PathType Container)) { throw 'Current package root is missing.' }
$expectedSetupHash = $ExpectedSetupSha256.ToUpperInvariant()

trap {
  $failureParent = Split-Path -Parent $output
  if ($failureParent) { New-Item -ItemType Directory -Path $failureParent -Force | Out-Null }
  [ordered]@{
    failedAtUtc = [DateTime]::UtcNow.ToString('o')
    message = $_.Exception.Message
    category = [string]$_.CategoryInfo
    scriptStackTrace = $_.ScriptStackTrace
  } | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath "$output.failure.json" -Encoding UTF8
  exit 1
}

function Snapshot-File([string]$Path) {
  if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
  $item = Get-Item -LiteralPath $Path
  return [ordered]@{
    path = $item.FullName
    length = $item.Length
    sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash
  }
}

function Get-CandidateProcesses {
  return @(
    Get-CimInstance Win32_Process |
      Where-Object {
        $_.ExecutablePath -and
        $_.ExecutablePath.StartsWith($installRoot, [StringComparison]::OrdinalIgnoreCase)
      }
  )
}

function Invoke-Process([string]$FilePath, [string[]]$Arguments, [int]$TimeoutSeconds) {
  $process = Start-Process -FilePath $FilePath -ArgumentList $Arguments -WindowStyle Hidden -PassThru
  if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
    Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
    throw "Process timed out: $FilePath"
  }
  return $process.ExitCode
}

$setupBeforeInstall = Snapshot-File $setup
if ($setupBeforeInstall.sha256 -ne $expectedSetupHash) { throw 'Current Setup SHA256 does not match the staged release manifest.' }

$result = [ordered]@{
  startedAtUtc = [DateTime]::UtcNow.ToString('o')
  user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
  localAppData = $localAppData
  staleUninstallRemoved = $false
  previousUninstallExitCode = $null
  previousProcessesStopped = $false
  previousUninstallRegistrationRemoved = $false
  previousApplicationRemoved = $false
  previousInstallRootRemoved = $false
  setupExitCode = $null
  setupIdentity = $setupBeforeInstall
  healthStayedRunning = $false
  healthRegistryCleanup = 'pending'
  nativeRegistryAbsent = $false
  launched = $false
  launchedProcess = $null
}

$existingProcesses = Get-CandidateProcesses
if ($existingProcesses.Count -gt 0) { throw 'Existing candidate QoderWake processes must be stopped before replacement.' }

$previousInstallRootPresent = Test-Path -LiteralPath $installRoot -PathType Container
$previousUninstallPresent = Test-Path -LiteralPath $uninstallKey
if ($previousInstallRootPresent -and -not $previousUninstallPresent) {
  $knownCandidateMarkers = @(
    (Join-Path $installRoot 'Update.exe'),
    (Join-Path $installRoot 'QoderWake.exe'),
    (Join-Path $applicationRoot 'QoderWake.exe')
  ) | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf }
  if ($knownCandidateMarkers.Count -eq 0) {
    throw 'Refusing to clean an unregistered install root without a QoderWake product marker.'
  }
}

if ($previousUninstallPresent) {
  $uninstall = Get-ItemProperty -LiteralPath $uninstallKey
  if ($uninstall.DisplayName -ne 'QoderWake' -or
      -not ([string]$uninstall.InstallLocation).Equals($installRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Refusing to replace an unexpected uninstall registration.'
  }
  $updater = Join-Path $installRoot 'Update.exe'
  if (Test-Path -LiteralPath $updater -PathType Leaf) {
    $result.previousUninstallExitCode = Invoke-Process $updater @('--uninstall', '-s') 60
    if ($result.previousUninstallExitCode -ne 0) { throw 'Existing candidate uninstall failed.' }
  } else {
    Remove-Item -LiteralPath $uninstallKey -Force
    $result.staleUninstallRemoved = $true
  }
}

if ($previousInstallRootPresent -or $previousUninstallPresent) {
  $uninstallDeadline = [DateTime]::UtcNow.AddSeconds(30)
  do {
    $remainingProcesses = Get-CandidateProcesses
    $uninstallRegistrationPresent = Test-Path -LiteralPath $uninstallKey
    if ($remainingProcesses.Count -eq 0 -and -not $uninstallRegistrationPresent) { break }
    Start-Sleep -Milliseconds 500
  } while ([DateTime]::UtcNow -lt $uninstallDeadline)
  if ($remainingProcesses.Count -gt 0) { throw 'Existing candidate processes remained after uninstall.' }
  if ($uninstallRegistrationPresent) { throw 'Existing candidate uninstall registration remained after uninstall.' }

  if (Test-Path -LiteralPath $installRoot -PathType Container) {
    Remove-Item -LiteralPath $installRoot -Recurse -Force
  }
  if (Test-Path -LiteralPath $installRoot) { throw 'Existing candidate install root remained after cleanup.' }
  $result.previousProcessesStopped = $true
  $result.previousUninstallRegistrationRemoved = $true
  $result.previousApplicationRemoved = $true
  $result.previousInstallRootRemoved = $true
}

$result.setupExitCode = Invoke-Process $setup @('--silent') 120
if ($result.setupExitCode -ne 0) { throw 'Current Setup failed.' }
$setupAfterInstall = Snapshot-File $setup
if ($setupAfterInstall.sha256 -ne $expectedSetupHash -or
    $setupAfterInstall.length -ne $setupBeforeInstall.length) {
  throw 'Current Setup identity changed during installation.'
}
if (-not (Test-Path -LiteralPath $uninstallKey)) { throw 'Current Setup did not register uninstall metadata.' }

$filePairs = @(
  [ordered]@{ name = 'QoderWake.exe'; installed = Join-Path $applicationRoot 'QoderWake.exe'; current = Join-Path $package 'QoderWake.exe' },
  [ordered]@{ name = 'app.asar'; installed = Join-Path $applicationRoot 'resources\app.asar'; current = Join-Path $package 'resources\app.asar' },
  [ordered]@{ name = 'NativeHost'; installed = Join-Path $applicationRoot 'resources\QoderWakeBrowserNativeHost.exe'; current = Join-Path $package 'resources\QoderWakeBrowserNativeHost.exe' },
  [ordered]@{ name = 'UninstallCleanup'; installed = Join-Path $applicationRoot 'resources\QoderWakeUninstallCleanup.exe'; current = Join-Path $package 'resources\QoderWakeUninstallCleanup.exe' }
)
$identities = @()
foreach ($pair in $filePairs) {
  $installed = Snapshot-File $pair.installed
  $current = Snapshot-File $pair.current
  if ($null -eq $installed -or $null -eq $current -or $installed.sha256 -ne $current.sha256) {
    throw "Installed $($pair.name) does not match the current package."
  }
  $identities += [ordered]@{ name = $pair.name; installed = $installed; current = $current; match = $true }
}
$result.identities = $identities

New-Item -ItemType Directory -Path $healthUserData -Force | Out-Null
$healthOut = Join-Path $healthUserData 'health.stdout.log'
$healthErr = Join-Path $healthUserData 'health.stderr.log'
$oldLogging = $env:ELECTRON_ENABLE_LOGGING
$oldAutomation = $env:WORKDUDE_AUTOMATION_WINDOW
try {
  $env:ELECTRON_ENABLE_LOGGING = '1'
  $env:WORKDUDE_AUTOMATION_WINDOW = 'hidden'
  $health = Start-Process -FilePath (Join-Path $applicationRoot 'QoderWake.exe') `
    -ArgumentList @("--user-data-dir=$healthUserData") `
    -RedirectStandardOutput $healthOut -RedirectStandardError $healthErr `
    -WindowStyle Hidden -PassThru
  if ($health.WaitForExit(15000)) {
    throw "Installed application exited during health window with code $($health.ExitCode)."
  }
  $result.healthStayedRunning = $true
  Stop-Process -Id $health.Id -Force -ErrorAction SilentlyContinue
  $health.WaitForExit(10000) | Out-Null

  if (Test-Path -LiteralPath $nativeRegistryKey) {
    $nativeRegistration = Get-Item -LiteralPath $nativeRegistryKey
    $registeredManifest = [string](Get-ItemProperty -LiteralPath $nativeRegistryKey).'(default)'
    $expectedManifest = Join-Path $healthUserData 'browser-connector-native-host.json'
    if ($nativeRegistration.SubKeyCount -ne 0 -or
        $nativeRegistration.ValueCount -ne 1 -or
        -not $registeredManifest.Equals($expectedManifest, [StringComparison]::OrdinalIgnoreCase)) {
      throw 'Installed health Browser Native registration is not the exact verifier-owned value.'
    }
    Remove-Item -LiteralPath $nativeRegistryKey -Force
    $result.healthRegistryCleanup = 'removed-exact-verifier-value'
  } else {
    $result.healthRegistryCleanup = 'already-absent'
  }
} finally {
  $env:ELECTRON_ENABLE_LOGGING = $oldLogging
  $env:WORKDUDE_AUTOMATION_WINDOW = $oldAutomation
}

$result.nativeRegistryAbsent = -not (Test-Path -LiteralPath $nativeRegistryKey)
if (-not $result.nativeRegistryAbsent) { throw 'Browser Native registry residue remains after health cleanup.' }
$stdoutText = if (Test-Path -LiteralPath $healthOut) { Get-Content -Raw -LiteralPath $healthOut } else { '' }
$stderrText = if (Test-Path -LiteralPath $healthErr) { Get-Content -Raw -LiteralPath $healthErr } else { '' }
$result.healthStdout = $stdoutText.Substring(0, [Math]::Min(4000, $stdoutText.Length))
$result.healthStderr = $stderrText.Substring(0, [Math]::Min(4000, $stderrText.Length))

if ($Launch) {
  if ((Get-CandidateProcesses).Count -gt 0) {
    throw 'Candidate processes appeared before the default-profile launch verification.'
  }
  $installedExecutable = Join-Path $applicationRoot 'QoderWake.exe'
  Start-Process -FilePath (Join-Path $installRoot 'QoderWake.exe') | Out-Null

  $launchDeadline = [DateTime]::UtcNow.AddSeconds(15)
  $launchedProcess = $null
  do {
    $launchedProcess = Get-CandidateProcesses |
      Where-Object {
        $_.ExecutablePath.Equals($installedExecutable, [StringComparison]::OrdinalIgnoreCase) -and
        ([string]$_.CommandLine).IndexOf('--type=', [StringComparison]::OrdinalIgnoreCase) -lt 0
      } |
      Select-Object -First 1
    if ($null -ne $launchedProcess) { break }
    Start-Sleep -Milliseconds 250
  } while ([DateTime]::UtcNow -lt $launchDeadline)
  if ($null -eq $launchedProcess) { throw 'Installed application did not start with the default user profile.' }

  $stableProcessId = [int]$launchedProcess.ProcessId
  $stableStartedAt = [string]$launchedProcess.CreationDate
  $windowDeadline = [DateTime]::UtcNow.AddSeconds(15)
  $desktopWindow = $null
  do {
    $desktopWindow = Get-Process -Id $stableProcessId -ErrorAction SilentlyContinue
    if ($null -eq $desktopWindow) { break }
    if ($desktopWindow.MainWindowHandle -ne 0 -and $desktopWindow.MainWindowTitle -eq 'QoderWake' -and $desktopWindow.Responding) {
      break
    }
    Start-Sleep -Milliseconds 250
  } while ([DateTime]::UtcNow -lt $windowDeadline)
  if ($null -eq $desktopWindow) { throw 'Installed application exited before exposing its product window.' }
  if ($desktopWindow.MainWindowHandle -eq 0 -or $desktopWindow.MainWindowTitle -ne 'QoderWake' -or -not $desktopWindow.Responding) {
    throw "Installed application exposed an invalid main window: '$($desktopWindow.MainWindowTitle)'."
  }
  $stabilityDeadline = [DateTime]::UtcNow.AddSeconds(15)
  do {
    Start-Sleep -Milliseconds 500
    $sameProcess = Get-CandidateProcesses |
      Where-Object {
        [int]$_.ProcessId -eq $stableProcessId -and
        [string]$_.CreationDate -eq $stableStartedAt -and
        $_.ExecutablePath.Equals($installedExecutable, [StringComparison]::OrdinalIgnoreCase)
      } |
      Select-Object -First 1
    if ($null -eq $sameProcess) { throw 'Installed application exited during the default-profile stability window.' }
    $sameWindow = Get-Process -Id $stableProcessId -ErrorAction SilentlyContinue
    if ($null -eq $sameWindow -or $sameWindow.MainWindowTitle -ne 'QoderWake' -or -not $sameWindow.Responding) {
      throw 'Installed application product window did not remain stable.'
    }
  } while ([DateTime]::UtcNow -lt $stabilityDeadline)

  $result.launched = $true
  $result.launchedProcess = [ordered]@{
    processId = $stableProcessId
    creationDate = $stableStartedAt
    executablePath = $installedExecutable
    mainWindowTitle = $desktopWindow.MainWindowTitle
    mainWindowHandle = [int64]$desktopWindow.MainWindowHandle
    stableForSeconds = 15
  }
}
$result.completedAtUtc = [DateTime]::UtcNow.ToString('o')

$outputParent = Split-Path -Parent $output
if ($outputParent) { New-Item -ItemType Directory -Path $outputParent -Force | Out-Null }
$result | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $output -Encoding UTF8
