param(
    [Parameter(Mandatory)]
    [ValidatePattern('^[0-9a-f]{24}$')]
    [string]$ApprovalId,
    [switch]$CheckOnly
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

foreach ($command in @('docker', 'git')) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
        throw "$command is required"
    }
}

$preflight = @(
    & docker exec mypeople /home/mp/mypeople/bin/mp publish $ApprovalId --check
)
if ($LASTEXITCODE -ne 0) {
    throw 'Publisher preflight failed'
}
if ($CheckOnly) {
    $preflight
    return
}

$credentialRequestPath = Join-Path ([System.IO.Path]::GetTempPath()) (
    'mypeople-credential-request-{0}.txt' -f [guid]::NewGuid().ToString('N')
)
try {
    [System.IO.File]::WriteAllText(
        $credentialRequestPath,
        "protocol=https`r`nhost=github.com`r`npath=LordCripto-Hub/Project-Factory.git`r`n`r`n",
        [System.Text.Encoding]::ASCII
    )
    $credentialProcessInfo = New-Object System.Diagnostics.ProcessStartInfo
    $credentialProcessInfo.FileName = $env:ComSpec
    $credentialProcessInfo.Arguments = '/d /s /c "git credential fill < ""' + $credentialRequestPath + '"""'
    $credentialProcessInfo.UseShellExecute = $false
    $credentialProcessInfo.RedirectStandardOutput = $true
    $credentialProcessInfo.RedirectStandardError = $true
    $credentialProcessInfo.CreateNoWindow = $true
    $credentialProcess = New-Object System.Diagnostics.Process
    $credentialProcess.StartInfo = $credentialProcessInfo
    [void]$credentialProcess.Start()
    $credentialOutput = $credentialProcess.StandardOutput.ReadToEnd()
    $credentialError = $credentialProcess.StandardError.ReadToEnd()
    $credentialProcess.WaitForExit()
    $credentialExitCode = $credentialProcess.ExitCode
    $credentialProcess.Dispose()
} finally {
    Remove-Item -LiteralPath $credentialRequestPath -Force -ErrorAction SilentlyContinue
}
if ($credentialExitCode -ne 0) {
    $credentialOutput = $null
    $credentialError = $null
    throw 'Windows Git Credential Manager did not return a credential'
}
$credentialLines = @($credentialOutput -split "`r?`n")
$credentialOutput = $null
$credentialError = $null
$credential = @{}
foreach ($line in $credentialLines) {
    if ($line -match '^([^=]+)=(.*)$') {
        $credential[$matches[1]] = $matches[2]
    }
}
if (-not $credential.username -or -not $credential.password) {
    throw 'Windows Git Credential Manager returned an incomplete credential'
}

$payload = [ordered]@{
    username = [string]$credential.username
    password = [string]$credential.password
} | ConvertTo-Json -Compress

try {
    $result = @(
        $payload |
            & docker exec -i mypeople /home/mp/mypeople/bin/publish-with-credential $ApprovalId
    )
    if ($LASTEXITCODE -ne 0) {
        throw 'Approved publication failed'
    }
    $result
} finally {
    $payload = $null
    $credential.Clear()
    $credentialLines = $null
}
