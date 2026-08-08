$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$upgradePath = Join-Path $root 'windows\Upgrade-MyPeopleDockerImage.ps1'
if (-not (Test-Path -LiteralPath $upgradePath)) {
    throw 'Permanent Docker image upgrade command is missing.'
}
$upgrade = Get-Content -Raw -LiteralPath $upgradePath

foreach ($required in @(
    '[string]$CandidateImage',
    'git -C $root status --porcelain',
    'Invoke-IsolatedVerify.ps1',
    '-UsePackagedSource',
    'backups\docker-upgrade',
    'portable-state.tar.gz',
    "backupClassification = 'sensitive-local-restore-material'",
    '*auth*',
    '*credential*',
    '*token*',
    '*.key',
    "-name '.env'",
    "-name '.env.*'",
    "-name '.npmrc'",
    "-name '.pypirc'",
    "-name '*.pem'",
    "-name '*.p12'",
    'Get-FileHash -Algorithm SHA256',
    'candidateImageId',
    "'inspect', 'mypeople', '--format', '{{.Image}}'",
    'deploymentImage',
    'rollbackPinnedImage',
    '''tag'', $script:state.candidateImageId, $script:state.deploymentImage',
    '''tag'', $script:state.rollbackImageId, $script:state.rollbackPinnedImage',
    '.env.previous.redacted',
    '--force-recreate',
    "'up', '--detach', '--force-recreate'",
    'Invoke-MyPeopleDocker -Arguments @(',
    'Get-MyPeopleStableRosterHash -Json',
    'mypeople-workspaces',
    '/home/mp/mypeople.seed.md',
    'Destination -eq $entry.Value',
    '$_.RW',
    '$volumeMounts.Count -ne $contract.Count',
    'repo-project-factory',
    'rollbackImage',
    'providerActivationAttempted = $false',
    'docker-operation.lock',
    'Enter-MyPeopleDockerOperationLock',
    'Exit-MyPeopleDockerOperationLock',
    '$deploymentFilesChanged',
    'recovery-required',
    'rollbackState.boardSha256',
    'rollbackState.stableRosterSha256',
    'Write-MyPeopleTransaction'
)) {
    if ($upgrade -notmatch [regex]::Escape($required)) {
        throw "Missing upgrade safety contract: $required"
    }
}

foreach ($forbidden in @(
    'docker rename',
    "'rename'",
    'docker compose down -v',
    'docker volume rm',
    'MyPeople.ProviderProfiles.psm1',
    'ActivateProfile',
    'ValidateRuntime',
    'main:Boss [alive]',
    'nightwatch:Nightwatch [alive]',
    'mypeople up --detach',
    'up -d --force-recreate',
    'function Docker {',
    'function Docker-Capture {',
    'Copy-Item -LiteralPath $environmentPath'
)) {
    if ($upgrade -match [regex]::Escape($forbidden)) {
        throw "Forbidden upgrade behavior: $forbidden"
    }
}

$backupStart = $upgrade.IndexOf('function Write-PortableBackup')
$backupEnd = $upgrade.IndexOf('function Assert-Preflight')
if ($backupStart -lt 0 -or $backupEnd -le $backupStart) {
    throw 'Unable to isolate the portable-backup implementation.'
}
$backupBody = $upgrade.Substring($backupStart, $backupEnd - $backupStart)
foreach ($required in @(
    'backupBoardSha256',
    'backupStableRosterSha256',
    '/tmp/portable/home/mp/mypeople/todos/board.v2.json',
    '/tmp/portable/home/mp/mypeople/run/roster.json',
    'Assert-FrozenSourceState'
)) {
    if ($backupBody -notmatch [regex]::Escape($required)) {
        throw "Backup does not capture frozen durable state: $required"
    }
}
if ($backupBody -match '\$script:state\.backupBoardSha256[^\r\n]*/src/mypeople-todos/board\.v2\.json') {
    throw 'The authoritative board hash must come from the staged archive tree.'
}
if ($backupBody -match [regex]::Escape("Invoke-MyPeopleDocker -Arguments @('start', 'mypeople')")) {
    throw 'The old runtime must remain stopped between backup and candidate deployment.'
}
foreach ($required in @(
    '$script:state.beforeBoardSha256 = $script:state.backupBoardSha256',
    '$script:state.beforeStableRosterSha256 = $script:state.backupStableRosterSha256',
    'Assert-FrozenSourceState',
    'Restore-StoppedLiveContainer',
    'restartFailure',
    "restartStatus = 'recovery-required'"
)) {
    if ($upgrade -notmatch [regex]::Escape($required)) {
        throw "Upgrade does not compare against the frozen backup state: $required"
    }
}
$frozenCheck = $upgrade.LastIndexOf('Assert-FrozenSourceState')
$deployCall = $upgrade.IndexOf('Invoke-PinnedCompose', $frozenCheck)
if ($frozenCheck -lt 0 -or $deployCall -le $frozenCheck) {
    throw 'Frozen source state must be rechecked immediately before deployment.'
}
$finallyStart = $upgrade.LastIndexOf('} finally {')
if ($finallyStart -lt 0) { throw 'Upgrade finally block is missing.' }
$finallyBody = $upgrade.Substring($finallyStart)
if ($finallyBody -notmatch [regex]::Escape('Restore-StoppedLiveContainer')) {
    throw 'Finally must use the checked live-container restart path.'
}
if ($finallyBody -match [regex]::Escape("& docker start mypeople")) {
    throw 'Finally must not use an unchecked native Docker restart.'
}
$restartStart = $upgrade.IndexOf('function Restore-StoppedLiveContainer')
$restartEnd = $upgrade.IndexOf('function Get-LiveState')
if ($restartStart -lt 0 -or $restartEnd -le $restartStart) {
    throw 'Unable to isolate the checked restart implementation.'
}
$restartBody = $upgrade.Substring($restartStart, $restartEnd - $restartStart)
foreach ($required in @('{{.Image}}', 'rollbackImageId')) {
    if ($restartBody -notmatch [regex]::Escape($required)) {
        throw "Checked restart does not validate immutable image identity: $required"
    }
}

Write-Output 'PASS provider-independent Docker image upgrade contract'
