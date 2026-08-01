param(
    [Parameter(Mandatory)]
    [ValidatePattern('^[0-9a-f]{24}$')]
    [string]$ApprovalId,
    [ValidateRange(30, 900)]
    [int]$ChecksTimeoutSeconds = 900
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$env:GIT_TERMINAL_PROMPT = '0'
$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ('mypeople-ssh-publication-' + [guid]::NewGuid().ToString('N'))
$bundlePath = Join-Path $tempRoot 'source.bundle'
$checkoutPath = Join-Path $tempRoot 'checkout'
$remotePath = Join-Path $tempRoot 'remote'
$bundleInContainer = '/tmp/mypeople-publication-' + [guid]::NewGuid().ToString('N') + '.bundle'

function Invoke-Checked {
    param([Parameter(Mandatory)][string]$File, [Parameter(Mandatory)][string[]]$Arguments)
    $output = (& $File @Arguments 2>&1 | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) { throw "tool_failed:$File" }
    return $output
}

function Assert-SafeSlug([string]$Value) {
    if ($Value -notmatch '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$') { throw 'repository_slug_invalid' }
    return $Value
}

function Assert-SafeBranch([string]$Value) {
    if ($Value -notmatch '^task/[A-Za-z0-9][A-Za-z0-9._/-]{0,126}$' -or $Value.Contains('..') -or $Value.Contains('//')) { throw 'head_branch_invalid' }
    return $Value
}

function Get-Preflight {
    $text = Invoke-Checked 'docker' @('exec', 'mypeople', '/home/mp/mypeople/bin/mp', 'publish', $ApprovalId, '--check')
    $record = $text | ConvertFrom-Json
    if ($record.mode -ne 'pr_merge_when_green') { throw 'approval_mode_invalid' }
    if ($record.status -notin @('approved', 'validating', 'branch_pushed', 'pr_created', 'waiting_checks', 'merge_blocked')) { throw 'approval_state_invalid' }
    if ($record.baseBranch -ne 'main') { throw 'base_branch_invalid' }
    if ($record.commit -notmatch '^[0-9a-f]{40}$') { throw 'commit_invalid' }
    if ($record.headBranch -ne (Assert-SafeBranch $record.headBranch)) { throw 'head_branch_invalid' }
    $repository = ([uri]$record.repository).AbsolutePath.Trim('/').TrimEnd('.git')
    $slug = Assert-SafeSlug $repository
    $record | Add-Member -NotePropertyName repositorySlug -NotePropertyValue $slug
    return $record
}

try {
    New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null
    $preflight = Get-Preflight
    if ($preflight.status -in @('approved', 'validating')) {
        Invoke-Checked 'docker' @('exec', 'mypeople', 'git', '-C', [string]$preflight.workspace, 'bundle', 'create', $bundleInContainer, [string]$preflight.commit) | Out-Null
        Invoke-Checked 'docker' @('cp', "mypeople:$bundleInContainer", $bundlePath) | Out-Null
        Invoke-Checked 'docker' @('exec', 'mypeople', 'rm', '-f', $bundleInContainer) | Out-Null
        Invoke-Checked 'git' @('init', '--quiet', $remotePath) | Out-Null
        Invoke-Checked 'git' @('-C', $remotePath, 'fetch', '--quiet', $bundlePath, [string]$preflight.commit) | Out-Null
        Invoke-Checked 'git' @('-C', $remotePath, 'push', '--porcelain', "git@github.com:$($preflight.repositorySlug).git", "$($preflight.commit):refs/heads/$($preflight.headBranch)") | Out-Null
        Invoke-Checked 'docker' @('exec', 'mypeople', '/home/mp/mypeople/bin/mp', 'publish-branch-complete', $ApprovalId, '--sha', [string]$preflight.commit) | Out-Null
        $preflight = Get-Preflight
    }
    if ($preflight.status -eq 'branch_pushed') {
        $existing = (& gh pr list --repo $preflight.repositorySlug --head $preflight.headBranch --state open --json number,url,state,isDraft,headRefName,baseRefName,headRefOid --limit 1 | Out-String).Trim()
        if ($LASTEXITCODE -ne 0) { throw 'github_pr_list_failed' }
        $candidate = @($existing | ConvertFrom-Json)
        if ($candidate.Count -eq 0) {
            $url = (& gh pr create --draft --repo $preflight.repositorySlug --base main --head $preflight.headBranch --title $preflight.prTitle --body $preflight.prBody | Out-String).Trim()
            if ($LASTEXITCODE -ne 0) { throw 'github_pr_create_failed' }
            $candidate = @((& gh pr view $url --repo $preflight.repositorySlug --json number,url,state,isDraft,headRefName,baseRefName,headRefOid | Out-String).Trim() | ConvertFrom-Json)
        }
        $pr = $candidate[0]
        if ($pr.state -ne 'OPEN' -or $pr.headRefName -ne $preflight.headBranch -or $pr.baseRefName -ne 'main' -or $pr.headRefOid -ne $preflight.commit) { throw 'github_pr_binding_mismatch' }
        Invoke-Checked 'docker' @('exec', 'mypeople', '/home/mp/mypeople/bin/mp', 'publish-pr-complete', $ApprovalId, '--number', [string]$pr.number, '--url', [string]$pr.url, '--head-sha', [string]$pr.headRefOid) | Out-Null
        $preflight = Get-Preflight
    }
    if ($preflight.status -in @('pr_created', 'waiting_checks')) {
        $pr = (& gh pr view $preflight.pullRequest.number --repo $preflight.repositorySlug --json number,url,state,isDraft,headRefName,baseRefName,headRefOid | Out-String).Trim() | ConvertFrom-Json
        if ($pr.headRefOid -ne $preflight.commit -or $pr.baseRefName -ne 'main' -or $pr.state -ne 'OPEN') { throw 'github_pr_binding_mismatch' }
        $deadline = (Get-Date).AddSeconds($ChecksTimeoutSeconds)
        do {
            $checks = (& gh pr checks $pr.number --repo $preflight.repositorySlug --required 2>&1 | Out-String).Trim()
            if ($LASTEXITCODE -eq 0) { break }
            if ($checks -match '(?i)fail|error|cancel') { throw 'required_checks_failed' }
            Start-Sleep -Seconds 10
        } while ((Get-Date) -lt $deadline)
        if ($LASTEXITCODE -ne 0) { throw 'required_checks_timeout' }
        $digestInput = [Text.Encoding]::UTF8.GetBytes("$($preflight.commit)|$($pr.number)|passed")
        $digest = ([Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($digestInput))).ToLowerInvariant()
        Invoke-Checked 'docker' @('exec', 'mypeople', '/home/mp/mypeople/bin/mp', 'publish-checks', $ApprovalId, '--state', 'passed', '--digest', $digest) | Out-Null
        $merge = (& gh pr merge $pr.number --repo $preflight.repositorySlug --$($preflight.mergeMethod) --match-head-commit $preflight.commit --delete-branch=false 2>&1 | Out-String).Trim()
        if ($LASTEXITCODE -ne 0) { throw 'github_pr_merge_failed' }
        $merged = (& gh pr view $pr.number --repo $preflight.repositorySlug --json mergeCommit | Out-String).Trim() | ConvertFrom-Json
        $mergeSha = [string]$merged.mergeCommit.oid
        if ($mergeSha -notmatch '^[0-9a-f]{40}$') { throw 'merge_sha_invalid' }
        Invoke-Checked 'docker' @('exec', 'mypeople', '/home/mp/mypeople/bin/mp', 'publish-merge-complete', $ApprovalId, '--sha', $mergeSha) | Out-Null
    }
    @{ status = 'published_and_merged'; approvalId = $ApprovalId; repository = $preflight.repositorySlug; branch = $preflight.headBranch } | ConvertTo-Json -Compress
} catch {
    Write-Error ('publication_failed:' + $_.Exception.Message)
    exit 1
} finally {
    Remove-Item -LiteralPath $bundlePath -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
    try { & docker exec mypeople rm -f $bundleInContainer *> $null } catch {}
    Remove-Item Env:GIT_TERMINAL_PROMPT -ErrorAction SilentlyContinue
}
