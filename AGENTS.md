# Agent team maintenance

Active role definitions, policies, schemas, scheduling code and the helper belong
in this directory. Application workers must not modify them. Only an explicit
owner-authorized infrastructure maintenance turn may change team machinery.

Stop all controllers and verify the process inventory before maintenance. Preserve
application changes, runtime evidence and owner STOP intent. Never start legacy
and centralized controllers together. Historical implementations are inactive.

Use English and explicit UTF-8. Test scheduling and Git boundaries with mocked
workers and temporary repositories; never call paid agents or production from
unit tests. A deliberate live launch is separate from tests. Keep roles and helper
options consistent with actual supported commands. Do not invent browser, owner,
backup, CI or deployment acceptance. Retain snapshot-bound quality gates and
explicit local commit/publication controls.
