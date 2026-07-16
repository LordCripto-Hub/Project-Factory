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

$preflightText = (@(
    & docker exec mypeople /home/mp/mypeople/bin/mp publish $ApprovalId --check
) -join "`n").Trim()
if ($LASTEXITCODE -ne 0) {
    throw 'Publisher preflight failed'
}
$preflight = $preflightText | ConvertFrom-Json
if ($CheckOnly) {
    $preflightText
    return
}

$repositoryUri = [Uri]$preflight.repository
$repositoryPath = $repositoryUri.AbsolutePath.TrimStart('/')

$result = $null
$resultText = $null
if ($preflight.mode -eq 'draft_pr' -and $preflight.status -in @('branch_pushed', 'pr_created')) {
    $result = $preflight
    $resultText = $preflightText
} else {
$credentialRequestPath = Join-Path ([System.IO.Path]::GetTempPath()) (
    'mypeople-credential-request-{0}.txt' -f [guid]::NewGuid().ToString('N')
)
try {
    [System.IO.File]::WriteAllText(
        $credentialRequestPath,
        "protocol=https`r`nhost=github.com`r`npath=$repositoryPath`r`n`r`n",
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
    $resultText = (@(
        $payload |
            & docker exec -i mypeople /home/mp/mypeople/bin/publish-with-credential $ApprovalId
    ) -join "`n").Trim()
    if ($LASTEXITCODE -ne 0) {
        throw 'Approved publication failed'
    }
    $result = $resultText | ConvertFrom-Json
} finally {
    $payload = $null
    $credential.Clear()
    $credentialLines = $null
}
}

if ($result.mode -ne 'draft_pr') {
    $resultText
    return
}
if ($result.status -eq 'pr_created') {
    $resultText
    return
}
if ($result.status -ne 'branch_pushed') {
    throw "Draft PR publication stopped in unexpected state: $($result.status)"
}
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    throw 'GitHub CLI is required after the approved branch push; rerun after gh authentication'
}

$repositorySlug = $repositoryPath -replace '\.git$', ''
$pullRequestListText = (& gh pr list --repo $repositorySlug --head $result.headBranch --state all --json number,url,state,isDraft,headRefName,baseRefName --limit 1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0) {
    throw 'GitHub pull request discovery failed; the approved branch remains pushed for an idempotent retry'
}
if (-not $pullRequestListText) {
    throw 'GitHub pull request discovery returned no JSON; the approved branch remains pushed for an idempotent retry'
}
if (
    -not $pullRequestListText.StartsWith('[') -or
    -not $pullRequestListText.EndsWith(']')
) {
    throw 'GitHub pull request discovery returned an invalid JSON contract; the approved branch remains pushed for an idempotent retry'
}
$pullRequestCandidates = @()
$parsedPullRequests = $pullRequestListText | ConvertFrom-Json
if ($null -ne $parsedPullRequests) {
    $pullRequestCandidates = @($parsedPullRequests)
}
if ($pullRequestCandidates.Count -eq 0) {
    & gh pr create --draft --repo $repositorySlug --base $result.baseBranch --head $result.headBranch --title $result.prTitle --body $result.prBody | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw 'GitHub draft PR creation failed; the approved branch remains pushed for an idempotent retry'
    }
    $pullRequestText = (& gh pr view $result.headBranch --repo $repositorySlug --json number,url,state,isDraft,headRefName,baseRefName | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $pullRequestText) {
        throw 'GitHub draft PR was created but could not be inspected; rerun to finalize it'
    }
    $pullRequest = $pullRequestText | ConvertFrom-Json
} else {
    $pullRequest = $pullRequestCandidates[0]
}
if (
    $pullRequest.state -ne 'OPEN' -or
    $pullRequest.isDraft -ne $true -or
    $pullRequest.headRefName -ne $result.headBranch -or
    $pullRequest.baseRefName -ne $result.baseBranch
) {
    throw 'GitHub returned a pull request that does not match the approved open base/head contract'
}
$finalText = (@(
    & docker exec mypeople /home/mp/mypeople/bin/mp publish-pr-complete $ApprovalId --number ([int]$pullRequest.number) --url ([string]$pullRequest.url)
) -join "`n").Trim()
if ($LASTEXITCODE -ne 0) {
    throw 'Draft PR exists but MyPeople could not record the final receipt; rerun to reconcile it'
}
$finalText
