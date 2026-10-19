# Agent team maintenance

Active role definitions, policies, schemas, scheduling code and the helper belong
in this directory. Application workers must not modify them. Only an explicit
owner-authorized infrastructure maintenance turn may change team machinery.

Stop all controllers and verify the process inventory before maintenance. Preserve
application changes, runtime evidence and owner STOP intent. Never start legacy
and centralized controllers together. Historical implementations are inactive.

Owner authority update - 2026-10-19: the technical coordinator may directly repair
local application, test harness, task, prompt, policy and controller source during
an explicitly scheduled autonomous intervention. The sole controller suspends
ordinary scheduling for that worker; no other writer/controller may run. This is
the authorized exception to the stopped-controller maintenance rule above.
After repair the controller exits, the guardian reloads changed machinery, and
source changes require independent review before ordinary QA/release work.
Runtime state, locks, STOP, gate receipts and Git/publication actions remain
controller-owned. Never fabricate acceptance or weaken security to clear a stall.

Use English and explicit UTF-8. Test scheduling and Git boundaries with mocked
workers and temporary repositories; never call paid agents or production from
unit tests. A deliberate live launch is separate from tests. Keep roles and helper
options consistent with actual supported commands. Do not invent browser, owner,
backup, CI or deployment acceptance. Retain snapshot-bound quality gates and
explicit local commit/publication controls.

Engine routing - 2026-10-19: workers may run on Codex or, after Codex plan exhaustion, Claude. Engine selection, Claude flags and quota handling are controller-owned (see README). Claude uses CLAUDE.md, which imports this file.
