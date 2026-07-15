param(
    [Parameter(Mandatory)][string]$Image,
    [Parameter(Mandatory)][string]$Manifest
)

$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Import-Module (Join-Path $PSScriptRoot 'MyPeople.DockerMigration.psm1') -Force

if (-not (Test-Path -LiteralPath $Manifest)) {
    throw "Migration manifest missing: $Manifest"
}
$record = Get-Content -Raw -LiteralPath $Manifest | ConvertFrom-Json
$backupRoot = Split-Path $Manifest -Parent
$archive = Join-Path $backupRoot 'portable-state.tar.gz'
if (-not (Test-Path -LiteralPath $archive)) {
    throw "Portable archive missing: $archive"
}
if ((Get-MyPeopleSha256 $archive) -ne [string]$record.archiveSha256) {
    throw 'Portable archive hash mismatch'
}

$contract = Get-MyPeopleVolumeContract -Root $root
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$container = "mypeople-restore-$stamp"
$restoreVolumes = [ordered]@{}
foreach ($volume in $contract.Keys) {
    $name = "mypeople-restore-$stamp-$volume"
    Invoke-MyPeopleDocker -Arguments @('volume', 'create', $name)
    $restoreVolumes[$volume] = $name
}

$createArgs = @(
    'create', '--name', $container,
    '--user', 'root',
    '--env', 'MYPEOPLE_SUPPRESS_BOSS_NOTIFY=1',
    '--env', 'MYPEOPLE_DISABLE_PROVIDER_LAUNCH=1'
)
foreach ($volume in $contract.Keys) {
    $createArgs += @(
        '--mount',
        "type=volume,src=$($restoreVolumes[$volume]),dst=/mnt/$volume"
    )
}
$createArgs += @($Image, 'sleep', 'infinity')
Invoke-MyPeopleDocker -Arguments $createArgs

try {
    Invoke-MyPeopleDocker -Arguments @('start', $container)
    Invoke-MyPeopleDocker -Arguments @(
        'cp', $archive, ('{0}:/tmp/portable-state.tar.gz' -f $container)
    )
    $restoreCommand = @'
set -eu
mkdir -p /restore
tar -C /restore -xzf /tmp/portable-state.tar.gz
copy_tree() { [ ! -d "$1" ] || cp -a "$1"/. "$2"/; }
copy_tree /restore/home/mp/mypeople/todos /mnt/mypeople-todos
copy_tree /restore/home/mp/mypeople/run /mnt/mypeople-run
copy_tree /restore/home/mp/mypeople/status /mnt/mypeople-status
copy_tree /restore/home/mp/recordings /mnt/mypeople-recordings
copy_tree /restore/home/mp/.codex /mnt/mypeople-codex
copy_tree /restore/home/mp/.claude /mnt/mypeople-claude
python3 -m json.tool /mnt/mypeople-todos/board.v2.json >/dev/null
python3 -m json.tool /mnt/mypeople-run/roster.json >/dev/null
'@
    Invoke-MyPeopleDocker -Arguments @(
        'exec', $container, 'sh', '-lc', $restoreCommand
    )
    $actual = Invoke-MyPeopleDocker -Arguments @(
        'exec', $container, 'sh', '-lc',
        'sha256sum /mnt/mypeople-todos/board.v2.json /mnt/mypeople-run/roster.json'
    ) -Capture

    $expectedHashes = @(
        [regex]::Split([string]$record.beforeState, '\r?\n') |
            Where-Object { $_.Trim() } |
            ForEach-Object { ($_ -split '\s+')[0] }
    )
    $actualHashes = @(
        [regex]::Split($actual, '\r?\n') |
            Where-Object { $_.Trim() } |
            ForEach-Object { ($_ -split '\s+')[0] }
    )
    if (($expectedHashes -join ',') -ne ($actualHashes -join ',')) {
        throw 'Restored board or roster hash mismatch'
    }

    $evidence = [ordered]@{
        container = $container
        image = $Image
        volumes = $restoreVolumes
        hashes = $actualHashes
        providerLaunchDisabled = $true
        bossNotificationsSuppressed = $true
        status = 'pass'
    }
    Write-MyPeopleTransaction -Path (Join-Path $backupRoot 'restore-drill.json') -State $evidence
    Write-Output "PASS isolated Docker restore drill; evidence volumes retained: $($restoreVolumes.Values -join ', ')"
} finally {
    & docker.exe rm -f $container *> $null
}
