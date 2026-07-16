param([string]$Container = 'mypeople')

$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'MyPeople.Memory.psm1') -Force
$secretPath = '/run/mypeople-secrets/MYPEOPLE_MEMORY_TOKEN'

Clear-MyPeopleMemoryCredentialInContainer -Container $Container
try {
    Install-MyPeopleMemoryCredentialInContainer -Container $Container | Out-Null
    & docker exec -e MYPEOPLE_MEMORY_PILOT_E2E=1 -e PYTHONPATH=/home/mp/mypeople/bin $Container python3 /home/mp/mypeople/verify/test_memory_activation_e2e.py
    if ($LASTEXITCODE -ne 0) {
        throw 'The live synthetic MyPeople memory pilot failed.'
    }
} finally {
    Clear-MyPeopleMemoryCredentialInContainer -Container $Container
    & docker exec $Container test ! -e $secretPath
    if ($LASTEXITCODE -ne 0) {
        throw 'The live pilot did not clear the tmpfs memory credential.'
    }
}

Write-Output 'PASS MyPeople synthetic memory activation; tmpfs credential cleared.'
