"""Token-budget behaviour: task briefs, per-role shared context and prompt read directives."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import team

TASKS = """# Backlog

## Execution rules

Pick the first ready row.

## Active product queue

- [x] **T1 - Done foundation** | done | Dependencies: none.
  Finished long ago.

- [ ] **T2 - Assigned slice** | todo | Dependencies: T1.
  HEAD-SCOPE acceptance text.
  MIDDLE-PADDING-LINE
  Delivery record (2026-10-19): TAIL-EVIDENCE

- [ ] **T3 - Unrelated slice** | blocked | Dependencies: T2.
  UNRELATED-BODY

## Work log

- 2026-10-15: T2 planned with evidence.
  continuation line for T2
- 2026-10-16: T3 only note.
"""


def write_project(root, text=TASKS):
    (root / 'tasks.md').write_text(text, encoding='utf-8')
    return root


class TaskBriefTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = write_project(Path(self.temp.name))

    def test_brief_contains_assigned_row_dependencies_index_and_log_only(self):
        brief = team.task_brief(self.project, ['T2'])
        self.assertIn('HEAD-SCOPE', brief)
        self.assertIn('- T1: done', brief)
        self.assertIn('- T2 [todo]', brief)
        self.assertIn('- T3 [blocked]', brief)
        self.assertNotIn('- T1 [done]', brief)
        self.assertNotIn('UNRELATED-BODY', brief)
        self.assertIn('T2 planned with evidence', brief)
        self.assertNotIn('T3 only note', brief)
        self.assertIn('Pick the first ready row.', brief)

    def test_long_row_keeps_head_and_latest_delivery_record(self):
        long_text = TASKS.replace('  MIDDLE-PADDING-LINE\n', ''.join('  filler %d xxxxxxxxxxxxxxxxxxxxxxxx\n' % i for i in range(400)))
        write_project(self.project, long_text)
        brief = team.task_brief(self.project, ['T2'], row_cap=2000)
        self.assertIn('HEAD-SCOPE', brief)
        self.assertIn('TAIL-EVIDENCE', brief)
        self.assertIn('middle truncated', brief)
        self.assertLess(len(brief), 6000)

    def test_unassigned_stage_and_unknown_ids_get_index_not_rows(self):
        brief = team.task_brief(self.project, [])
        self.assertIn('No task row is assigned', brief)
        self.assertIn('- T3 [blocked]', brief)
        self.assertNotIn('UNRELATED-BODY', team.task_brief(self.project, ['T99']))

    def test_limit_and_missing_file(self):
        self.assertLessEqual(len(team.task_brief(self.project, ['T2'], limit=300)), 300 + 120)
        (self.project / 'tasks.md').unlink()
        self.assertIn('missing', team.task_brief(self.project, ['T2']))

    def test_real_sized_backlog_is_a_small_fraction(self):
        rows = ''.join('- [x] **T%d - Row %d** | done | Dependencies: none.\n  %s\n\n' % (i, i, 'x' * 1800) for i in range(10, 110))
        log = ''.join('- 2026-10-1%d: log %d %s\n' % (i % 10, i, 'y' * 700) for i in range(300))
        write_project(self.project, TASKS.replace('## Work log', rows + '## Work log') + log)
        full = len((self.project / 'tasks.md').read_text(encoding='utf-8'))
        brief = team.task_brief(self.project, ['T2'])
        self.assertLess(len(brief), full // 10)
        self.assertIn('TAIL-EVIDENCE', brief)


class RoleContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = write_project(Path(self.temp.name))
        self.home = self.project / 'agent-team'
        self.home.mkdir()
        source = Path(team.__file__).parent
        self.config = json.loads((source / 'team.json').read_text(encoding='utf-8-sig'))
        self.config.update(auto_commit=False, autonomous_intervention=False, archive_done_tasks=False)
        team.save(self.home / 'team.json', self.config)
        (self.home / 'report.schema.json').write_text((source / 'report.schema.json').read_text(encoding='utf-8'), encoding='utf-8')
        (self.project / '.gitignore').write_text('.supervisor/\n', encoding='utf-8')
        for args in (('init', '-q'), ('config', 'user.name', 'Fixture'), ('config', 'user.email', 'f@example.invalid'),
                     ('config', 'commit.gpgsign', 'false'), ('add', '.'), ('commit', '-qm', 'Fixture baseline')):
            subprocess.run(['git', '-C', str(self.project), *args], check=True, capture_output=True)
        self.controller = team.Team(self.project, self.home, runner=lambda role: None)

    def write_shared(self, text):
        (self.home / 'shared-context.md').write_text(text, encoding='utf-8')

    def test_sections_are_limited_per_role_and_unlisted_sections_go_to_everyone(self):
        self.write_shared('# Shared\n\n## Common rules\n\nALWAYS\n\n## Local environment and recovery\n\nENVIRONMENT\n\n'
                          '## Owner-authorized autonomous intervention - 2026-10-19\n\nINTERVENTION\n')
        self.controller.config['shared_context_sections'] = {
            'Local environment and recovery': ['qa', 'technical_lead'],
            'Owner-authorized autonomous intervention': ['technical_lead']}
        lead = self.controller.shared_for_role('technical_lead')
        qa = self.controller.shared_for_role('qa')
        ops = self.controller.shared_for_role('operations')
        self.assertTrue('ALWAYS' in lead and 'ENVIRONMENT' in lead and 'INTERVENTION' in lead)
        self.assertTrue('ALWAYS' in qa and 'ENVIRONMENT' in qa and 'INTERVENTION' not in qa)
        self.assertTrue('ALWAYS' in ops and 'ENVIRONMENT' not in ops and 'INTERVENTION' not in ops)
        self.assertTrue(lead.startswith('# Shared'))

    def test_empty_map_returns_full_shared_context(self):
        text = '# Shared\n\n## A\n\none\n\n## B\n\ntwo\n'
        self.write_shared(text)
        self.controller.config['shared_context_sections'] = {}
        self.assertEqual(self.controller.shared_for_role('operations'), text)

    def test_shipped_config_keeps_safety_sections_for_every_role(self):
        shared = (Path(team.__file__).parent / 'shared-context.md').read_text(encoding='utf-8')
        self.write_shared(shared)
        self.controller.config['shared_context_sections'] = self.config['shared_context_sections']
        for role in team.ROLES:
            text = self.controller.shared_for_role(role)
            self.assertIn('## Production boundary', text, role)
            self.assertIn('Owner-approved batch delivery', text, role)
        self.assertIn('Owner-authorized autonomous intervention', self.controller.shared_for_role('technical_lead'))
        self.assertNotIn('Owner-authorized autonomous intervention', self.controller.shared_for_role('developer'))
        self.assertLess(len(self.controller.shared_for_role('operations')), len(shared) // 2)

    def test_task_brief_is_written_per_role_and_referenced_in_context(self):
        self.controller.persist(task='T2', delivery_batch={'id': 'T2', 'tasks': ['T2'], 'acceptance_tasks': []})
        path = self.controller.write_task_brief('qa')
        self.assertEqual(path, self.controller.folder / 'artifacts' / 'qa' / 'task-brief.md')
        self.assertIn('HEAD-SCOPE', path.read_text(encoding='utf-8'))
        self.assertEqual(self.controller.context('qa')['task_brief_file'], str(path))

    def test_developer_brief_carries_gate_findings_when_no_task_is_assigned(self):
        report = self.controller.folder / 'reports' / 'gate.json'
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps({'report': {'status': 'changes_requested', 'findings': ['FINDING-XYZ']}}), encoding='utf-8')
        self.controller.persist(active_issue_ids=['i1'], reports={'code_reviewer': str(report)})
        text = self.controller.write_task_brief('developer').read_text(encoding='utf-8')
        self.assertIn('Source repair assignment', text)
        self.assertIn('FINDING-XYZ', text)
        self.controller.persist(active_issue_ids=[])
        self.assertNotIn('Source repair assignment', self.controller.write_task_brief('developer').read_text(encoding='utf-8'))

    def test_brief_failure_degrades_to_a_note(self):
        (self.project / 'tasks.md').write_bytes(b'\xff\xfe\x00bad')
        path = self.controller.write_task_brief('developer')
        self.assertIn('Task brief unavailable', path.read_text(encoding='utf-8'))


class PromptDirectiveTests(unittest.TestCase):
    def test_no_prompt_instructs_reading_whole_project_files(self):
        base = Path(team.__file__).parent
        for role in sorted(team.ROLES | {'supervisor'}):
            text = ' '.join((base / 'agents' / role / 'prompt.md').read_text(encoding='utf-8').split())
            self.assertIn('context.task_brief_file', text, role)
            self.assertNotIn('Read AGENTS.md, agent.md, tasks.md', text, role)
        shared = ' '.join((base / 'shared-context.md').read_text(encoding='utf-8').split())
        self.assertNotIn('Read current AGENTS.md, agent.md, tasks.md', shared)


if __name__ == '__main__':
    unittest.main()
