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

Write-Output 'PASS provider-independent Docker image upgrade contract'
