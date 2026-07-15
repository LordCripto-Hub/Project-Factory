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

function Invoke-MyPeopleDocker {
    param(
        [Parameter(Mandatory)][string[]]$Arguments,
        [switch]$Capture
    )
    $output = @(& docker @Arguments 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "docker $($Arguments -join ' ') failed: $($output -join "`n")"
    }
    if ($Capture) { return $output -join "`n" }
}

function Invoke-MyPeopleRollback {
    param(
        [Parameter(Mandatory)][string]$PreservedName,
        [string]$NewName = 'mypeople'
    )
    if (-not (Test-MyPeopleDockerName $PreservedName) -or -not (Test-MyPeopleDockerName $NewName)) {
        throw 'Rollback received an unsafe Docker name'
    }

    & docker inspect $PreservedName *> $null
    $oldExists = $LASTEXITCODE -eq 0
    & docker inspect $NewName *> $null
    $newExists = $LASTEXITCODE -eq 0

    if (-not $oldExists) {
        if (-not $newExists) { throw 'Neither preserved nor original container exists' }
        Invoke-MyPeopleDocker -Arguments @('start', $NewName)
        return
    }
    if ($newExists) {
        Invoke-MyPeopleDocker -Arguments @('rm', '-f', $NewName)
    }
    Invoke-MyPeopleDocker -Arguments @('rename', $PreservedName, $NewName)
    Invoke-MyPeopleDocker -Arguments @('start', $NewName)
}

Export-ModuleMember -Function @(
    'Get-MyPeopleVolumeContract',
    'Test-MyPeopleDockerName',
    'ConvertTo-MyPeopleRedactedConfig',
    'Get-MyPeopleSha256',
    'Write-MyPeopleTransaction',
    'Invoke-MyPeopleDocker',
    'Invoke-MyPeopleRollback'
)
