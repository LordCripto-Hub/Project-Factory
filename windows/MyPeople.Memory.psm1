$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Security

if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
    throw 'LOCALAPPDATA is required for the MyPeople memory credential store.'
}

$script:MemoryRoot = Join-Path $env:LOCALAPPDATA 'MyPeople\memory'
$script:CredentialPath = Join-Path $script:MemoryRoot 'cloudflare-pilot.dpapi'
$script:SettingsPath = Join-Path $script:MemoryRoot 'settings.json'
$script:SecretPath = '/run/mypeople-secrets/MYPEOPLE_MEMORY_TOKEN'
$script:PilotServerUrl = 'https://mypeople-memory-sandbox.labmkt.workers.dev/mcp'
$script:Entropy = [Text.Encoding]::UTF8.GetBytes('MyPeople.MemoryCredential.v1')

function Protect-MyPeopleMemoryDirectory {
    param([Parameter(Mandatory)][string]$Path)
    $resolved = [IO.Path]::GetFullPath($Path)
    [IO.Directory]::CreateDirectory($resolved) | Out-Null
    $directory = [IO.DirectoryInfo]::new($resolved)
    $acl = $directory.GetAccessControl([Security.AccessControl.AccessControlSections]::Access)
    $acl.SetAccessRuleProtection($true, $false)
    foreach ($rule in @($acl.Access)) {
        [void]$acl.RemoveAccessRuleAll($rule)
    }
    $inheritance = [Security.AccessControl.InheritanceFlags]'ContainerInherit, ObjectInherit'
    $allow = [Security.AccessControl.AccessControlType]::Allow
    $rights = [Security.AccessControl.FileSystemRights]::FullControl
    $currentUser = [Security.Principal.WindowsIdentity]::GetCurrent().User
    $system = [Security.Principal.SecurityIdentifier]::new(
        [Security.Principal.WellKnownSidType]::LocalSystemSid,
        $null
    )
    foreach ($identity in @($currentUser, $system)) {
        $accessRule = [Security.AccessControl.FileSystemAccessRule]::new(
            $identity,
            $rights,
            $inheritance,
            [Security.AccessControl.PropagationFlags]::None,
            $allow
        )
        [void]$acl.AddAccessRule($accessRule)
    }
    $directory.SetAccessControl($acl)
    return $resolved
}

function Initialize-MyPeopleMemoryStore {
    Protect-MyPeopleMemoryDirectory -Path $script:MemoryRoot | Out-Null
    return $script:MemoryRoot
}

function Get-MyPeopleMemoryCredentialPath {
    Initialize-MyPeopleMemoryStore | Out-Null
    return $script:CredentialPath
}

function Write-MyPeopleMemoryBytesAtomic {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][byte[]]$Bytes
    )
    Initialize-MyPeopleMemoryStore | Out-Null
    $temporary = Join-Path $script:MemoryRoot ('.memory-' + [Guid]::NewGuid().ToString('N') + '.tmp')
    try {
        [IO.File]::WriteAllBytes($temporary, $Bytes)
        Move-Item -LiteralPath $temporary -Destination $Path -Force
    } finally {
        if (Test-Path -LiteralPath $temporary) {
            Remove-Item -LiteralPath $temporary -Force
        }
    }
}

function Save-MyPeopleMemoryCredentialBytes {
    param([Parameter(Mandatory)][byte[]]$CredentialBytes)
    if ($CredentialBytes.Length -lt 16 -or $CredentialBytes.Length -gt 4096) {
        throw 'Memory credential must contain between 16 and 4096 bytes.'
    }
    $protected = [Security.Cryptography.ProtectedData]::Protect(
        $CredentialBytes,
        $script:Entropy,
        [Security.Cryptography.DataProtectionScope]::CurrentUser
    )
    try {
        Write-MyPeopleMemoryBytesAtomic -Path $script:CredentialPath -Bytes $protected
    } finally {
        [Array]::Clear($protected, 0, $protected.Length)
    }
    return $script:CredentialPath
}

function Get-MyPeopleMemoryCredentialBytes {
    Initialize-MyPeopleMemoryStore | Out-Null
    if (-not [IO.File]::Exists($script:CredentialPath)) {
        throw 'The DPAPI-protected MyPeople memory credential is missing.'
    }
    $protected = [IO.File]::ReadAllBytes($script:CredentialPath)
    try {
        $plain = [Security.Cryptography.ProtectedData]::Unprotect(
            $protected,
            $script:Entropy,
            [Security.Cryptography.DataProtectionScope]::CurrentUser
        )
    } finally {
        [Array]::Clear($protected, 0, $protected.Length)
    }
    if ($plain.Length -lt 16 -or $plain.Length -gt 4096) {
        [Array]::Clear($plain, 0, $plain.Length)
        throw 'The DPAPI-protected MyPeople memory credential is invalid.'
    }
    return $plain
}

function Test-MyPeopleMemoryProjectSlug {
    param([Parameter(Mandatory)][string]$ProjectSlug)
    if ($ProjectSlug.Length -gt 64 -or $ProjectSlug -notmatch '^[a-z0-9]+(?:-[a-z0-9]+)*$') {
        throw 'Invalid MyPeople memory project slug.'
    }
    return $ProjectSlug
}

function Test-MyPeopleMemoryServerUrl {
    param([Parameter(Mandatory)][string]$ServerUrl)
    $uri = $null
    if (-not [Uri]::TryCreate($ServerUrl, [UriKind]::Absolute, [ref]$uri) -or
        $uri.Scheme -ne 'https' -or
        -not [string]::IsNullOrEmpty($uri.UserInfo) -or
        -not [string]::IsNullOrEmpty($uri.Query) -or
        -not [string]::IsNullOrEmpty($uri.Fragment)) {
        throw 'Memory MCP URL must be HTTPS without credentials, query, or fragment.'
    }
    $normalized = $uri.AbsoluteUri.TrimEnd('/')
    if ($normalized -ne $script:PilotServerUrl) {
        throw 'The pilot credential is pinned to the trusted MyPeople MCP URL.'
    }
    return $normalized
}

function Set-MyPeopleMemorySettings {
    param(
        [Parameter(Mandatory)][bool]$Enabled,
        [Parameter(Mandatory)][string]$ProjectSlug,
        [Parameter(Mandatory)][string]$ServerUrl
    )
    Initialize-MyPeopleMemoryStore | Out-Null
    $value = [ordered]@{
        schemaVersion = 1
        enabled = $Enabled
        projectSlug = Test-MyPeopleMemoryProjectSlug -ProjectSlug $ProjectSlug
        serverUrl = Test-MyPeopleMemoryServerUrl -ServerUrl $ServerUrl
        credentialRef = 'dpapi://cloudflare-pilot'
        containerCredentialRef = 'file:///run/mypeople-secrets/MYPEOPLE_MEMORY_TOKEN'
    }
    $json = [Text.UTF8Encoding]::new($false).GetBytes(
        ($value | ConvertTo-Json -Depth 8) + [Environment]::NewLine
    )
    try {
        Write-MyPeopleMemoryBytesAtomic -Path $script:SettingsPath -Bytes $json
    } finally {
        [Array]::Clear($json, 0, $json.Length)
    }
    return [pscustomobject]$value
}

function Get-MyPeopleMemorySettings {
    Initialize-MyPeopleMemoryStore | Out-Null
    if (-not [IO.File]::Exists($script:SettingsPath)) { return $null }
    try {
        $value = [IO.File]::ReadAllText($script:SettingsPath, [Text.Encoding]::UTF8) | ConvertFrom-Json
        if ($value.schemaVersion -ne 1 -or $value.enabled -isnot [bool]) {
            throw 'Invalid memory settings schema.'
        }
        Test-MyPeopleMemoryProjectSlug -ProjectSlug ([string]$value.projectSlug) | Out-Null
        Test-MyPeopleMemoryServerUrl -ServerUrl ([string]$value.serverUrl) | Out-Null
        if ($value.credentialRef -ne 'dpapi://cloudflare-pilot' -or
            $value.containerCredentialRef -ne 'file:///run/mypeople-secrets/MYPEOPLE_MEMORY_TOKEN') {
            throw 'Invalid memory credential reference.'
        }
        return $value
    } catch {
        throw 'MyPeople memory settings are invalid.'
    }
}

function Test-MyPeopleMemoryContainerName {
    param([Parameter(Mandatory)][string]$Container)
    if ($Container -notmatch '^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$') {
        throw 'Invalid Docker container name.'
    }
    return $Container
}

function Install-MyPeopleMemoryCredentialInContainer {
    param([string]$Container = 'mypeople')
    $safeContainer = Test-MyPeopleMemoryContainerName -Container $Container
    $credentialBytes = Get-MyPeopleMemoryCredentialBytes
    $secret = $null
    $previousInputEncoding = [Console]::InputEncoding
    try {
        [Console]::InputEncoding = [Text.UTF8Encoding]::new($false)
        $secret = [Text.Encoding]::UTF8.GetString($credentialBytes)
        $start = [Diagnostics.ProcessStartInfo]::new()
        $start.FileName = (Get-Command docker -ErrorAction Stop).Source
        $start.Arguments = 'exec -i ' + $safeContainer + ' sh -c "umask 077; cat > ' + $script:SecretPath + '"'
        $start.UseShellExecute = $false
        $start.CreateNoWindow = $true
        $start.RedirectStandardInput = $true
        $start.RedirectStandardOutput = $true
        $start.RedirectStandardError = $true
        $process = [Diagnostics.Process]::new()
        $process.StartInfo = $start
        if (-not $process.Start()) { throw 'Unable to start Docker memory injection.' }
        $process.StandardInput.Write($secret)
        $process.StandardInput.Close()
        $process.StandardOutput.ReadToEnd() | Out-Null
        $process.StandardError.ReadToEnd() | Out-Null
        $process.WaitForExit()
        if ($process.ExitCode -ne 0) {
            throw 'Unable to inject the MyPeople memory credential into container tmpfs.'
        }
        & docker exec $safeContainer test -s $script:SecretPath
        if ($LASTEXITCODE -ne 0) { throw 'Injected MyPeople memory credential is missing.' }
        & docker exec $safeContainer chmod 600 $script:SecretPath
        if ($LASTEXITCODE -ne 0) { throw 'Unable to protect the MyPeople memory credential.' }
    } finally {
        [Console]::InputEncoding = $previousInputEncoding
        [Array]::Clear($credentialBytes, 0, $credentialBytes.Length)
        $secret = $null
    }
    return $script:SecretPath
}

function Clear-MyPeopleMemoryCredentialInContainer {
    param([string]$Container = 'mypeople')
    $safeContainer = Test-MyPeopleMemoryContainerName -Container $Container
    & docker exec $safeContainer python3 -c "from pathlib import Path; Path('$script:SecretPath').unlink(missing_ok=True)"
    if ($LASTEXITCODE -ne 0) { throw 'Unable to clear the MyPeople memory tmpfs credential.' }
}

function Sync-MyPeopleMemoryActivation {
    param([string]$Container = 'mypeople')
    $settings = Get-MyPeopleMemorySettings
    if ($null -eq $settings) {
        Clear-MyPeopleMemoryCredentialInContainer -Container $Container
        return 'disabled'
    }
    $safeContainer = Test-MyPeopleMemoryContainerName -Container $Container
    if ($settings.enabled) {
        Clear-MyPeopleMemoryCredentialInContainer -Container $safeContainer
        throw 'Persistent memory activation is blocked until the credential broker is isolated from workers.'
    }
    try {
        & docker exec $safeContainer /home/mp/mypeople/bin/memory-profile disable --project $settings.projectSlug --server-url $settings.serverUrl
        if ($LASTEXITCODE -ne 0) { throw 'Unable to disable the MyPeople memory ProjectProfile.' }
    } finally {
        Clear-MyPeopleMemoryCredentialInContainer -Container $safeContainer
    }
    return 'disabled'
}

Export-ModuleMember -Function @(
    'Initialize-MyPeopleMemoryStore',
    'Get-MyPeopleMemoryCredentialPath',
    'Save-MyPeopleMemoryCredentialBytes',
    'Get-MyPeopleMemoryCredentialBytes',
    'Set-MyPeopleMemorySettings',
    'Get-MyPeopleMemorySettings',
    'Install-MyPeopleMemoryCredentialInContainer',
    'Clear-MyPeopleMemoryCredentialInContainer',
    'Sync-MyPeopleMemoryActivation'
)
