$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$modulePath = Join-Path $root 'windows\MyPeople.DockerMigration.psm1'
Import-Module $modulePath -Force

$contract = Get-MyPeopleVolumeContract -Root $root
if ($contract.Count -ne 8) { throw 'Expected eight volumes' }
if ($contract['mypeople-run'] -ne '/home/mp/mypeople/run') { throw 'Wrong run target' }
if ($contract['mypeople-workspaces'] -ne '/home/mp/workspaces') { throw 'Wrong workspace target' }
if (-not (Test-MyPeopleDockerName 'mypeople-pre-volumes-20260715T190000Z')) { throw 'Safe name rejected' }
if (Test-MyPeopleDockerName 'mypeople;rm') { throw 'Unsafe name accepted' }
if (-not (Test-MyPeopleDockerObject -Type container -Name 'mypeople')) {
    throw 'Existing container was not detected'
}
if (Test-MyPeopleDockerObject -Type container -Name 'mypeople-object-that-does-not-exist') {
    throw 'Missing container was reported as present'
}
if (-not (Test-MyPeopleDockerObject -Type image -Name 'mypeople-node:latest')) {
    throw 'Existing tagged image was not detected'
}

$redacted = ConvertTo-MyPeopleRedactedConfig @'
QUEUE_SECRET=alpha
NIGHTWATCH_TOKEN=beta
HOST_ID=node-1
TODO_PORT=9933
'@
if ($redacted -match 'alpha|beta') { throw 'Secret value leaked' }
if ($redacted -notmatch 'QUEUE_SECRET=<redacted>') { throw 'Queue secret was not redacted' }
if ($redacted -notmatch 'HOST_ID=node-1') { throw 'Non-secret value was lost' }

$rosterBefore = @'
[
  {"agent_id":"main","backend":"codex","model":"gpt-5.6-sol","provider_profile":"codex-primary","session_id":"boss-session","state":"alive","updated_at":"before"},
  {"agent_id":"eng-1","backend":"codex","model":"gpt-5.6-luna","provider_profile":"codex-primary","session_id":null,"state":"dead","updated_at":"before"}
]
'@
$rosterAfterRestart = @'
[
  {"agent_id":"eng-1","backend":"codex","model":"gpt-5.6-luna","provider_profile":"codex-primary","session_id":null,"state":"alive","updated_at":"after"},
  {"agent_id":"main","backend":"codex","model":"gpt-5.6-sol","provider_profile":"codex-primary","session_id":"boss-session","state":"alive","updated_at":"after"}
]
'@
$rosterChangedModel = $rosterAfterRestart -replace 'gpt-5.6-sol', 'gpt-5.6-luna'
$stableBefore = Get-MyPeopleStableRosterHash -Json $rosterBefore
$stableAfterRestart = Get-MyPeopleStableRosterHash -Json $rosterAfterRestart
$stableChangedModel = Get-MyPeopleStableRosterHash -Json $rosterChangedModel
if ($stableBefore -ne $stableAfterRestart) { throw 'Dynamic roster fields changed the stable hash' }
if ($stableBefore -eq $stableChangedModel) { throw 'Model change did not change the stable hash' }

$temporaryRoot = Join-Path ([IO.Path]::GetTempPath()) "mypeople-migration-test-$PID"
New-Item -ItemType Directory -Path $temporaryRoot -Force | Out-Null
try {
    $sourcePath = Join-Path $temporaryRoot 'source.txt'
    Set-Content -LiteralPath $sourcePath -Value 'hash-me' -NoNewline -Encoding ASCII
    $plainText = Read-MyPeoplePlainText -Path $sourcePath
    $serializedPlainText = ConvertTo-Json -InputObject $plainText -Depth 12 -Compress
    if ($serializedPlainText.Length -gt 64) {
        throw 'Plain text reader retained PowerShell extended properties'
    }
    $hash = Get-MyPeopleSha256 $sourcePath
    if ($hash -ne '4d11186aed035cc624d553e10db358492c84a7cd6b9670d92123c144930450aa') {
        throw "Unexpected SHA-256: $hash"
    }

    $transactionPath = Join-Path $temporaryRoot 'transaction.json'
    Write-MyPeopleTransaction -Path $transactionPath -State ([ordered]@{ stage='test'; count=7 })
    $transaction = Get-Content -Raw -LiteralPath $transactionPath | ConvertFrom-Json
    if ($transaction.stage -ne 'test' -or $transaction.count -ne 7) { throw 'Transaction did not round-trip' }
} finally {
    Remove-Item -LiteralPath $temporaryRoot -Recurse -Force
}

$dockerVersion = Invoke-MyPeopleDocker -Arguments @('version','--format','{{.Client.Version}}') -Capture
if (-not $dockerVersion.Trim()) { throw 'Docker capture helper returned no version' }
$stderrWithSuccess = Invoke-MyPeopleDocker -Arguments @(
    'exec', 'mypeople', 'sh', '-lc', 'printf healthy-to-stderr >&2'
) -Capture
if ($stderrWithSuccess -notmatch 'healthy-to-stderr') {
    throw 'Docker helper lost stderr from a successful command'
}

$module = Get-Content -Raw -LiteralPath $modulePath
$guardIndex = $module.IndexOf('if (-not $oldExists)')
$removeIndex = $module.IndexOf("Invoke-MyPeopleDocker -Arguments @('rm', '-f'")
if ($guardIndex -lt 0 -or $removeIndex -lt 0 -or $guardIndex -gt $removeIndex) {
    throw 'Rollback removal is not guarded by preserved-container detection'
}
if ($module -notmatch [regex]::Escape("'/home/mp/mypeople/bin/mypeople', 'up', '--detach'")) {
    throw 'Rollback does not restart the legacy container services'
}

$migrationPath = Join-Path $root 'windows\Migrate-MyPeopleDockerState.ps1'
$migration = if (Test-Path -LiteralPath $migrationPath) { Get-Content -Raw $migrationPath } else { '' }
foreach ($required in @(
    '[switch]$Execute',
    'mypeople-pre-volumes-',
    'mypeople-node:pre-volumes-',
    'mypeople-node:volume-backed-',
    'Docker commit',
    'Docker rename',
    'Invoke-MyPeopleRollback',
    'compose.volume-backed.yml',
    'state-volumes.json',
    'portable-state.tar.gz',
    'Remove-StaleRuntimePidFiles',
    'Test-MyPeopleDockerRestore.ps1'
)) {
    if ($migration -notmatch [regex]::Escape($required)) { throw "Missing migration token: $required" }
}
foreach ($forbidden in @('docker volume rm', 'docker compose down -v', 'docker system prune')) {
    if ($migration -match [regex]::Escape($forbidden)) { throw "Forbidden migration token: $forbidden" }
}
foreach ($required in @(
    '[int]$MinimumFreeGiB = 16',
    '[string]$ResumeManifest',
    'beforeStableState',
    'afterStableState',
    'resumedFrom',
    'snapshot-reused',
    'portable-backup-reused',
    'Rollback launcher verification failed',
    'cp -a ''$source/.'' ''$target/''',
    'Get-MyPeopleStableRosterHash -Json',
    'Test-MyPeopleDockerObject -Type volume',
    'copy_if_present /home/mp/workspaces /tmp/portable/home/mp/',
    'extraheader|helper'
)) {
    if ($migration -notmatch [regex]::Escape($required)) {
        throw "Missing migration regression guard: $required"
    }
}

$restorePath = Join-Path $root 'windows\Test-MyPeopleDockerRestore.ps1'
$restore = if (Test-Path -LiteralPath $restorePath) { Get-Content -Raw $restorePath } else { '' }
foreach ($required in @(
    'mypeople-restore-',
    'MYPEOPLE_SUPPRESS_BOSS_NOTIFY=1',
    'MYPEOPLE_DISABLE_PROVIDER_LAUNCH=1',
    'board.v2.json',
    'roster.json',
    'portable-state.tar.gz',
    'copy_tree /restore/home/mp/workspaces /mnt/mypeople-workspaces'
)) {
    if ($restore -notmatch [regex]::Escape($required)) { throw "Missing restore behavior: $required" }
}
if ($restore -match [regex]::Escape('docker volume rm')) {
    throw 'Restore drill must retain evidence volumes'
}

Write-Output 'PASS Docker migration contract, names, redaction, hashes, and transactions'
