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
| technical_lead | Diagnose failed local recovery and choose ordered alternative strategies | Ignored recovery plan and diagnostic artifacts |
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
completed and clear. Reports must identify concrete checks and limitations and
must never include credentials or raw private conversations. Controller state
binds accepted reports to the actual workspace fingerprint; a worker cannot approve
an unrelated snapshot by naming it in prose.

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

Definitions live here; ignored runtime data lives in .supervisor/team-v2:
state.json, LOCK, STOP, baseline.json, events.jsonl, inbox/, reports/, logs/, artifacts/.
Role metadata is validated for identity, worker flag and sandbox. write_scope and
triggers describe controller policy; they are not arbitrary executable rules.

Ready tasks select the developer; new intake selects the planner at the next safe
planning stage. UX runs when no task is ready, source differs from its last review
and the configured interval has elapsed. Unchanged source does not trigger repeated
paid UX reviews. Two failed public readiness probes queue one operations review per
incident at the next schedule/idle stage. Actionable findings go to planner.
Blocked gates are quiet until explicit retry or a planner handoff for independent work. Quota pauses
require explicit retry after account reset. A per-start call budget bounds usage.
Watch and doctor do not call agents. Public readiness is not a full user-journey smoke.

When a developer/QA/DevOps stage is blocked but another task is independently
ready, the planner receives the blocked evidence to preserve its opening condition
and continue useful independent work. Missing acceptance never becomes a passing
gate. Source or policy failures and quota waits are not automatically retried.

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
