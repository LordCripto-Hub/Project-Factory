$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$modulePath = Join-Path $root 'windows\MyPeople.DockerMigration.psm1'
Import-Module $modulePath -Force

$contract = Get-MyPeopleVolumeContract -Root $root
if ($contract.Count -ne 7) { throw 'Expected seven volumes' }
if ($contract['mypeople-run'] -ne '/home/mp/mypeople/run') { throw 'Wrong run target' }
if (-not (Test-MyPeopleDockerName 'mypeople-pre-volumes-20260715T190000Z')) { throw 'Safe name rejected' }
if (Test-MyPeopleDockerName 'mypeople;rm') { throw 'Unsafe name accepted' }

$redacted = ConvertTo-MyPeopleRedactedConfig @'
QUEUE_SECRET=alpha
NIGHTWATCH_TOKEN=beta
HOST_ID=node-1
TODO_PORT=9933
'@
if ($redacted -match 'alpha|beta') { throw 'Secret value leaked' }
if ($redacted -notmatch 'QUEUE_SECRET=<redacted>') { throw 'Queue secret was not redacted' }
if ($redacted -notmatch 'HOST_ID=node-1') { throw 'Non-secret value was lost' }

$temporaryRoot = Join-Path ([IO.Path]::GetTempPath()) "mypeople-migration-test-$PID"
New-Item -ItemType Directory -Path $temporaryRoot -Force | Out-Null
try {
    $sourcePath = Join-Path $temporaryRoot 'source.txt'
    Set-Content -LiteralPath $sourcePath -Value 'hash-me' -NoNewline -Encoding ASCII
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

$module = Get-Content -Raw -LiteralPath $modulePath
$guardIndex = $module.IndexOf('if (-not $oldExists)')
$removeIndex = $module.IndexOf("Invoke-MyPeopleDocker -Arguments @('rm', '-f'")
if ($guardIndex -lt 0 -or $removeIndex -lt 0 -or $guardIndex -gt $removeIndex) {
    throw 'Rollback removal is not guarded by preserved-container detection'
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

Write-Output 'PASS Docker migration contract, names, redaction, hashes, and transactions'
