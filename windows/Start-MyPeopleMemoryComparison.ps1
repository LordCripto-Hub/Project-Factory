[CmdletBinding()]
param(
    [ValidateSet('Preflight','Offline','Paired','Status','Cleanup','Report')]
    [string]$Action = 'Preflight',
    [string]$RunId = '',
    [string]$ConfirmedRunId = '',
    [switch]$Execute,
    [switch]$ConfirmLiveRun,
    [string]$Container = 'mypeople',
    [int]$TimeoutSeconds = 900
)

$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$casesPath = Join-Path $projectRoot 'experiments\memory-gate-b\comparison\cases.json'
$datasetPath = Join-Path $projectRoot 'experiments\memory-gate-b\datasets\project-factory-history-039a62988625'
$lockPath = Join-Path $projectRoot 'experiments\memory-gate-b\docker\history-hybrid-039a62988625.dataset-lock.json'
$questionsPath = Join-Path $datasetPath 'questions.jsonl'
$offlineReport = Join-Path $projectRoot 'experiments\memory-gate-b\reports\comparison-offline-039a62988625.json'
$sourceSha = '039a62988625369f3f86c055cd476b0080395daa'
$model = 'gpt-5.6-luna'
$schedule = @(
    @{ alias = 'cmp-exact-01'; arms = @('baseline','memory') },
    @{ alias = 'cmp-temporal-01'; arms = @('memory','baseline') },
    @{ alias = 'cmp-contradiction-01'; arms = @('baseline','memory') }
)

function Invoke-Docker {
    param([Parameter(Mandatory)][string[]]$Arguments, [switch]$AllowFailure)
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $output = @(& docker @Arguments 2>&1)
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousPreference
    }
    if (-not $AllowFailure -and $exitCode -ne 0) {
        throw "docker_command_failed: $($output -join ' ')"
    }
    [pscustomobject]@{ ExitCode = $exitCode; Output = ($output -join "`n") }
}

function Invoke-DockerPython {
    param(
        [Parameter(Mandatory)][string]$Source,
        [string[]]$Arguments = @(),
        [switch]$AllowFailure
    )
    $dockerArguments = @('exec', '-i', $Container, 'python3', '-') + $Arguments
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $output = @($Source | & docker @dockerArguments 2>&1)
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousPreference
    }
    if (-not $AllowFailure -and $exitCode -ne 0) {
        throw "docker_python_failed: $($output -join ' ')"
    }
    [pscustomobject]@{ ExitCode = $exitCode; Output = ($output -join "`n") }
}

function Invoke-Mp {
    param([Parameter(Mandatory)][string[]]$Arguments, [switch]$AllowFailure)
    # Contract markers: mp spawn, mp kill, memory-comparison abort.
    Invoke-Docker -Arguments (@('exec', $Container, '/home/mp/mypeople/bin/mp') + $Arguments) -AllowFailure:$AllowFailure
}

function Invoke-TodoMachine {
    param([Parameter(Mandatory)][hashtable]$Payload)
    $json = $Payload | ConvertTo-Json -Depth 12 -Compress
    $encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($json))
    $python = @'
import base64,json,os,sys
sys.path.insert(0,"/home/mp/mypeople/bin")
from mpcommon import ENV,http_json
payload=json.loads(base64.b64decode(sys.argv[1]).decode("utf-8"))
print(json.dumps(http_json("/todo/update","POST",payload,base="http://127.0.0.1:9933",token=ENV.get("QUEUE_SECRET","")),separators=(",",":")))
'@
    $response = Invoke-DockerPython -Source $python -Arguments @($encoded)
    $response.Output | ConvertFrom-Json
}

function Get-ContainerSnapshot {
    $raw = Invoke-Docker -Arguments @('inspect', $Container, '--format', '{{json .State}}')
    $state = $raw.Output | ConvertFrom-Json
    if (-not $state.Running) { throw 'docker_unhealthy' }
    $inspect = Invoke-Docker -Arguments @('inspect', $Container, '--format', '{{.RestartCount}}')
    [pscustomobject]@{ ContainerId = $state.Pid; RestartCount = [int]$inspect.Output }
}

function Test-HttpHealth {
    foreach ($url in @('http://127.0.0.1:9933/','http://127.0.0.1:9900/')) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 10
            if ($response.StatusCode -ne 200) { throw "health_status_$($response.StatusCode)" }
        } catch { throw "health_failed: $url" }
    }
}

function Get-OfflineBinding {
    if (-not (Test-Path -LiteralPath $offlineReport -PathType Leaf)) { throw 'offline_receipt_missing' }
    $receipt = Get-Content -LiteralPath $offlineReport -Raw | ConvertFrom-Json
    if ($receipt.dataset.source_sha -ne $sourceSha) { throw 'wrong_project' }
    if (-not $receipt.fixture_sha256 -or -not $receipt.logical_digest) { throw 'offline_receipt_invalid' }
    if ($receipt.passed -ne $true) { throw 'offline_qualification_failed' }
    [pscustomobject]@{
        fixture_sha256 = [string]$receipt.fixture_sha256
        offline_digest = [string]$receipt.logical_digest
    }
}

function Get-CaseQuestion {
    param([Parameter(Mandatory)][string]$CaseAlias)
    $caseDocument = Get-Content -LiteralPath $casesPath -Raw | ConvertFrom-Json
    $case = @($caseDocument.cases | Where-Object { $_.alias -eq $CaseAlias })
    if ($case.Count -ne 1 -or -not $case[0].question_id) { throw 'comparison_question_missing' }
    $question = @(Get-Content -LiteralPath $questionsPath | ForEach-Object { $_ | ConvertFrom-Json } | Where-Object { $_.question_id -eq $case[0].question_id })
    if ($question.Count -ne 1 -or [string]::IsNullOrWhiteSpace($question[0].query)) { throw 'comparison_question_missing' }
    [string]$question[0].query
}

function Assert-Preflight {
    $snapshot = Get-ContainerSnapshot
    Test-HttpHealth
    if (-not (Test-Path -LiteralPath $datasetPath -PathType Container)) { throw 'dataset_missing' }
    $cases = Get-Content -LiteralPath $casesPath -Raw | ConvertFrom-Json
    if ($cases.dataset.source_sha -ne $sourceSha) { throw 'wrong_project' }
    # Exact live binding: git rev-parse HEAD in the durable project workspace.
    $workspace = Invoke-Docker -Arguments @('exec', $Container, 'git', '-C', '/home/mp/workspaces/project-factory', 'rev-parse', 'HEAD')
    if ($workspace.Output.Trim() -ne $sourceSha) { throw 'workspace_source_mismatch' }
    # git status --porcelain: reject uncommitted project state before comparison.
    $workspaceStatus = Invoke-Docker -Arguments @('exec', $Container, 'git', '-C', '/home/mp/workspaces/project-factory', 'status', '--porcelain')
    if (-not [string]::IsNullOrWhiteSpace($workspaceStatus.Output)) { throw 'workspace_dirty' }
    $flag = Invoke-Docker -Arguments @('exec', $Container, 'printenv', 'MYPEOPLE_MEMORY_COMPARISON_ENABLED') -AllowFailure
    if ($flag.ExitCode -ne 0 -or $flag.Output.Trim() -ne '1') { throw 'MYPEOPLE_MEMORY_COMPARISON_ENABLED_required' }
    $provider = Invoke-Docker -Arguments @('exec', $Container, 'codex', 'login', 'status') -AllowFailure
    if ($provider.ExitCode -ne 0) { throw 'provider_unavailable' }
    $resourceProbe = @'
import json,pathlib,sys
root=pathlib.Path("/home/mp/mypeople/run/memory-comparison/runs")
active=[] if not root.exists() else [p for p in root.glob("*/state.json") if json.loads(p.read_text()).get("status") not in {"completed","aborted"}]
inbox=pathlib.Path("/home/mp/mypeople/run/memory-comparison/inbox")
pending=[] if not inbox.exists() else list(inbox.iterdir())
sys.exit(1 if active or pending else 0)
'@
    $resources = Invoke-DockerPython -Source $resourceProbe -AllowFailure
    if ($resources.ExitCode -ne 0) { throw 'comparison_resources_present' }
    $sidecar = Invoke-Docker -Arguments @('ps', '--filter', 'label=com.docker.compose.service=memory-gate-b', '--filter', 'health=healthy', '--format', '{{.ID}}') -AllowFailure
    if ($sidecar.ExitCode -ne 0 -or [string]::IsNullOrWhiteSpace($sidecar.Output)) { throw 'memory_sidecar_unavailable' }
    $binding = Get-OfflineBinding
    [pscustomobject]@{
        status = 'offline_qualified'
        restart_count = $snapshot.RestartCount
        fixture_sha256 = $binding.fixture_sha256
        offline_digest = $binding.offline_digest
        source_sha = $sourceSha
    }
}

function Assert-LiveConfirmation {
    if (-not $Execute -or -not $ConfirmLiveRun -or [string]::IsNullOrWhiteSpace($RunId) -or $RunId -ne $ConfirmedRunId) {
        throw 'execution_confirmation_mismatch'
    }
    if ($RunId -notmatch '^[A-Za-z0-9_-]{1,64}$') { throw 'invalid_run_id' }
}

function Wait-ComparisonResult {
    param([string]$RemoteDirectory)
    $remote = "$RemoteDirectory/result-envelope.json"
    $deadline = [DateTimeOffset]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTimeOffset]::UtcNow -lt $deadline) {
        $probe = Invoke-Docker -Arguments @('exec', $Container, 'test', '-s', $remote) -AllowFailure
        if ($probe.ExitCode -eq 0) { return $remote }
        Start-Sleep -Seconds 2
    }
    throw 'result_timeout'
}

function Convert-ClosedResult {
    param([string]$CaseAlias, [string]$RemoteResult, [long]$WallTimeMs)
    $temp = Join-Path ([IO.Path]::GetTempPath()) ("mypeople-comparison-" + [guid]::NewGuid().ToString('N') + '.json')
    try {
        Invoke-Docker -Arguments @('cp', "$Container`:$RemoteResult", $temp) | Out-Null
        $result = Get-Content -LiteralPath $temp -Raw | ConvertFrom-Json
        $required = @('decision_id','selected_evidence_ids','rejected_evidence_ids','commands','conclusion')
        if (@($result.psobject.Properties.Name).Count -ne $required.Count -or @($required | Where-Object { $_ -notin $result.psobject.Properties.Name }).Count) {
            throw 'score_refused'
        }
        $scoreTemp = "$temp.scored.json"
        $scoreScript = Join-Path $projectRoot 'experiments\memory-gate-b\scripts\score_memory_comparison_result.py'
        & python $scoreScript --cases $casesPath --case-alias $CaseAlias --input $temp --output $scoreTemp
        if ($LASTEXITCODE -ne 0) { throw 'score_refused' }
        $score = Get-Content -LiteralPath $scoreTemp -Raw | ConvertFrom-Json
        [pscustomobject]@{
            score_receipt = $score
            metrics = [ordered]@{
                wall_time_ms = $WallTimeMs
                retrieval_latency_ms = 'not_measured'
                memory_context_tokens_estimated = 'not_measured'
                rework_count = 0
                provider_tokens = 'not_measured'
            }
        }
    } finally {
        Remove-Item -LiteralPath $temp, "$temp.scored.json" -Force -ErrorAction SilentlyContinue
    }
}

function Remove-ArmResources {
    param([string]$WorkerId, [string]$CardId, [string]$RemoteDirectory)
    Invoke-Mp -Arguments @('kill', $WorkerId, '--reason', 'operator-request') -AllowFailure | Out-Null
    Invoke-TodoMachine -Payload @{ 'op' = 'del'; id = $CardId } | Out-Null
    Invoke-Docker -Arguments @('exec', $Container, 'rm', '-rf', $RemoteDirectory) | Out-Null
    $workerAbsent = (Invoke-Mp -Arguments @('peek', $WorkerId) -AllowFailure).ExitCode -ne 0
    $cardAbsent = (Invoke-TodoMachine -Payload @{ 'op' = 'del'; id = $CardId }).error -eq 'unknown_task'
    $tempAbsent = (Invoke-Docker -Arguments @('exec', $Container, 'test', '!', '-e', $RemoteDirectory) -AllowFailure).ExitCode -eq 0
    if (-not ($workerAbsent -and $cardAbsent -and $tempAbsent)) { throw 'cleanup_verification_failed' }
    Invoke-Mp -Arguments @('memory-comparison','cleanup',$RunId,'--worker-absent','--card-absent','--conversation-retired','--temp-artifacts-absent') | Out-Null
    # Evidence field names: worker_absent, card_absent, conversation_retired, temp_artifacts_absent.
}

function Stop-ComparisonRun {
    param([string]$Code, [string]$WorkerId = '', [string]$CardId = '', [string]$RemoteDirectory = '')
    if ($RunId) { Invoke-Mp -Arguments @('memory-comparison','abort',$RunId,'--code',$Code) -AllowFailure | Out-Null }
    if ($WorkerId) { Invoke-Mp -Arguments @('kill',$WorkerId,'--reason','operator-request') -AllowFailure | Out-Null }
    if ($CardId) { Invoke-TodoMachine -Payload @{ 'op' = 'del'; id = $CardId } | Out-Null }
    if ($RemoteDirectory) { Invoke-Docker -Arguments @('exec',$Container,'rm','-rf',$RemoteDirectory) -AllowFailure | Out-Null }
}

function Invoke-PairedRun {
    Assert-LiveConfirmation
    $preflight = Assert-Preflight
    Invoke-Mp -Arguments @('memory-comparison','init',$RunId,'--cases-file','/home/mp/mypeople/experiments/memory-gate-b/comparison/cases.json','--fixture-sha',$preflight.fixture_sha256,'--offline-digest',$preflight.offline_digest) | Out-Null
    foreach ($pair in $schedule) {
        foreach ($arm in $pair.arms) {
            $nonce = [guid]::NewGuid().ToString('N')
            $workerId = "main:cmp-$nonce"
            $conversationId = "conversation-$nonce"
            $remoteDirectory = "/home/mp/mypeople/run/memory-comparison/inbox/$RunId/$($pair.alias)-$arm-$nonce"
            $cardId = ''
            try {
                $question = Get-CaseQuestion -CaseAlias $pair.alias
                $deadline = [DateTimeOffset]::UtcNow.AddSeconds($TimeoutSeconds).ToUnixTimeSeconds()
                $card = Invoke-TodoMachine -Payload @{
                    op = 'add'; text = "Synthetic Gate B comparison $($pair.alias) $arm"; test = $true
                    projectSlug = 'project-factory'; contextQuestion = $question
                    memoryCanary = ($arm -eq 'memory'); evidencePolicy = 'optional'
                    experiment = @{ memory_comparison = @{ experiment_id = $RunId; case_alias = $pair.alias; arm = $arm; cleanup_deadline = $deadline } }
                }
                $cardId = [string]$card.id
                if (-not $cardId) { throw 'card_creation_failed' }
                Invoke-Docker -Arguments @('exec',$Container,'mkdir','-p',$remoteDirectory) | Out-Null
                $spawn = @('spawn',$workerId,'--backend','codex','--model',$model,'--boss','main:Boss','--owner-task',$cardId)
                if ($arm -eq 'baseline') { $spawn += '--without-memory' }
                Invoke-Mp -Arguments $spawn | Out-Null # mp spawn --backend codex --owner-task --without-memory
                Invoke-Mp -Arguments @('memory-comparison','start-arm',$RunId,'--case-alias',$pair.alias,'--arm',$arm,'--worker-id',$workerId,'--card-id',$cardId,'--conversation-id',$conversationId) | Out-Null
                $started = [Diagnostics.Stopwatch]::StartNew()
                $message = "Return only the closed comparison JSON envelope. Write it atomically to $remoteDirectory/result-envelope.json. Do not include prose, credentials, raw prompts, or private reasoning."
                Invoke-Mp -Arguments @('send',$workerId,$message) | Out-Null
                $remoteResult = Wait-ComparisonResult -RemoteDirectory $remoteDirectory
                $started.Stop()
                $closed = Convert-ClosedResult -CaseAlias $pair.alias -RemoteResult $remoteResult -WallTimeMs $started.ElapsedMilliseconds
                if ($closed.score_receipt.harmful) { throw 'score_refused' }
                $hostResult = Join-Path ([IO.Path]::GetTempPath()) ("result-" + [guid]::NewGuid().ToString('N') + '.json')
                try {
                    $json = $closed | ConvertTo-Json -Depth 12 -Compress
                    [IO.File]::WriteAllText($hostResult, $json, [Text.UTF8Encoding]::new($false))
                    Invoke-Docker -Arguments @('cp',$hostResult,"$Container`:$remoteDirectory/scored-result.json") | Out-Null
                    Invoke-Mp -Arguments @('memory-comparison','submit-result',$RunId,'--case-alias',$pair.alias,'--arm',$arm,'--result-file',"$remoteDirectory/scored-result.json") | Out-Null
                } finally { Remove-Item -LiteralPath $hostResult -Force -ErrorAction SilentlyContinue }
                Remove-ArmResources -WorkerId $workerId -CardId $cardId -RemoteDirectory $remoteDirectory
                $now = Get-ContainerSnapshot
                if ($now.RestartCount -ne $preflight.restart_count) { throw 'restart_detected' }
            } catch {
                $code = if ($_.Exception.Message -match 'project') { 'wrong_project' } elseif ($_.Exception.Message -match 'provider') { 'provider_error' } else { $_.Exception.Message -replace '[^A-Za-z0-9_-]','_' }
                Stop-ComparisonRun -Code $code -WorkerId $workerId -CardId $cardId -RemoteDirectory $remoteDirectory
                throw
            }
        }
        Invoke-Mp -Arguments @('memory-comparison','complete-pair',$RunId,'--case-alias',$pair.alias) | Out-Null
    }
    Invoke-Mp -Arguments @('memory-comparison','complete-run',$RunId) | Out-Null
    (Invoke-Mp -Arguments @('memory-comparison','summary',$RunId)).Output | ConvertFrom-Json
}

switch ($Action) {
    'Preflight' { Assert-Preflight | ConvertTo-Json -Compress }
    'Offline' { & python (Join-Path $projectRoot 'experiments\memory-gate-b\scripts\run_memory_comparison_offline.py') --dataset $datasetPath --lock $lockPath --cases $casesPath }
    'Paired' { Invoke-PairedRun | ConvertTo-Json -Depth 12 -Compress }
    'Status' { if (-not $RunId) { throw 'run_id_required' }; (Invoke-Mp -Arguments @('memory-comparison','status',$RunId)).Output }
    'Cleanup' { Assert-LiveConfirmation; Stop-ComparisonRun -Code 'operator_cleanup'; '{"ok":true,"status":"cleanup_requested"}' }
    'Report' { if (-not $RunId) { throw 'run_id_required' }; (Invoke-Mp -Arguments @('memory-comparison','summary',$RunId)).Output }
}
