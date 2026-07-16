param(
    [switch]$Generate,
    [SecureString]$Credential,
    [Parameter(Mandatory)][string]$CloudflareRepository
)

$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'MyPeople.Memory.psm1') -Force

if ($Generate -and $null -ne $Credential) {
    throw 'Choose either -Generate or -Credential.'
}
if (-not $Generate -and $null -eq $Credential) {
    $Credential = Read-Host 'Enter the Cloudflare memory bearer credential' -AsSecureString
}
$repository = [IO.Path]::GetFullPath($CloudflareRepository)
if (-not [IO.Directory]::Exists($repository) -or
    -not [IO.File]::Exists((Join-Path $repository 'wrangler.jsonc'))) {
    throw 'Cloudflare memory repository is invalid.'
}

$token = $null
$bytes = $null
$bstr = [IntPtr]::Zero
$previousInputEncoding = [Console]::InputEncoding
try {
    [Console]::InputEncoding = [Text.UTF8Encoding]::new($false)
    if ($Generate) {
        $random = [byte[]]::new(32)
        $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
        try {
            $rng.GetBytes($random)
            $token = [Convert]::ToBase64String($random).TrimEnd('=').Replace('+', '-').Replace('/', '_')
        } finally {
            $rng.Dispose()
            [Array]::Clear($random, 0, $random.Length)
        }
    } else {
        $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Credential)
        $token = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    }
    $bytes = [Text.Encoding]::UTF8.GetBytes($token)
    Save-MyPeopleMemoryCredentialBytes -CredentialBytes $bytes | Out-Null

    $start = [Diagnostics.ProcessStartInfo]::new()
    $start.FileName = (Get-Command npm.cmd -ErrorAction Stop).Source
    $start.Arguments = 'exec wrangler -- secret put AUTH_TOKEN'
    $start.WorkingDirectory = $repository
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.RedirectStandardInput = $true
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $start
    if (-not $process.Start()) { throw 'Unable to start Wrangler.' }
    $process.StandardInput.Write($token)
    $process.StandardInput.Close()
    $process.StandardOutput.ReadToEnd() | Out-Null
    $process.StandardError.ReadToEnd() | Out-Null
    $process.WaitForExit()
    if ($process.ExitCode -ne 0) {
        throw 'Cloudflare memory secret rotation failed.'
    }

    Write-Output 'Cloudflare memory credential rotated and stored with Windows DPAPI.'
} finally {
    [Console]::InputEncoding = $previousInputEncoding
    if ($null -ne $bytes) { [Array]::Clear($bytes, 0, $bytes.Length) }
    if ($bstr -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
    $token = $null
}
