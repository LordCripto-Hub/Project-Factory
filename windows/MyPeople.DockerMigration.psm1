$script:SecretPattern = '(?i)(secret|token|password|api[_-]?key|credential|auth)'

function Get-MyPeopleVolumeContract {
    param([Parameter(Mandatory)][string]$Root)
    $path = Join-Path $Root 'docker\state-volumes.json'
    $object = Get-Content -Raw -LiteralPath $path | ConvertFrom-Json
    $result = [ordered]@{}
    foreach ($property in $object.PSObject.Properties) {
        $result[$property.Name] = [string]$property.Value
    }
    return $result
}

function Test-MyPeopleDockerName {
    param([Parameter(Mandatory)][string]$Name)
    return $Name -match '^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$'
}

function ConvertTo-MyPeopleRedactedConfig {
    param([AllowEmptyString()][string]$Text)
    $lines = foreach ($line in ($Text -split "`r?`n")) {
        if ($line -match '^\s*([^#=]+)=(.*)$') {
            $key = $matches[1].Trim()
            if ($key -match $script:SecretPattern) {
                '{0}=<redacted>' -f $key
            } else {
                $line
            }
        } else { $line }
    }
    return $lines -join "`n"
}

function Get-MyPeopleSha256 {
    param([Parameter(Mandatory)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
}

function Read-MyPeoplePlainText {
    param([Parameter(Mandatory)][string]$Path)
    return [IO.File]::ReadAllText((Resolve-Path -LiteralPath $Path).Path)
}

function Get-MyPeopleStableRosterHash {
    param([Parameter(Mandatory)][string]$Json)
    $roster = ConvertFrom-Json -InputObject $Json
    $stable = @(
        $roster |
            Sort-Object -Property agent_id |
            ForEach-Object {
                [ordered]@{
                    agent_id = $_.agent_id
                    backend = $_.backend
                    model = $_.model
                    provider_profile = $_.provider_profile
                    session_id = $_.session_id
                }
            }
    )
    $payload = ConvertTo-Json -InputObject $stable -Depth 4 -Compress
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [Text.Encoding]::UTF8.GetBytes($payload)
        return -join ($algorithm.ComputeHash($bytes) | ForEach-Object { $_.ToString('x2') })
    } finally {
        $algorithm.Dispose()
    }
}

function Write-MyPeopleTransaction {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][System.Collections.IDictionary]$State
    )
    $directory = Split-Path $Path -Parent
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
    $temporary = "$Path.tmp"
    $State | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $temporary -Encoding UTF8
    Move-Item -LiteralPath $temporary -Destination $Path -Force
}

function Enter-MyPeopleDockerOperationLock {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Owner
    )
    $directory = Split-Path $Path -Parent
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
    try {
        $stream = [IO.FileStream]::new(
            $Path,
            [IO.FileMode]::CreateNew,
            [IO.FileAccess]::ReadWrite,
            [IO.FileShare]::None,
            4096,
            [IO.FileOptions]::DeleteOnClose
        )
    } catch [IO.IOException] {
        throw "Another MyPeople Docker operation already owns the lock: $Path"
    }
    try {
        $payload = [Text.Encoding]::UTF8.GetBytes("$Owner`n")
        $stream.Write($payload, 0, $payload.Length)
        $stream.Flush($true)
        return $stream
    } catch {
        $stream.Dispose()
        Remove-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
        throw
    }
}

function Exit-MyPeopleDockerOperationLock {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][IO.FileStream]$Lock
    )
    $Lock.Dispose()
}

function Invoke-MyPeopleDocker {
    param(
        [Parameter(Mandatory)][string[]]$Arguments,
        [switch]$Capture
    )
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $output = @(& docker.exe @Arguments 2>&1)
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousPreference
    }
    if ($exitCode -ne 0) {
        throw "docker $($Arguments -join ' ') failed: $($output -join "`n")"
    }
    if ($Capture) { return $output -join "`n" }
}

function Test-MyPeopleDockerObject {
    param(
        [Parameter(Mandatory)][ValidateSet('container', 'image', 'volume')][string]$Type,
        [Parameter(Mandatory)][string]$Name
    )
    $safeName = if ($Type -eq 'image') {
        $Name -match '^[a-zA-Z0-9][a-zA-Z0-9_./:-]{0,255}$'
    } else {
        Test-MyPeopleDockerName $Name
    }
    if (-not $safeName) {
        throw 'Docker object check received an unsafe name'
    }

    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'SilentlyContinue'
        & docker.exe $Type inspect $Name 2>$null | Out-Null
        return $LASTEXITCODE -eq 0
    } finally {
        $ErrorActionPreference = $previousPreference
    }
}

function Invoke-MyPeopleRollback {
    param(
        [Parameter(Mandatory)][string]$PreservedName,
        [string]$NewName = 'mypeople'
    )
    if (-not (Test-MyPeopleDockerName $PreservedName) -or -not (Test-MyPeopleDockerName $NewName)) {
        throw 'Rollback received an unsafe Docker name'
    }

    $oldExists = Test-MyPeopleDockerObject -Type container -Name $PreservedName
    $newExists = Test-MyPeopleDockerObject -Type container -Name $NewName

    if (-not $oldExists) {
        if (-not $newExists) { throw 'Neither preserved nor original container exists' }
        Invoke-MyPeopleDocker -Arguments @('start', $NewName)
        Invoke-MyPeopleDocker -Arguments @(
            'exec', $NewName, '/home/mp/mypeople/bin/mypeople', 'up', '--detach'
        )
        return
    }
    if ($newExists) {
        Invoke-MyPeopleDocker -Arguments @('rm', '-f', $NewName)
    }
    Invoke-MyPeopleDocker -Arguments @('rename', $PreservedName, $NewName)
    Invoke-MyPeopleDocker -Arguments @('start', $NewName)
    Invoke-MyPeopleDocker -Arguments @(
        'exec', $NewName, '/home/mp/mypeople/bin/mypeople', 'up', '--detach'
    )
}

Export-ModuleMember -Function @(
    'Get-MyPeopleVolumeContract',
    'Test-MyPeopleDockerName',
    'ConvertTo-MyPeopleRedactedConfig',
    'Get-MyPeopleSha256',
    'Read-MyPeoplePlainText',
    'Get-MyPeopleStableRosterHash',
    'Write-MyPeopleTransaction',
    'Enter-MyPeopleDockerOperationLock',
    'Exit-MyPeopleDockerOperationLock',
    'Invoke-MyPeopleDocker',
    'Test-MyPeopleDockerObject',
    'Invoke-MyPeopleRollback'
)
