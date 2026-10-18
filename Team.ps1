[CmdletBinding()]
param(
    [ValidateSet('menu', 'status', 'start', 'stop', 'watch', 'doctor', 'reports', 'inbox', 'help', 'initialize', 'retry', 'next', 'commit', 'publish', 'recover', 'details')]
    [string]$Action = 'menu',
    [switch]$Resume,
    [switch]$AdoptDirty,
    [string]$Message
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Controller = Join-Path $PSScriptRoot 'team.py'
$Runtime = Join-Path $ProjectRoot '.supervisor\team-v2'

function Show-TeamHelp {
    Write-Host @'
AfterDark agent team helper

The coordinator selects agents by workflow stage, rather than running every
agent continuously. Status, reports, doctor and inbox do not start paid work.
Starting the team runs Codex using your existing login and consumes account quota.
Workers prepare local changes. The independent guardian can commit and publish
only after exact-snapshot review, QA and release gates pass.
Manual Publish remains available; authorized automatic publishing uses the same checks.
Missing local browser/runtime tools are delegated to the environment engineer.
Failed preparation goes to the technical lead for diagnosis and an ordered
alternative strategy. All roles share the project context and current evidence.
Status shows environment_engineer while recovery runs; QA resumes automatically
only after readiness evidence is validated. No manual browser connection is needed.

First run: choose Doctor, then Initialize. If existing changes are intentional,
use Initialize and adopt existing work. Adopted work is reviewed, not auto-committed.
Then Start; use Resume only after a deliberate team stop. Legacy controller STOP
files are preserved. Stop requests a safe shutdown; inspect status before editing.
After review gates pass, stop the coordinator and use Commit for a local commit.
Commit shows the reviewed snapshot and requires typing COMMIT. Next schedules a
clean committed next batch; Retry reopens a blocked stage after its cause is fixed.
Publish requires typing the full commit SHA and does not run automatically.

Commands (from the repository):
  .\Team.cmd -Action status
  .\Team.cmd -Action doctor
  .\Team.cmd -Action initialize -AdoptDirty
  .\Team.cmd -Action start -Resume
  .\Team.cmd -Action watch
  .\Team.cmd -Action inbox -Message "Describe an observed issue"
  .\Team.cmd -Action stop
  .\Team.cmd -Action commit
  .\Team.cmd -Action retry
  .\Team.cmd -Action recover
  .\Team.cmd -Action next
  .\Team.cmd -Action publish

Live watch shows current commands, elapsed time, quality gates, the last completed
report evidence and recent handoffs in separate sections. D shows full reports.
Raw shell commands and command output are not displayed.
Live watch: Ctrl+C to leave. Leaving watch does not stop the team.
Controller output: .supervisor/team-v2/controller.log and controller.err
Never enter private keys, passwords or production secrets into issue reports.
'@
}

function Invoke-TeamCommand {
    param([string[]]$CommandArguments)
    if (-not (Test-Path -LiteralPath $Controller -PathType Leaf)) {
        throw "Controller not found: $Controller"
    }
    $PythonCommand = Get-Command python -CommandType Application -ErrorAction Stop | Select-Object -First 1
    Push-Location -LiteralPath $ProjectRoot
    try {
        if ($CommandArguments[0] -eq 'reports' -and $CommandArguments.Count -eq 1) {
            & $PythonCommand.Source $Controller @CommandArguments | ForEach-Object {
                Write-Output ('-' * 72)
                Write-Output $_
            }
        }
        else { & $PythonCommand.Source $Controller @CommandArguments }
        $CommandExit = $LASTEXITCODE
        if ($CommandExit -ne 0) {
            throw "Team command '$($CommandArguments -join ' ')' failed with exit code $CommandExit."
        }
    }
    finally { Pop-Location }
}

function ConvertTo-WindowsArgument {
    param([string]$Value)
    # Windows command-line quoting: escape backslashes preceding quotes or the end.
    return '"' + [regex]::Replace([regex]::Replace($Value, '(\\*)"', '$1$1\"'), '(\\+)$', '$1$1') + '"'
}

function Start-TeamController {
    param([bool]$ShouldResume)
    Invoke-TeamCommand -CommandArguments @('doctor')
    $StopFile=Join-Path $Runtime 'STOP'
    if (Test-Path -LiteralPath $StopFile) {
        if (-not $ShouldResume) { throw 'Owner STOP exists. Use Resume to restart deliberately.' }
        Move-Item -LiteralPath $StopFile -Destination (Join-Path $Runtime ('STOP.archived-'+[guid]::NewGuid().ToString()))
    }
    & (Join-Path $PSScriptRoot 'Install-Guardian.ps1')
    Start-Sleep -Seconds 3
    Invoke-TeamCommand -CommandArguments @('status')
}

function Show-TeamStatus {
    $JsonLines = Invoke-TeamCommand -CommandArguments @('status', '--json')
    $State = ($JsonLines -join [Environment]::NewLine) | ConvertFrom-Json
    $Line = '=' * 72
    $Running = if ($State.controller_alive -eq $true) { 'RUNNING' } elseif ($null -eq $State.controller_alive) { 'UNKNOWN' } else { 'STOPPED' }
    $Agent = if ($State.active_role -and $State.controller_alive -eq $true) { $State.active_role } else { '-' }
    $StageNames = @{
        qa='Testing user journeys'; code_reviewer='Reviewing source changes'
        developer='Implementing changes'; environment_engineer='Preparing test environment'
        technical_lead='Diagnosing recovery'; devops='Checking release readiness'
        ready_for_commit='Ready to commit'; release_ready='Ready to publish'
        published='Waiting for deployment verification'; release_verified='Deployment verified'
        needs_attention='Needs attention'; waiting_for_quota='Waiting for quota'
        planner='Planning work'; idle='Waiting for work'; schedule='Selecting next work'
    }
    $Stage = if ($StageNames.ContainsKey([string]$State.stage)) { $StageNames[[string]$State.stage] } else { $State.stage }
    Write-Host "`n$Line" -ForegroundColor DarkCyan
    Write-Host ('TEAM STATUS   {0}' -f (Get-Date -Format 'HH:mm:ss')) -ForegroundColor Cyan
    Write-Host $Line -ForegroundColor DarkCyan
    Write-Host ('  Team       {0,-12} Task  {1}' -f $Running, $State.task)
    Write-Host ('  Stage      {0}' -f $Stage)
    Write-Host ('  Agent      {0}' -f $Agent)
    Write-Host ('  Website    {0}' -f $State.health.status)
    Write-Host ('-' * 72) -ForegroundColor DarkGray
    Write-Host '  Quality gates' -ForegroundColor Cyan
    foreach ($Role in @('code_reviewer','qa','devops')) {
        $Receipt = $State.receipts.$Role
        $Verdict = 'Pending'
        if ($Receipt -and $Receipt.snapshot -eq $State.snapshot -and $Receipt.report.status -eq 'passed') { $Verdict = 'Passed' }
        if ($Agent -eq $Role) { $Verdict = 'In progress' }
        Write-Host ('    {0,-16} {1}' -f $Role, $Verdict)
    }
    if ($State.stage -in @('needs_attention','waiting_for_quota')) {
        Write-Host ('-' * 72) -ForegroundColor DarkGray
        $Reason = if ($State.reason -like '*changed source*') { 'Source changed during a check; a fresh review is required.' } else { [string]$State.reason }
        Write-Host ('  Action needed: {0}' -f $Reason) -ForegroundColor Yellow
    }
    Write-Host ('-' * 72) -ForegroundColor DarkGray
    Write-Host '  5 Live activity   |   D Full reports   |   --help All options' -ForegroundColor DarkGray
    Write-Host "$Line`n" -ForegroundColor DarkCyan
}

function Invoke-TeamAction {
    param([string]$SelectedAction, [bool]$ShouldResume = $false, [bool]$ShouldAdopt = $false)
    switch ($SelectedAction) {
        'status' { Show-TeamStatus }
        'help' { Show-TeamHelp; Show-TeamOptions }
        'details' { Invoke-TeamCommand -CommandArguments @('reports', '--details') }
        'commit' {
            $State = Get-TeamStateForManualAction
            if ($State.stage -ne 'ready_for_commit') { throw 'Commit requires ready_for_commit. Complete the review gates first.' }
            if ([string]::IsNullOrWhiteSpace($State.snapshot)) { throw 'Reviewed snapshot is missing.' }
            Write-Host "Reviewed snapshot: $($State.snapshot)"
            Write-Host "Summary: $($State.last_summary)"
            Write-Host "Reason: $($State.reason)"
            $Subject = Read-Host 'Enter a concise English commit subject'
            if ([string]::IsNullOrWhiteSpace($Subject)) { throw 'A commit subject is required.' }
            $Confirmation = Read-Host 'Type COMMIT to create this local commit (no push)'
            if ($Confirmation -cne 'COMMIT') { Write-Host 'Commit cancelled.'; return }
            Invoke-TeamCommand -CommandArguments @('commit', '--snapshot', $State.snapshot, '--message', $Subject)
        }
        'publish' {
            $State = Get-TeamStateForManualAction
            if ($State.stage -ne 'release_ready') { throw 'Publish requires a reviewed local commit in release_ready.' }
            if ([string]::IsNullOrWhiteSpace($State.commit)) { throw 'Release commit is missing.' }
            Write-Host "Release commit: $($State.commit)"
            Write-Host "Summary: $($State.last_summary)"
            Write-Warning 'This pushes to origin/main and triggers actual Oracle production deployment.'
            $Confirmation = Read-Host 'Type the full release commit SHA to publish, or Enter to cancel'
            if ($Confirmation -cne $State.commit) { Write-Host 'Publish cancelled.'; return }
            Invoke-TeamCommand -CommandArguments @('publish', '--commit', $State.commit, '--confirm-production')
        }
        'retry' {
            $State = Get-TeamStateForManualAction
            if ($State.stage -notin @('needs_attention', 'waiting_for_quota')) { throw 'Retry requires a needs_attention or waiting_for_quota stage.' }
            Invoke-TeamCommand -CommandArguments @('retry')
            Write-Host 'Stage reopened. Use Start / Resume when ready; no worker was started.'
        }
        'next' {
            $State = Get-TeamStateForManualAction
            if ($State.stage -notin @('release_ready', 'published')) { throw 'Next requires clean committed release_ready or published work.' }
            Invoke-TeamCommand -CommandArguments @('next')
            Write-Host 'Next batch scheduled. Use Start / Resume when ready; no worker was started.'
        }
        'start' { Start-TeamController -ShouldResume $ShouldResume }
        'inbox' {
            $IssueText = $Message
            if ([string]::IsNullOrWhiteSpace($IssueText)) { $IssueText = Read-Host 'Describe the issue, steps and expected behavior' }
            if ([string]::IsNullOrWhiteSpace($IssueText)) { throw 'An issue description is required.' }
            Invoke-TeamCommand -CommandArguments @('inbox', '--text', $IssueText)
        }
        'initialize' {
            $InitializeArguments = @('initialize')
            if ($ShouldAdopt) { $InitializeArguments += '--adopt-dirty' }
            Invoke-TeamCommand -CommandArguments $InitializeArguments
        }
        'watch' { Invoke-TeamCommand -CommandArguments @('watch', '--interval', '30') }
        default { Invoke-TeamCommand -CommandArguments @($SelectedAction) }
    }
}

function Get-TeamStateForManualAction {
    $JsonLines = Invoke-TeamCommand -CommandArguments @('status', '--json')
    $State = ($JsonLines -join [Environment]::NewLine) | ConvertFrom-Json
    if ($State.lock -or $State.controller_status -eq 'running') {
        throw 'Stop the coordinator and wait for process exit before this action. Use Stop, then Status.'
    }
    return $State
}

function Show-TeamOptions {
    Write-Host @'

1  Status                  2  Start
3  Resume after stop       4  Stop safely
5  Live work details       6  Doctor / readiness checks
7  List reports            8  Submit issue to planner
D  Full report evidence, findings and limitations
9  Help                    I  Initialize clean work
A  Initialize and adopt existing dirty work for review
C  Commit reviewed work     R  Retry a blocked stage
N  Schedule next batch      P  Publish reviewed release to production
T  Ask technical lead to recover a local tooling blocker
0  Exit helper (team keeps running)
'@
}

if ($Action -ne 'menu') {
    try {
        Invoke-TeamAction -SelectedAction $Action -ShouldResume $Resume.IsPresent -ShouldAdopt $AdoptDirty.IsPresent
        exit 0
    }
    catch {
        Write-Error -Message $_.Exception.Message -ErrorAction Continue
        exit 1
    }
}

Write-Host 'AfterDark team helper. Type --help for options; 0 exits without stopping the team.'
while ($true) {

    $Choice = Read-Host 'team'
    if ($Choice -eq '--help' -or $Choice -eq 'help') { Show-TeamHelp; Show-TeamOptions; continue }
    if ($Choice -eq '0') { break }
    try {
        switch ($Choice.ToUpperInvariant()) {
            '1' { Invoke-TeamAction 'status' }
            '2' { Invoke-TeamAction 'start' }
            '3' { Invoke-TeamAction 'start' -ShouldResume $true }
            '4' { Invoke-TeamAction 'stop' }
            '5' { Invoke-TeamAction 'watch' }
            '6' { Invoke-TeamAction 'doctor' }
            '7' { Invoke-TeamAction 'reports' }
            'D' { Invoke-TeamAction 'details' }
            '8' { Invoke-TeamAction 'inbox' }
            '9' { Show-TeamHelp; Show-TeamOptions }
            'I' { Invoke-TeamAction 'initialize' }
            'A' { Invoke-TeamAction 'initialize' -ShouldAdopt $true }
            'C' { Invoke-TeamAction 'commit' }
            'R' { Invoke-TeamAction 'retry' }
            'N' { Invoke-TeamAction 'next' }
            'P' { Invoke-TeamAction 'publish' }
            'T' { Invoke-TeamAction 'recover' }
            default { Write-Host 'Unknown option. Type --help to see available commands.' }
        }
    }
    catch { Write-Warning $_.Exception.Message }
}
