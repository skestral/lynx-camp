[CmdletBinding()]
param(
    [ValidateRange(1024, 65535)]
    [int]$Port = 6080,
    [switch]$NoBuild,
    [switch]$ShowPassword
)

$ErrorActionPreference = 'Stop'
if (-not $env:LOCALAPPDATA) {
    throw 'This launcher requires Windows. Use compose.browser.yaml directly on a Linux server.'
}
$repo = Split-Path -Parent $PSScriptRoot
$endpoint = & docker context inspect desktop-linux --format '{{.Endpoints.docker.Host}}'
if ($LASTEXITCODE -ne 0 -or $endpoint -notlike 'npipe://*') {
    throw 'A local Docker Desktop Linux context is required. No remote Docker service will be started.'
}
$secretDirectory = Join-Path $env:LOCALAPPDATA 'CampFinder\browser-worker'
$secretPath = Join-Path $secretDirectory 'console-password.xml'

if (-not (Test-Path -LiteralPath $secretPath)) {
    New-Item -ItemType Directory -Path $secretDirectory -Force | Out-Null
    $bytes = New-Object byte[] 24
    $random = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $random.GetBytes($bytes) } finally { $random.Dispose() }
    $generated = [Convert]::ToBase64String($bytes)
    # Export-Clixml uses Windows DPAPI for SecureString values, bound to this user.
    ConvertTo-SecureString $generated -AsPlainText -Force | Export-Clixml -LiteralPath $secretPath
}
$securePassword = Import-Clixml -LiteralPath $secretPath
if ($securePassword -isnot [System.Security.SecureString]) {
    throw 'The saved console credential is not a Windows SecureString.'
}
$credential = New-Object System.Management.Automation.PSCredential ('campfinder', $securePassword)
$oldPassword = $env:CAMPFINDER_BROWSER_PASSWORD
$oldPort = $env:CAMPFINDER_BROWSER_PORT
$compose = @('--context', 'desktop-linux', 'compose', '-p', 'campfinder-browser-local', '-f', (Join-Path $repo 'compose.browser.yaml'))

Push-Location $repo
try {
    $env:CAMPFINDER_BROWSER_PASSWORD = $credential.GetNetworkCredential().Password
    $env:CAMPFINDER_BROWSER_PORT = [string]$Port
    $buildFlag = if ($NoBuild) { '--no-build' } else { '--build' }
    & docker @compose up -d $buildFlag
    if ($LASTEXITCODE -ne 0) { throw 'Browser worker startup failed. Existing Camp Finder services were not changed.' }
    $container = & docker @compose ps -a -q browser
    if ($LASTEXITCODE -ne 0 -or -not $container) { throw 'Browser worker container was not created.' }
    $deadline = (Get-Date).AddSeconds(90)
    do {
        $stateJson = & docker --context desktop-linux inspect --format '{{json .State}}' $container
        if ($LASTEXITCODE -ne 0) { throw 'Could not inspect browser worker state.' }
        $state = $stateJson | ConvertFrom-Json
        if (-not $state.Running) {
            throw "Browser worker exited. Inspect logs with: docker --context desktop-linux logs $container"
        }
        if ($state.Health.Status -eq 'healthy') { break }
        if ($state.Health.Status -eq 'unhealthy' -or (Get-Date) -ge $deadline) {
            throw "Browser worker is not healthy. Inspect logs with: docker --context desktop-linux logs $container"
        }
        Start-Sleep -Seconds 2
    } while ($true)

    Write-Output "Console: http://127.0.0.1:$Port/vnc.html?autoconnect=true&resize=scale"
    Write-Output 'Username: campfinder'
    Write-Output "Encrypted credential: $secretPath"
    if ($ShowPassword) { Write-Output "Password: $($credential.GetNetworkCredential().Password)" }
    Write-Output "Stop: docker --context desktop-linux stop $container"
} finally {
    $env:CAMPFINDER_BROWSER_PASSWORD = $oldPassword
    $env:CAMPFINDER_BROWSER_PORT = $oldPort
    Pop-Location
}
