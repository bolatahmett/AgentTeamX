# AfterDark agent team

This directory contains the active team definitions and controller. Each role has
its own agents/<role>/ folder containing prompt.md and role.json. The historical
planner/supervisor implementations remain inactive references; do not run them
alongside this controller. Runtime evidence and controls belong to the controller's
ignored runtime directory, not to application source.

## Roles and boundaries

| Role | Responsibility | Writes |
| --- | --- | --- |
| supervisor | Deterministic scheduling, locking, snapshot gates and bounded retries | Controller-owned runtime state |
| technical_lead | Diagnose recovery; directly repair local stalls in authorized intervention mode | Recovery artifacts; local application/controller/policy source during intervention |
| planner | Validate findings, prioritize user outcomes and maintain bounded tasks | tasks.md only |
| developer | Implement one ready task or assigned review repair | Assigned source, targeted tests, related documents and tasks |
| ux_reviewer | Walk assigned pages and report observed journey friction | None |
| code_reviewer | Independently inspect the exact change snapshot | None |
| qa | Independently execute acceptance and relevant regressions | Local test artifacts only |
| devops | Inspect release configuration, migrations and rollback prerequisites | None |
| operations | Observe configured public readiness and availability | None |
| environment_engineer | Provision and verify missing local browser/runtime tools | Dedicated ignored local tool and environment directories |

Only one worker runs at a time. Role prompts and Codex sandbox modes restrict
workers; these are not separate operating-system accounts or proof of credential
isolation. Keep production secrets outside worker-readable project files. No worker
may change its own policy, controller locks, STOP state, Git history or production.
The supervisor is ordinary deterministic code, not another paid model invocation.
Owner-approved role_models in team.json selects each worker's explicit CLI model
and reasoning effort; unspecified policies retain the configured CLI default.
Operations uses gpt-6-luna/low, routine DevOps gpt-6-luna/medium and UX review
gpt-6-luna/medium. Planner uses gpt-6-sol/low; QA and environment preparation use
gpt-6-sol/medium. Developer and code review use gpt-6.1-sol/medium; technical
diagnosis uses gpt-6.1-sol/high. Active release-incident DevOps uses the stronger
release_diagnostic_model because production failure diagnosis is not a routine
checklist. Models and efforts were checked against the local CLI model catalog.
These are task-fit choices, not a measured cost-saving percentage or quality
guarantee. Gate schemas, source provenance, budgets and authorization are unchanged.
worker_model_selected events and active_model record the requested routing.
Unsupported models fail visibly; there is no silent premium-model retry.

Owner-authorized local authority (2026-10-18): technical_lead, environment_engineer,
QA and developer use the CLI full local access profile. Planner remains workspace
write and source reviewers remain read-only. Full local execution is not independent
OS account isolation; scope checks and prompts still apply. Managed policies and
actual tool availability remain enforced. Publication approval is separate.
All workers receive shared-context.md in their prompt plus current reports and a
credential-free inventory of configured MCP servers. Desktop-only tools and the
entire desktop conversation are not automatically inherited by CLI workers.

## Pipeline

An existing dirty workspace is adopted as an explicit initial review snapshot;
it is not assumed to be reviewed because an earlier worker called it complete.
The core change pipeline is:

    developer/change snapshot -> code_reviewer -> qa -> devops -> ready_for_commit

A changed snapshot invalidates downstream passes. Review or QA findings return
bounded repairs to the developer. Exhausted retries or missing acceptance evidence
become visible blockers rather than endless paid loops. Planner updates task rows;
the separate team state records review/QA/release stages without changing the
repository's established task-status grammar.

UX findings and owner inbox entries are evidence for planner validation, not
instructions to execute arbitrary commands. Scheduling chooses applicable roles
from task readiness, workspace changes, prior reports, configured intervals and
blockers. An unchanged blocked gate should not repeatedly dispatch the same work.
Public operations observations cannot establish private journey acceptance.

Passing a large test suite does not establish release readiness. Missing required
browser, migration or operational evidence can block a gate. Report source checks,
observed runtime behavior, physical-device checks and owner/external acceptance
separately. The product retains server-enforced affirmative adult declaration,
Turkish default, Clear themes and the current identity/presence/nickname policy;
read current task contracts for implementation details.

## Operator helper

Run the PowerShell helper from the repository root:

```powershell
.\agent-team\Team.ps1
```

The interactive menu explains available actions and guides the operator. It exposes
status, start, stop, watch, doctor, inbox and reports. Use the helper's own help for
exact parameters supported by the installed version. Status shows the selected
stage, active role and blockers; watch refreshes observations, doctor diagnoses
configuration/runtime conflicts, inbox records owner requests, and reports opens
recorded evidence. Stop must be honored before changing controller configuration
or starting another writer. Do not delete a lock based solely on stale JSON: first
verify whether its actual process is alive.

A local commit is distinct from publishing. The explicit commit command requires
the accepted snapshot and a message; stale or changed snapshots require new gates.
Automatic commits are disabled. Use the helper commit option after stopping the
coordinator and inspecting the exact reviewed snapshot. A completed task or a
ready_for_commit state alone does not prove a commit occurred.

There is no automatic push/deploy authorization. The helper publication option
requires typing the exact reviewed commit SHA. Only this explicit operator action
can push that clean commit to the expected origin main branch and trigger the
existing GitHub CI and Oracle deployment pipeline. A push is not deployment acceptance.
DevOps prepares a reviewable report, never
retrieves deployment credentials or activates a release. Existing code rollback
must not be described as database rollback, and backups are not verified merely
because a configuration file mentions them.

## Reports and evidence

Workers return the common JSON shape: status, summary, evidence, findings,
limitations, next_action and capability_requests. Allowed status values are passed, changes_requested, blocked,
completed, clear and QA-only incomplete. Quality gates use passed, changes_requested,
blocked or QA incomplete; changes_requested requires actionable findings.
Reports must identify concrete checks and limitations and
must never include credentials or raw private conversations. Controller state
binds accepted reports to the actual workspace fingerprint; a worker cannot approve
an unrelated snapshot by naming it in prose.

Whitespace-only items in evidence, findings and limitations are removed locally
before validation, without another worker call. Substantive entries and blocked
status are preserved. Wrong item types, missing fields, empty passing evidence
and unresolved findings still fail validation; formatting cleanup grants no gate.

findings contains actionable defects only; limitations contains verification
constraints and unrun checks. A source review may pass its assigned scope with
limitations, but never with unresolved findings. If missing evidence is required
for the assigned stage, return blocked even when findings is empty. Old ambiguous
reports are not reclassified automatically; rerun the affected role under the new
schema. Owner issue intake rejects empty text and unexpected control characters.

A stage completing does not close historical release/device gates. No human
approval, production health, backup restoration or browser success may be invented.
Repeated quota, tool or environment failures should be surfaced with their opening
condition. Team controls are separate from the application and do not change
existing authentication, access-control, block or consent enforcement.

## Runtime and scheduling

Owner authorization `owner-2026-10-19` enables autonomous_intervention. Ordinary
local needs_attention states automatically dispatch the full-local-access
technical coordinator with intervention.md. This mode can directly repair
application/controller source, prompts, policies, tasks and local harness/tooling.
The sole controller suspends normal dispatch while it runs. Successful repair
produces current-snapshot evidence and a resume assignment, then exits the
controller so new machinery is loaded. Any controller (including one parked in
waiting_for_quota or needs_attention) also exits between steps when agent-team/*.py
changes; the guardian then reloads itself and restarts it. Source changes require independent review, and no
intervention creates a passing gate or changes Git/publication authority.

Repairs have a separate persistent budget of six calls per incident/hour and
twelve overall/hour. Exhaustion waits for the next window automatically, without
paid polling or a manual Retry; product and release ledgers are preserved.
Successful repair also authorizes one independent review/QA/DevOps pass on the
exact repaired snapshot and assigned task/batch. These gate calls share that
same hourly repair budget, including across restarts, so an exhausted delivery
budget cannot prevent verification of the repair. Each gate can run once per
repair and is consumed only when the gate returns, so a controller crash
mid-review retries it (charged to the repair budget); source/task/batch/
release-incident drift invalidates this assignment.
Cooldown resumes the pending gate directly. Further failures require diagnosis;
no product/release limit is raised or counter reset, and no approval is implied.
On the first reload, an older controller's completed repair handoff can restore
this assignment only from its saved successful report on the exact current
snapshot; an existing assignment, including an exhausted one, is never refilled.
A diagnosed real external credential/permission/owner boundary stays explicit.
STOP always wins. A repaired QA continuation incident grants two additional QA
turns without resetting its history/counters. Interrupted state-file replacement
retries transient Windows sharing locks, and failed disk persistence does not
advance in-memory scheduling state.

Definitions live here; ignored runtime data lives in .supervisor/team-v2:
state.json, LOCK, STOP, baseline.json, events.jsonl, inbox/, reports/, logs/, artifacts/.
Role metadata is validated for identity, worker flag and sandbox. write_scope and
triggers describe controller policy; they are not arbitrary executable rules.

Ready tasks select the developer; new intake selects the planner at the next safe
planning stage. UX runs when no task is ready, source differs from its last review
and the configured interval has elapsed. Unchanged source does not trigger repeated
paid UX reviews. Two failed public readiness probes queue one operations review per
incident at the next schedule/idle stage. Actionable findings go to planner.
Blocked gates are quiet until explicit retry or a planner handoff for independent work.
Quota pauses poll the authenticated CLI account/rateLimits/read endpoint at most
once per five minutes, without a model turn. Positive current core-quota evidence
resumes the interrupted role; changed source first requires fresh review. Unknown,
unavailable or exhausted quota stays paused. STOP and persistent delivery budgets
remain effective; the monitor never consumes reset credits. The guardian can also
perform this check when the coordinator has exited. A per-start call budget bounds usage.
Exception: QA may explicitly report a confirmed local synthetic entry cooldown
using `WAIT_LOCAL_RATE_LIMIT seconds=N;` in next_action, with timing evidence and
no findings/capability request. N is bounded to 1-3600 seconds. The coordinator
persists waiting_local and resumes incomplete QA after the deadline, without
agent calls while waiting. Two attempts per task survive restarts and source
changes; existing delivery/call budgets remain enforced. STOP prevents resumption,
changed source requires review and approvals are retained only for matching scopes.
Unknown blockers, production limits, quota and owner approvals never use this path.
QA may return incomplete for unfinished local execution with working tools. A
current-task/current-snapshot continuation.json checklist records observed completed
scenarios and stable remaining IDs. The coordinator preserves per-scenario evidence,
schedules only remaining work, and grants at most two continuation turns per task
across restarts and source changes. Subsequent results must complete a previously
remaining scenario without dropping IDs. No progress, invalid/stale checklists or
exhaustion become explicit attention reasons. A later passed report must complete
the stored checklist; partial progress never creates a passing receipt. External
approval/tool blockers remain blocked. Generic legacy blocked prose is not silently
reclassified. Existing call budgets, source review and STOP remain in effect.
Watch and doctor do not call agents. Public readiness is not a full user-journey smoke.

When a developer/QA/DevOps stage is blocked but another task is independently
ready, the planner receives the blocked evidence to preserve its opening condition
and continue useful independent work. Missing acceptance never becomes a passing
gate. Source or policy failures and quota waits are not automatically retried.
Blocked quality reports with actionable source findings route to the existing
bounded developer repair flow instead of being parked as missing acceptance.
Bare HTTP 429/rate-limit text is not classified as account quota; account usage
limits require account-specific signals. Fresh worker runs clear stale failure
labels so an earlier transport/quota incident cannot misclassify the next result.

Stop and verify controller exit before retry, commit, publication or next batch.
Retry recomputes the current source fingerprint. If maintenance or another owner
repair changed it, retry always selects code_reviewer, including when the previous
assignment was developer. Unchanged work retains its assigned role. This prevents
an already-applied repair from being sent back for a no-change developer turn;
current gates and persistent incident counters remain intact.
The helper provides these actions. A local commit requires three current snapshot
gates, no pre-existing staged changes, no sensitive-looking paths and no competing
workers. The initial adopted work is never silently committed. Publication checks
the exact recorded local commit, a clean workspace, expected repository and
fast-forward ancestry. CI/deployment results remain distinct from push completion.

Python examples:

```powershell
python agent-team/team.py status
python agent-team/team.py doctor
python agent-team/team.py initialize --adopt-dirty
python agent-team/team.py start
python agent-team/team.py stop
python agent-team/team.py retry
python agent-team/team.py commit --snapshot REVIEWED_FINGERPRINT --message "Describe the change"
python agent-team/team.py publish --commit REVIEWED_COMMIT_SHA --confirm-production
python agent-team/team.py next
```

## Automatic local environment recovery

A blocked worker can request browser, local_runtime or build_tools in the typed
capability_requests array. The supervisor schedules environment_engineer before
deferring independent product work. This agent provisions only local ignored
tooling; it cannot change application source, tasks, policy, production or global
security settings. Requests are capped at two per capability/source snapshot.

The report must be backed by a matching ignored manifest with runtime evidence
and reusable QA bootstrap instructions. Browser readiness requires a loopback
test origin, two actual contexts with isolated storage and a loaded current page.
An executable existing or an empty CUA inventory alone is not a readiness result.
QA owns its bootstrap lifecycle and independently verifies the actual journey;
environment preparation never creates a passing QA receipt. Failed recovery
reports attempted actions and the concrete remaining condition. Failed preparation
automatically selects technical_lead to diagnose alternatives and write an ordered
local_runtime/build_tools/browser recovery plan. Each verified prerequisite hands
off to the next; the final capability returns to the original QA stage without
manufacturing a passing QA result. Alternative strategies are bounded per snapshot.
Managed approval/exec policies remain enforced; local full access is explicitly
owner-configured, not a retry with a policy-bypass flag.

Reference: [official Codex CLI documentation](https://developers.openai.com/codex/cli/reference).

## Repair budgets

## Owner-authorized delivery batches - 2026-10-18

delivery_batches in team.json explicitly groups up to three dependency-ready
source tasks. Scheduling passes their IDs and independently eligible delivered
acceptance_tasks in context.delivery_batch. A source task with an unmet dependency
is excluded, never silently waived. The primary task remains visible for existing
monitoring; reports must identify each batch member and its own acceptance result.
One developer turn produces the batch snapshot, followed by one review/QA/DevOps
chain. QA owns one build/runtime/browser setup for the combined scenarios, using
valid checkpoint outputs where possible, then cleans it up once. Failed scenarios
receive focused repairs and affected regression checks; no unconditional full
end-to-end run per child task. Documentation-only changes require document checks,
not an application bootstrap. Exact-source gates, STOP, quota and persistent
release-recovery budgets remain in force. Source work uses one shared existing
delivery call budget per batch, rather than one budget per child.

Source repair budgets are tracked per task and normalized individual finding,
not by a task's cumulative review/QA rounds. Line numbers, whitespace and revision
hashes do not create fresh identities; an extra finding does not reset an existing
one. A newly observed defect receives its own budget. Repeated unchanged findings
go to technical_lead for an alternative source-repair plan before developer resumes.
A distinct strategy has its own bounded attempts; unchanged strategy repetition is
rejected. Per-start call limits and managed quota/STOP remain separate controls.


## Detailed operator monitoring

Open Team.cmd and choose 5 for live work details. The view separates the active
agent, elapsed time and classified command activity from the last completed
report. It shows current-snapshot quality gates, recent handoffs and recorded
publication observations. Choose D for full latest per-role report evidence,
findings, limitations and next actions. Ctrl+C leaves monitoring without stopping
the coordinator. For a single read-only frame run:

```powershell
python agent-team/team.py watch --once
```

Monitoring reads bounded log tails and canonical report files. It never displays
raw shell commands or raw command output; report text is redacted for common
credential patterns. Command completion is not a passing test verdict, and local
checks do not constitute production acceptance.


## Owner-authorized resilience and publishing - 2026-10-18

This update supersedes earlier manual-only publishing descriptions. The owner
explicitly authorized automatic commit, push and deployment. Worker roles still
cannot mutate Git or production. The independent guardian invokes the same
exact-source commit and publish guards after current review, QA and DevOps pass.
It observes both GitHub workflows for the exact SHA and requires the live
readiness endpoint to report that SHA before recording release_verified.
Missing GitHub CLI authentication or failed/skipped CI never counts as success.

Team helper Start/Resume installs a current-user, limited interactive Windows
scheduled task. This gives the guardian a lifetime independent of a terminal or
Codex tool call, with a logon trigger and bounded restarts. It needs the computer
awake and the user logged in; it is not an always-on cloud service. STOP prevents
work and must be explicitly resumed. A named mutex prevents duplicate guardians.
The guardian observes health independently while a model worker is running,
records controller exit codes and long host scheduling gaps, and bounds crash
restarts to three per hour. It never infers sleep or crash causes from elapsed
time alone. Worker heartbeats record elapsed time and output inactivity.

Preparation checkpoints bind application/environment hashes and hashed ignored
evidence artifacts. Team-only and documentation changes preserve build scope;
all changed source still needs exact-source release review. Checkpoints are not
QA approvals: actual outputs must be checked and live browser checks repeated.
The environment agent records prepare/build/browser/cleanup separately, allowing
completed build work to survive a later cleanup/reporting interruption. Older
artifacts without checkpoint provenance require a fresh verified checkpoint.

Failure handling distinguishes quota, policy, timeout, transport, cleanup, build
and validation failures. Only transient errors get bounded automatic retries;
repeated local preparation problems select technical diagnosis. Quota and policy
remain blocked. Monitoring shows completed/remaining gates, next action, guardian
heartbeat, repeated starts and completed role durations from retained history.
No percentage or production acceptance is inferred from command completion.


## Independent release recovery budget

Failed deployment observation schedules DevOps with a persistent release incident.
Its 40-call recovery budget is separate from the 24-call product-delivery batch
budget and covers diagnosis, repair and required review/QA. Both ledgers survive
controller restarts. A new candidate SHA does not reset an unresolved incident;
only verified CI and matching healthy production SHA close it. All existing
source, commit and publication checks remain required. For a previously blocked
exact recorded failed publication, stop workers and run
`python agent-team/team.py recover-release`, then explicitly Resume. This command
preserves owner STOP and all counters; it does not waive checks or publish.

Owner-authorized budget increase (2026-10-18): 48 model calls per start,
24 per delivery batch and 40 per persistent release incident. These are total
role calls across diagnosis, repair and quality gates, not retries of one defect.
Existing incident/delivery counters are retained when limits increase; the current
incident at 10 calls therefore has 30 remaining. Repeated-source-finding limits,
environment/strategy limits, quota pauses, STOP and exact-source gates are unchanged.


## Engine failover: Codex primary, Claude Sonnet 5.5 fallback - 2026-10-19

Owner-authorized. `engine_failover` in team.json lets every worker role run on either
CLI. Codex is the primary engine (`primary_engine`, overridable per role with
`role_engines`). When a Codex turn ends with a plan/credit exhaustion error the same
role is re-run immediately on Claude (`claude_models.default`, currently
claude-sonnet-5-5, effort taken from the role's configured reasoning level) with no
waiting stage and no manual retry. When Claude is exhausted the work goes back to
Codex, whichever has quota. Only when both are exhausted does the existing
waiting_for_quota stage apply.

Owner UX update - 2026-10-20: the developer is Codex-first again so the UX modernization
queue (T88-T103) runs on `gpt-6.1-sol`; QA and ux_reviewer also use `gpt-6.1-sol`;
`auto_batch_size` is 1 so pages are delivered one at a time; T103 is the verification-only
QA row. Completed rows were archived to docs/history/tasks-archive-20261020.md.

Owner role split - 2026-10-19: `role_engines` makes developer, technical_lead and
code_reviewer Claude-first; all other roles stay Codex-first. The split applies while
both engines have quota; a Claude-first role falls back to Codex on Claude plan
exhaustion and vice versa. Claude effort follows `role_models` (developer and
code_reviewer medium, technical_lead high). code_reviewer and Codex-run QA therefore
use different engines for review and verification.

Return to Codex: an exhausted Codex is re-probed at most every `codex_probe_seconds`
(300) through the account limit endpoint, without a model turn; positive evidence
restores it as the first choice for the next role call. Claude has no such endpoint,
so an exhausted Claude is retried after `claude_quota_cooldown_seconds` (1800). The
state is kept in state.json under `engines`; events: engine_quota_exhausted,
engine_failover, engine_restored. Only plan/credit exhaustion switches engines.
Bare HTTP 429, api_retry rate_limit, timeouts, policy and validation failures keep
their existing handling and never switch engines. Quota patterns are matched only
against an event's error/message/result fields, never the whole JSON line, and
a rate_limit_event counts only when `rate_limit_info.status` is "rejected"
(`overageStatus` is "rejected" on every event when overage is disabled).

Claude invocation: `claude -p --output-format stream-json --verbose --json-schema
<report.schema.json> --model M --effort E --no-session-persistence --add-dir <project>
--strict-mcp-config`, prompt on stdin. Every sandbox limits tools to
Bash/Read/Edit/Write/Glob/Grep (read-only: Read/Grep/Glob/Bash) and denies Git
mutation/publication (commit, push, reset, checkout, add, ...), gh, curl/wget/ssh and
PowerShell web cmdlets, and `--output`/`--ext-diff`/`--textconv`. Deny rules also hold
under bypass mode (verified live 2026-10-19). danger-full-access uses
--dangerously-skip-permissions (the same owner-authorized level); workspace-write uses
acceptEdits; read-only uses dontAsk with read-only git commands and denies Edit/Write.
Claude Code has no OS sandbox on native Windows: this is a tool-level guardrail that
pattern rules alone enforce (an indirect shell such as `cmd /c` can evade it), not
the Codex workspace/network isolation. The controller's HEAD/index checks remain the
backstop. The report is taken from the final result event's structured_output. Claude workers
are recognised by competing_processes through --add-dir plus stream-json. Claude reads
CLAUDE.md (a one-line import of AGENTS.md) instead of AGENTS.md. No MCP servers or
browser tools reach Claude workers (--strict-mcp-config, which also drops claude.ai
connectors). The CLI must be on the controller's PATH (winget Anthropic.ClaudeCode)
and logged in with `claude auth login`; the desktop app's bundled CLI is not used.
Run `python agent-team/team.py doctor` to verify the claude binary, login and model
policy.
Set `engine_failover` to false to return to Codex-only behaviour.

Token budget (2026-10-19): every worker turn used to start by dumping AGENTS.md, agent.md,
tasks.md (200+ KB, growing), writing-block.md and product-delivery.md. The controller now
writes artifacts/<role>/task-brief.md (assigned rows, dependency status, open-row index,
recent work-log entries; capped by task_brief_limit_chars) and prompts point to it via
context.task_brief_file; whole-file reads are replaced by targeted search. The shared
context injected into a prompt is limited per role by shared_context_sections in team.json
(sections not listed there, and the preamble, go to every role). Set shared_context_sections
to {} to return to the full shared context for all roles.

QA fast paths (2026-10-19): QA is a tiered gate, not a mandatory model turn. qa_tiers.py plus
Team.qa_fast_path decide from the change since the last QA pass (state.last_qa_pass): tier 0,
application and environment scopes unchanged: reuse the earlier evidence; tier 1, only non-UI
application files changed (qa_tiers.ui_paths): the controller runs qa_tiers.source_checks and
passes the gate on exit 0 (no browser journey is claimed; browser acceptance stays open on its
task rows); tier 2, UI or acceptance-contract changes, verification-only tasks, batches that
carry acceptance scenarios and pending continuations: preflight, then a QA-authored suite that
covers the assignment, then the QA agent. A failed source check or suite never fails a gate by
itself, it hands the agent the evidence (context.qa_fast_path). A fast path spends no call budget.
Preflight (qa_tiers.preflight) blocks QA with a typed capability request when git, the dev-tools
files, a browser or a free loopback port are missing, instead of starting a model turn.
Suites live in .supervisor/team-v2/artifacts/qa/suites/<id>.json (contract in agents/qa/prompt.md);
the controller runs script and result_file itself inside an owned Windows job, requires the
result to name the exact current snapshot and every listed scenario to pass with evidence, and
requires the suite to cover every scenario ID previously enumerated for the task. Suite
completeness is QA-authored and not independently reviewed. Set qa_tiers.enabled to false to
return to a model turn for every QA gate.
tasks.md scope: the environment scope now hashes the acceptance contract (task definitions and
acceptance text; not checkbox/status, delivery-record lines or the work log) so task bookkeeping
no longer voids QA evidence. A one-time migration upgrades stored scopes that still match the
current files (state.scope_algorithm=2); the full-snapshot fingerprint is unchanged.


## Owner feature-focus mode - 2026-10-19

Owner-selected to deliver features faster with fewer model calls. Revert each line to restore
the earlier behaviour.

- `qa_tiers.mode: "source_only"`: every QA gate is the controller's typecheck/lint/test run and
  never a QA model turn, including UI changes, `qa_acceptance_tasks`, batches with acceptance
  scenarios and pending continuations. A passing report says browser acceptance is deferred, not
  passed; browser, device and owner acceptance stay open on their task rows. A check that fails
  with a log returns changes_requested with the log tail, so the developer repairs it without a QA
  turn; a host/definition/snapshot-stability failure still falls back to the QA agent. Remove
  `mode` to return to tiered QA.
- `allow_push`/`allow_deploy` are back to true (owner, 2026-10-19): every gated local commit,
  including DevOps release repairs, is pushed and deployed automatically again. If they are set
  to false, `continue_after_local_commit: true` keeps delivering on local commits instead of
  parking in release_ready, and the helper publish action accepts an idle team whose last
  local-only delivery is still HEAD.
- `ux_review_enabled: false`: no scheduled UX review turns.
- `auto_batch_size: 3`: a ready task outside `delivery_batches` is grouped with up to two further
  dependency-ready rows of any kind (features, fixes, tests, debt; never explicit-batch members,
  `qa_acceptance_tasks` or already delivered rows) into one developer turn and one gate chain.
  Fewer ready rows simply make a smaller batch.
- technical_lead effort high -> medium and `max_interventions_per_hour` 12 -> 6. code_reviewer
  stays at medium because it is now the only model gate on source changes.
- `qa_acceptance_tasks` is empty; T64 is already done.

Owner update (2026-10-20): `qa_tiers.mode` was removed to return to tiered QA, and
`qa_acceptance_tasks` lists T62 and T65-T73 so QA runs their deferred browser acceptance. Those
rows were reopened from `released_tasks`. A passed acceptance run for a listed task closes its
tasks.md row (done, with the report path) and returns to scheduling; no owner approval is needed.

Controller-owned QA runtime and acceptance sweep (owner, 2026-10-20): the controller starts
`scripts/qa/runtime.ps1` (migrate, build, serve the current snapshot on loopback 3443) for every
acceptance QA turn and stops it afterwards; QA never bootstraps its own runtime. In the schedule
stage every ready acceptance task with a suite runs on one shared runtime; passing rows close,
the rest go to a QA model turn that writes or repairs the suite (`{url}` is the runtime base URL in
suite args). An acceptance turn that is not passed parks its row for `park_retry_hours` (or goes
to repair when it reports findings), so one row never blocks the queue; a QA timeout parks too.

## Autonomous task discovery - 2026-10-19

Owner-selected: the team runs without waiting for the owner. With `autonomous_discovery.enabled`,
a schedule or idle stage with no ready rows and no pending inbox schedules the planner with
context.autonomous_discovery. The planner may add up to three evidence-backed ready rows of any
kind (see agents/planner/prompt.md); it never adds rows needing owner approval, credentials,
production writes or invented data. A pass that adds no ready row (clear or blocked) is not an
incident: it backs off exponentially from `interval_minutes` (60) up to `max_interval_hours` (24)
and resets once ready work exists. Events: autonomous_discovery_started/finished.

## Delivery speed and daily publishing - 2026-10-20

Owner-selected. `skip_released_tasks: true`: every task in a gated local commit is recorded in
state.released_tasks. Scheduling (and auto batches) never sends those rows to the developer again,
even when tasks.md keeps them open for deferred browser/owner acceptance; the planner still gets its
one delivered_release pass. Rows that reach done are pruned from the list automatically; for real rework on an
open released row run `python agent-team/team.py reopen --task T62`. Blocked-report routing uses the
same schedulable list, so released rows never count as independent ready work. This removes the no-change developer -> environment -> technical lead
loops that previously consumed most of the wall-clock time.

`publish_min_interval_hours: 24`: the guardian pushes and deploys at most once per 24 hours. Before
that, each gated commit stays local (release_ready -> continue) and delivery goes on. The first
release_ready after the interval, or an idle team whose HEAD is the last gated local commit with a
clean tree, publishes HEAD, which carries every earlier gated commit. state.last_publication_at
records the cadence. Deployment applies pending migrations after a verified backup
(docs/launch/oracle-deployment.md).

## Budgets never stop delivery - 2026-10-20

Owner-selected. With `park_exhausted_tasks: true`, a task or batch that reaches
`max_calls_per_delivery` (now 40) is recorded in state.parked_tasks and the scheduler moves to other
ready work instead of entering needs_attention. Parked rows are skipped like released rows, passed to
the planner (context.parked_tasks, which may split them into smaller rows) and re-enabled with
`python agent-team/team.py reopen --task ID`. Release recovery keeps its own budget and still escalates.
Safety nets were raised: 100 calls per controller start, 10 repair calls per incident and 30 per hour.
A repair window that is full is a timed wait that resumes automatically, not a stop.

## QA exploration and release log capture - 2026-10-20

Owner-selected. With `autonomous_discovery.qa_exploration`, a discovery pass with no ready rows
first schedules QA with context.qa_exploration instead of going straight to the planner. QA boots
the local build from the environment manifest, walks docs/product/journeys.md and the observable
behaviour of released rows in isolated synthetic browser contexts, and reports observed gaps as
findings. The pass is not a gate: no fast path, receipt or last_qa_pass is recorded. Its report
path reaches the planner as autonomous_discovery.exploration_report and the planner turns findings
into rows. A typed capability request goes through normal environment recovery and resumes the
exploration. The usual discovery backoff applies when neither step produces ready work.
Events: qa_exploration_finished.

When a release recovery starts, the controller saves the failed-step log of every failed workflow
for the exact commit (`gh run view <id> --log-failed`, its existing read-only gh login) under
artifacts/release-logs/ and lists the files in release_recovery.failure_logs, so DevOps and the
coordinator can diagnose without their own GitHub access. Token-like strings and private keys are
redacted. Event: release_logs_captured.

## No owner waits - 2026-10-20

Owner-selected; limits remain, but none of them stops the team.

- External boundaries: a coordinator `blocked` report with a valid typed boundary parks only the
  affected task/batch (and any release incident) and delivery continues (`park_external_blockers`).
  `owner_decision` is no longer an accepted boundary: the coordinator decides, implements and
  records the decision under docs/decisions/.
- Parked rows (external boundary, exhausted delivery budget, repeated failed repair) carry
  `retry_at` and return to scheduling after `park_retry_hours` (12) with a fresh delivery ledger.
  `team.py reopen --task ID` still re-enables a row immediately.
- No-progress breaker: after `max_interventions_per_incident` (3) coordinator repairs of the same
  incident, the work is parked instead of looping. Events: blocked_work_parked, parked_tasks_retried.
- The per-start call cap is a timed pause: stage waiting_budget for `call_budget_cooldown_seconds`
  (1800), then a fresh call window resumes the same stage (call_budget_wait/call_budget_resumed).
  Set it to null for the old stop behaviour.
- Claude-run technical_lead and devops may run `gh run view` / `gh run list` (owner-authorized) only in the
  read-only sandbox; every other sandbox keeps the blanket `gh *` deny (the controller supplies failure logs).
  Other gh subcommands, Git mutation and network clients stay denied.
- Self-improvement: with `self_improvement.enabled`, an idle team runs a coordinator retrospective
  at most every `interval_hours` (12) when at least `min_new_events` (30) events were recorded. It
  reads events/reports, fixes the costliest recurring waste (controller, prompts, config, harness or
  a tasks.md row) and resumes `schedule`; changed source goes through the normal review gates and
  the hourly repair ledger. Event: retrospective_started.
