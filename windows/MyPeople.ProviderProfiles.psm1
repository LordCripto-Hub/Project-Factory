$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
    throw 'LOCALAPPDATA is required for the MyPeople provider profile store.'
}

$script:StoreRoot = Join-Path $env:LOCALAPPDATA 'MyPeople'
$script:StateRoot = Join-Path $script:StoreRoot 'state'
$script:CredentialsRoot = Join-Path $script:StoreRoot 'credentials'
$script:HandoffsRoot = Join-Path $script:StoreRoot 'handoffs'
$script:ProfilesPath = Join-Path $script:StateRoot 'provider-profiles.json'
$script:BindingsPath = Join-Path $script:StateRoot 'provider-bindings.json'

function Test-MyPeopleProfileId {
    param([Parameter(Mandatory)][string]$Profile)
    if ($Profile -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$') {
        throw 'Invalid provider profile ID.'
    }
    return $Profile
}

function Protect-MyPeopleDirectory {
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
    $propagation = [Security.AccessControl.PropagationFlags]::None
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
            $propagation,
            $allow
        )
        [void]$acl.AddAccessRule($accessRule)
    }
    $directory.SetAccessControl($acl)
    return $resolved
}

function Initialize-MyPeopleProfileStore {
    [IO.Directory]::CreateDirectory($script:StoreRoot) | Out-Null
    foreach ($path in @(
        $script:StateRoot,
        $script:CredentialsRoot,
        $script:HandoffsRoot
    )) {
        Protect-MyPeopleDirectory -Path $path | Out-Null
    }
    return $script:StoreRoot
}

function Get-MyPeopleProfilePath {
    param(
        [Parameter(Mandatory)][string]$Provider,
        [Parameter(Mandatory)][string]$Profile
    )
    $safeProvider = Test-MyPeopleProfileId -Profile $Provider
    $safeProfile = Test-MyPeopleProfileId -Profile $Profile
    $providerRoot = Join-Path $script:CredentialsRoot $safeProvider
    $profileRoot = Join-Path $providerRoot $safeProfile
    $root = [IO.Path]::GetFullPath($script:CredentialsRoot)
    $resolved = [IO.Path]::GetFullPath($profileRoot)
    if (-not $resolved.StartsWith($root + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Provider profile path escaped the credential store.'
    }
    return $resolved
}

function Read-MyPeopleJson {
    param(
        [Parameter(Mandatory)][string]$Path,
        $Default = $null
    )
    try {
        if (-not [IO.File]::Exists($Path)) { return $Default }
        $raw = [IO.File]::ReadAllText($Path, [Text.Encoding]::UTF8)
        if ([string]::IsNullOrWhiteSpace($raw)) { return $Default }
        return $raw | ConvertFrom-Json
    } catch {
        return $Default
    }
}

function Write-MyPeopleJsonAtomic {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)]$Value
    )
    $resolved = [IO.Path]::GetFullPath($Path)
    $directory = Split-Path -Parent $resolved
    Protect-MyPeopleDirectory -Path $directory | Out-Null
    $temporary = Join-Path $directory ('.{0}.{1}.tmp' -f ([IO.Path]::GetFileName($resolved)), [Guid]::NewGuid().ToString('N'))
    $json = $Value | ConvertTo-Json -Depth 16
    [IO.File]::WriteAllText($temporary, $json + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $temporary -Destination $resolved -Force
}

function ConvertTo-MyPeopleMap {
    param($Value)
    $result = [ordered]@{}
    if ($null -eq $Value) { return $result }
    if ($Value -is [Collections.IDictionary]) {
        foreach ($key in $Value.Keys) { $result[[string]$key] = $Value[$key] }
        return $result
    }
    foreach ($property in $Value.PSObject.Properties) {
        $result[$property.Name] = $property.Value
    }
    return $result
}

function Get-MyPeopleProviderProfiles {
    Initialize-MyPeopleProfileStore | Out-Null
    return Read-MyPeopleJson -Path $script:ProfilesPath -Default ([pscustomobject]@{})
}

function Get-MyPeopleProviderBindings {
    Initialize-MyPeopleProfileStore | Out-Null
    $default = [pscustomobject]@{
        globalProfile = ''
        agentProfiles = [pscustomobject]@{}
    }
    return Read-MyPeopleJson -Path $script:BindingsPath -Default $default
}

function Sync-MyPeopleRuntimeJson {
    param(
        [Parameter(Mandatory)][string]$Source,
        [Parameter(Mandatory)][string]$Destination,
        [string]$Container = 'mypeople'
    )
    & docker exec $Container mkdir -p /home/mp/mypeople/run | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Unable to prepare the MyPeople runtime state directory.' }
    & docker cp $Source (('{0}:{1}' -f $Container, $Destination)) | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Unable to mirror provider metadata into MyPeople.' }
    & docker exec -u 0 $Container chown mp:mp $Destination | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Unable to assign mirrored provider metadata.' }
    & docker exec -u 0 $Container chmod 600 $Destination | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Unable to protect mirrored provider metadata.' }
}

function Set-MyPeopleProviderBindings {
    param(
        [Parameter(Mandatory)]$Bindings,
        [string]$Container = 'mypeople'
    )
    Initialize-MyPeopleProfileStore | Out-Null
    Write-MyPeopleJsonAtomic -Path $script:BindingsPath -Value $Bindings
    Sync-MyPeopleRuntimeJson -Source $script:BindingsPath -Destination '/home/mp/mypeople/run/provider-bindings.json' -Container $Container

}

function Save-MyPeopleCodexCredential {
    param(
        [Parameter(Mandatory)][string]$Profile,
        [Parameter(Mandatory)][string]$SourceAuth
    )
    $safeProfile = Test-MyPeopleProfileId -Profile $Profile
    if (-not [IO.File]::Exists($SourceAuth)) { throw 'Codex authentication source is missing.' }
    Initialize-MyPeopleProfileStore | Out-Null
    $profilePath = Get-MyPeopleProfilePath -Provider 'codex' -Profile $safeProfile
    Protect-MyPeopleDirectory -Path $profilePath | Out-Null
    $destination = Join-Path $profilePath 'auth.json'
    [IO.File]::WriteAllBytes($destination, [IO.File]::ReadAllBytes($SourceAuth))

    $profiles = ConvertTo-MyPeopleMap (Get-MyPeopleProviderProfiles)
    $profiles[$safeProfile] = [ordered]@{
        id = $safeProfile
        provider = 'codex'
        credentialRef = "local://codex/$safeProfile"
        defaultModel = 'gpt-5.6-luna'
        roleModels = [ordered]@{
            boss = 'gpt-5.6-sol'
            nightwatch = 'gpt-5.6-luna'
            engineer = 'gpt-5.6-luna'
        }
        enabled = $true
    }
    Write-MyPeopleJsonAtomic -Path $script:ProfilesPath -Value $profiles
    return $profiles[$safeProfile]
}

function Install-MyPeopleCodexProfileInContainer {
    param(
        [Parameter(Mandatory)][string]$Profile,
        [string]$Container = 'mypeople'
    )
    $safeProfile = Test-MyPeopleProfileId -Profile $Profile
    $profilePath = Get-MyPeopleProfilePath -Provider 'codex' -Profile $safeProfile
    $authPath = Join-Path $profilePath 'auth.json'
    if (-not [IO.File]::Exists($authPath)) { throw 'Saved Codex profile is missing.' }
    $runtimeHome = "/home/mp/mypeople/run/provider-homes/codex/$safeProfile"
    & docker exec $Container mkdir -p $runtimeHome | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Unable to create the Codex runtime profile.' }
    & docker exec $Container chmod 700 $runtimeHome | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Unable to protect the Codex runtime profile.' }
    & docker cp $authPath (('{0}:{1}/auth.json' -f $Container, $runtimeHome)) | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Unable to install the Codex runtime credential.' }
    & docker exec -u 0 $Container chown mp:mp "$runtimeHome/auth.json" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Unable to assign the Codex runtime credential.' }
    & docker exec -u 0 $Container chmod 600 "$runtimeHome/auth.json" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Unable to protect the Codex runtime credential.' }
    Sync-MyPeopleRuntimeJson -Source $script:ProfilesPath -Destination '/home/mp/mypeople/run/provider-profiles.json' -Container $Container

    return $runtimeHome
}

function Invoke-MyPeopleHiddenProcess {
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [Parameter(Mandatory)][string[]]$ArgumentList,
        [int]$TimeoutSeconds = 45
    )
    $startArguments = @{
        FilePath = $FilePath
        ArgumentList = $ArgumentList
        WindowStyle = 'Hidden'
        PassThru = $true
    }
    $process = Start-Process @startArguments
    if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
        try { $process.Kill() } catch { }
        throw "Provider validation timed out after $TimeoutSeconds seconds."
    }
    return $process.ExitCode
}

function Test-MyPeopleCodexProfileInContainer {
    param(
        [Parameter(Mandatory)][string]$Profile,
        [string]$Container = 'mypeople'
    )
    $safeProfile = Test-MyPeopleProfileId -Profile $Profile
    $runtimeHome = "/home/mp/mypeople/run/provider-homes/codex/$safeProfile"
    $probe = 'PROFILE_OK'
    $exitCode = Invoke-MyPeopleHiddenProcess -FilePath 'docker' -ArgumentList @(
        'exec', '-e', "CODEX_HOME=$runtimeHome", $Container,
        'codex', 'exec', '--ephemeral', '--ignore-user-config', '--ignore-rules',
        '--skip-git-repo-check', '--sandbox', 'read-only', '--color', 'never',
        '-C', '/home/mp/mypeople', $probe
    )
    if ($exitCode -ne 0) { throw "Codex profile validation failed: $safeProfile" }
    return $true
}
function Get-MyPeopleProviderAdapter {
    param([Parameter(Mandatory)][string]$Provider)
    if ($Provider -ne 'codex') { throw "Unsupported provider: $Provider" }
    return [ordered]@{
        InspectSource = {
            param([string]$Profile)
            $codexCommand = Get-Command codex.cmd -ErrorAction SilentlyContinue
            if ($null -eq $codexCommand) {
                $codexCommand = Get-Command codex -ErrorAction Stop
            }
            $exitCode = Invoke-MyPeopleHiddenProcess -FilePath $codexCommand.Source -ArgumentList @('login', 'status')
            if ($exitCode -ne 0) { throw 'The current Codex login is not valid.' }
            return $true
        }
        SaveProfile = {
            param([string]$Profile, [string]$SourceAuth)
            Save-MyPeopleCodexCredential -Profile $Profile -SourceAuth $SourceAuth
        }
        ActivateProfile = {
            param([string]$Profile, [string]$Container = 'mypeople')
            Install-MyPeopleCodexProfileInContainer -Profile $Profile -Container $Container
        }
        ValidateRuntime = {
            param([string]$Profile, [string]$Container = 'mypeople')
            Test-MyPeopleCodexProfileInContainer -Profile $Profile -Container $Container
        }
        RuntimeEnvironment = {
            param([string]$Profile)
            $safeProfile = Test-MyPeopleProfileId -Profile $Profile
            return @{ CODEX_HOME = "/home/mp/mypeople/run/provider-homes/codex/$safeProfile" }
        }
        LaunchArguments = {
            param([string]$Profile)
            Test-MyPeopleProfileId -Profile $Profile | Out-Null
            return @()
        }
        RestorePrevious = {
            param([string]$Profile, [string]$Container = 'mypeople')
            if (-not [string]::IsNullOrWhiteSpace($Profile)) {
                Install-MyPeopleCodexProfileInContainer -Profile $Profile -Container $Container
            }
        }
    }
}

Export-ModuleMember -Function @(
    'Initialize-MyPeopleProfileStore',
    'Test-MyPeopleProfileId',
    'Get-MyPeopleProfilePath',
    'Protect-MyPeopleDirectory',
    'Read-MyPeopleJson',
    'Write-MyPeopleJsonAtomic',
    'Get-MyPeopleProviderAdapter',
    'Get-MyPeopleProviderProfiles',
    'Save-MyPeopleCodexCredential',
    'Install-MyPeopleCodexProfileInContainer',
    'Test-MyPeopleCodexProfileInContainer',
    'Get-MyPeopleProviderBindings',
    'Set-MyPeopleProviderBindings'
)
