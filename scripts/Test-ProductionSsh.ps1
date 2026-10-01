param(
    [Parameter(Mandatory = $true)][string]$Address,
    [Parameter(Mandatory = $true)][string]$InterfaceAlias,
    [string]$User = 'ubuntu',
    [ValidateRange(1, 30)][int]$Attempts = 5,
    [ValidateRange(2, 30)][int]$TimeoutSeconds = 5
)

$ErrorActionPreference = 'Stop'
$parsed = $null
if (-not [System.Net.IPAddress]::TryParse($Address, [ref]$parsed) -or
    $parsed.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork) {
    throw 'Address must be a literal IPv4 address.'
}
if ($User -notmatch '^[a-z_][a-z0-9_-]{0,31}$') {
    throw 'User is not a valid SSH account name.'
}

$adapter = Get-NetAdapter -Name $InterfaceAlias -ErrorAction Stop
if ($adapter.Status -ne 'Up' -or -not $adapter.HardwareInterface) {
    throw "Network adapter $InterfaceAlias must be an active physical interface."
}
$gateway = @(Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' -InterfaceIndex $adapter.ifIndex -ErrorAction Stop |
    Where-Object { $_.NextHop -ne '0.0.0.0' } |
    Sort-Object RouteMetric)
if ($gateway.Count -ne 1) {
    throw "Expected one default gateway on $InterfaceAlias; found $($gateway.Count). Re-evaluate the network before SSH."
}
$nextHop = $gateway[0].NextHop
$prefix = "$Address/32"
foreach ($store in @('ActiveStore', 'PersistentStore')) {
    $routes = @(Get-NetRoute -AddressFamily IPv4 -DestinationPrefix $prefix -PolicyStore $store -ErrorAction SilentlyContinue)
    if ($routes.Count -ne 1 -or $routes[0].InterfaceIndex -ne $adapter.ifIndex -or
        $routes[0].NextHop -ne $nextHop) {
        throw "$store route for $prefix does not match the current $InterfaceAlias gateway $nextHop. Repair the host route after checking the network."
    }
}

$results = for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
    $watch = [System.Diagnostics.Stopwatch]::StartNew()
    $sshArgs = @(
        '-o', 'BatchMode=yes', '-o', 'PreferredAuthentications=publickey',
        '-o', 'NumberOfPasswordPrompts=0', '-o', 'StrictHostKeyChecking=yes',
        '-o', "ConnectTimeout=$TimeoutSeconds", '-o', 'ConnectionAttempts=1',
        "$User@$Address", 'true'
    )
    & ssh @sshArgs 2>$null
    $exitCode = $LASTEXITCODE
    $watch.Stop()
    [pscustomobject]@{
        Attempt = $attempt
        ExitCode = $exitCode
        Milliseconds = $watch.ElapsedMilliseconds
        Route = "$InterfaceAlias via $nextHop"
    }
    if ($exitCode -ne 0) { break }
}
$results | Format-Table -AutoSize | Out-Host
if ($results.Count -ne $Attempts -or @($results | Where-Object ExitCode -ne 0).Count -ne 0) {
    throw 'Production SSH preflight failed; do not deploy over this connection.'
}
