"""Deterministic coordinator contracts; no model or production calls."""
import json
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import team


def report(status='passed', findings=None):
    return {'status': status, 'summary': 'Deterministic test evidence',
            'evidence': ['Verified fixture'], 'findings': findings or [], 'limitations': [], 'capability_requests': [],
            'next_action': 'Continue the reviewed workflow'}


class TeamTests(unittest.TestCase):
    def test_report_blank_items_do_not_discard_blocked_qa_evidence(self):
        original = report('blocked')
        original['limitations'] = ['Pending browser recovery', '', '  \t']
        original['evidence'] += ['']
        cleaned = team.validate_report(original, 'qa')
        self.assertEqual(cleaned['status'], 'blocked')
        self.assertEqual(cleaned['limitations'], ['Pending browser recovery'])
        self.assertEqual(cleaned['evidence'], ['Verified fixture'])
        self.assertEqual(original['limitations'], ['Pending browser recovery', '', '  \t'])

    def test_report_cleanup_cannot_manufacture_a_gate_pass(self):
        for evidence in ([], ['', '  ']):
            with self.assertRaisesRegex(ValueError, 'needs evidence'):
                team.validate_report({**report(), 'evidence': evidence}, 'qa')
        with self.assertRaisesRegex(ValueError, 'Unresolved findings'):
            team.validate_report({**report(), 'findings': ['', 'Actual defect']}, 'qa')
        for key in ('evidence', 'findings', 'limitations'):
            for value in (None, 'text', [None], [123], [{}]):
                with self.assertRaisesRegex(ValueError, 'Invalid '+key):
                    team.validate_report({**report(), key: value}, 'qa')

    def test_blank_limitation_preserves_qa_handoff_without_extra_call(self):
        self.adopted()
        self.controller.step()
        blocked = report('blocked')
        blocked['limitations'] = ['Remaining browser scenarios are unrun', '']
        blocked['next_action'] = 'Correct the local QA harness and resume remaining scenarios'
        self.responses['qa'] = blocked
        self.controller.step()
        stored = team.load(self.project / self.controller.state['reports']['qa'])
        self.assertEqual(stored['report']['limitations'], ['Remaining browser scenarios are unrun'])
        self.assertEqual(stored['report']['status'], 'blocked')
        self.assertNotIn('qa', self.controller.state.get('receipts', {}))
        self.assertEqual(self.roles, ['code_reviewer', 'qa'])
        self.assertNotEqual(self.controller.state.get('attention_kind'), 'worker_failure')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        self.home = self.project / 'agent-team'
        self.home.mkdir()
        config = json.loads((Path(team.__file__).parent / 'team.json').read_text(encoding='utf-8-sig'))
        config['auto_commit'] = False
        config['qa_owns_environment'] = False
        config['autonomous_intervention'] = False
        config['max_calls_per_delivery'] = 1000
        team.save(self.home / 'team.json', config)
        self.write('.gitignore', '.supervisor/\n')
        self.write('tasks.md', '- [ ] **T1 Work** | todo | Dependencies: None.\n')
        self.write('app.txt', 'original\n')
        self.git('init', '-q')
        self.git('config', 'user.name', 'Fixture')
        self.git('config', 'user.email', 'fixture@example.invalid')
        self.git('config', 'commit.gpgsign', 'false')
        self.git('config', 'core.hooksPath', str(self.project / 'no-hooks'))
        self.git('add', '.')
        self.git('commit', '-qm', 'Fixture baseline')
        self.roles = []
        self.responses = {}
        self.effects = {}
        self.controller = team.Team(self.project, self.home, runner=self.run_role)
        self.patch = patch.object(team, 'competing_processes', return_value=[])
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def write(self, name, text):
        path = self.project / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.project), *args], check=True,
                              capture_output=True).stdout

    def run_role(self, role):
        self.roles.append(role)
        if role in self.effects:
            self.effects[role]()
        return self.responses.get(role, report('completed' if role in {'planner', 'developer'} else 'passed'))

    def adopted(self):
        self.write('app.txt', 'owner changes\n')
        self.controller.initialize(adopt=True)

    def approvals(self):
        self.adopted()
        for _ in range(3):
            self.controller.step()
        self.assertEqual(self.roles, team.GATES)
        self.assertEqual(self.controller.state['stage'], 'ready_for_commit')
        return self.controller.state['snapshot']

    def test_batch_selects_only_ready_tasks_and_eligible_acceptance(self):
        self.write('tasks.md', '\n'.join([
            '- [x] **T1 Done** | done | Dependencies: None.',
            '- [ ] **T2 First** | todo | Dependencies: T1.',
            '- [ ] **T3 Second** | todo | Dependencies: T1.',
            '- [ ] **T4 Waiting** | blocked | Dependencies: T1.',
            '- [ ] **T5 Unready** | todo | Dependencies: T2.',
            '- [ ] **T6 Blocked dependency** | blocked | Dependencies: T5.',
        ]))
        config = {'delivery_batches': [{'id': 'shared', 'tasks': ['T2', 'T3', 'T5'],
                                       'acceptance_tasks': ['T4', 'T6']}]}
        result = team.delivery_batch(self.project, config, 'T2')
        self.assertEqual(result, {'id': 'shared', 'tasks': ['T2', 'T3'], 'acceptance_tasks': ['T4']})
        self.assertEqual(team.delivery_batch(self.project, config, 'T1')['tasks'], ['T1'])

    def test_batch_uses_one_developer_and_one_gate_chain(self):
        self.write('tasks.md', '- [ ] **T1 First** | todo | Dependencies: None.\n'
                   '- [ ] **T2 Second** | todo | Dependencies: None.\n')
        self.git('add', '.'); self.git('commit', '-qm', 'Two tasks')
        self.controller.config['delivery_batches'] = [{'id': 'shared', 'tasks': ['T1', 'T2']}]
        self.controller.initialize()
        self.effects['developer'] = lambda: self.write('app.txt', 'both changes\n')
        self.controller.step()
        self.assertEqual(self.controller.context('qa')['delivery_batch']['tasks'], ['T1', 'T2'])
        for _ in range(3): self.controller.step()
        self.assertEqual(self.roles, ['developer', *team.GATES])
        self.assertEqual(self.controller.state['stage'], 'ready_for_commit')
        self.assertEqual(self.controller.state['delivery_calls'][self.controller.config['delivery_epoch'] + ':shared'], 4)

    def released_open_task(self):
        self.write('tasks.md', '- [ ] **T1 Shipped** | in_progress | Dependencies: None.\n'
                   '- [ ] **T2 Next** | todo | Dependencies: None.\n')
        self.git('add', '.'); self.git('commit', '-qm', 'Shipped but still open')
        self.controller.config['delivery_batches'] = [{'id': 'shipped', 'tasks': ['T1']}]
        self.controller.initialize()
        self.controller.persist(task='T1', delivery_batch={'id': 'shipped', 'tasks': ['T1'], 'acceptance_tasks': []},
                                published_commit='a' * 40,
                                delivery_calls={self.controller.config['delivery_epoch'] + ':shipped':
                                                self.controller.config.get('max_calls_per_delivery', 1000)})
        self.controller.complete_release()
        self.assertEqual(self.controller.state['delivered_release']['tasks'], ['T1'])

    def test_released_task_still_open_goes_to_planner_not_developer(self):
        self.released_open_task()
        self.effects['planner'] = lambda: self.write('tasks.md', '- [x] **T1 Shipped** | done | Dependencies: None.\n'
                                                     '- [ ] **T2 Next** | todo | Dependencies: None.\n')
        self.effects['developer'] = lambda: self.write('app.txt', 'T2 change\n')
        self.controller.step()
        self.assertEqual(self.roles, ['planner'])
        self.assertEqual(self.controller.context('planner')['delivered_release']['commit'], 'a' * 40)
        self.assertEqual(self.controller.state['stage'], 'schedule')
        self.controller.step()
        self.assertEqual(self.roles, ['planner', 'developer'])
        self.assertEqual(self.controller.state['task'], 'T2')
        self.assertIsNone(self.controller.state['delivered_release'])

    def test_planner_routing_after_release_happens_only_once(self):
        self.released_open_task()
        self.controller.step()  # planner keeps T1 open with a concrete opening condition
        self.assertEqual(self.roles, ['planner'])
        self.controller.step()
        self.assertEqual(self.roles, ['planner'])  # existing delivery budget still guards the re-run
        self.assertEqual(self.controller.state['attention_kind'], 'delivery_budget')

    def test_batch_rejects_unknown_ids_and_oversized_groups(self):
        for tasks in (['T1', 'T999'], ['T1', 'T2', 'T3', 'T4'], ['T1', 'T1']):
            with self.subTest(tasks=tasks), self.assertRaises(ValueError):
                team.delivery_batch(self.project, {'delivery_batches': [{'id': 'invalid', 'tasks': tasks}]}, 'T1')

    def test_role_model_routing_and_release_diagnosis(self):
        self.assertEqual(set(self.controller.config['role_models']), team.ROLES)
        self.assertEqual(self.controller.worker_model('operations')['model'], 'gpt-6-luna')
        self.assertEqual(self.controller.worker_model('developer')['model'], 'gpt-6.1-sol')
        self.assertEqual(self.controller.worker_model('devops')['model'], 'gpt-6-luna')
        self.controller.state['release_recovery'] = {'active': True}
        self.assertEqual(self.controller.worker_model('devops')['model'], 'gpt-6.1-sol')
        self.assertEqual(self.controller.worker_model_args('qa'),
                         ['--model', 'gpt-6-sol', '-c', 'model_reasoning_effort="medium"'])
        self.assertEqual(self.controller.context('qa')['model_policy'], self.controller.worker_model('qa'))
        self.assertEqual(self.controller.worker_sandbox('devops'), 'read-only')

    def test_read_only_roles_receive_controller_written_review_input(self):
        self.write('app.txt', 'changed\n')
        self.write('new.txt', 'fresh\n')
        self.controller.state['snapshot'] = team.snapshot(self.project)['fingerprint']
        self.assertIsNone(self.controller.context('qa')['review_input'])
        self.controller.prepare_review_input('qa')
        self.controller.prepare_review_input('code_reviewer')
        paths = self.controller.context('code_reviewer')['review_input']
        info = json.loads(Path(paths['snapshot_file']).read_text(encoding='utf-8'))
        self.assertEqual(info['fingerprint'], self.controller.state['snapshot'])
        self.assertTrue(info['matches_assigned_snapshot'])
        self.assertIn('+changed', Path(paths['diff_file']).read_text(encoding='utf-8'))
        self.assertEqual(Path(paths['untracked_file']).read_text(encoding='utf-8').split(), ['new.txt'])
        self.assertFalse((self.controller.folder / 'artifacts' / 'qa' / 'review-input').exists())

    def test_missing_model_policy_inherits_and_invalid_policy_fails(self):
        self.controller.config.pop('role_models')
        self.assertEqual(self.controller.worker_model_args('qa'), [])
        self.controller.config['role_models'] = {'qa': {'model': 'gpt-6-luna', 'reasoning_effort': 'invalid'}}
        with self.assertRaisesRegex(ValueError, 'Invalid model policy'):
            self.controller.worker_model_args('qa')

    def test_retry_external_repair_reviews_before_stale_developer_assignment(self):
        self.adopted()
        self.controller.persist(stage='needs_attention',resume_role='developer',
                                release_recovery={'active':True,'incident':'a'*40},
                                release_recovery_calls={'release:'+'a'*40:11})
        self.write('app.txt','owner already repaired the finding\n')
        self.controller.stop.write_text('Owner maintenance',encoding='utf-8')
        self.controller.retry()
        self.assertEqual(self.controller.state['stage'],'code_reviewer')
        self.assertEqual(self.controller.state['resume_role'],'code_reviewer')
        self.assertEqual(self.controller.state['release_recovery_calls']['release:'+'a'*40],11)
        self.assertTrue(self.controller.stop.exists())
        self.controller.stop.unlink()
        self.controller.step()
        self.assertEqual(self.roles,['code_reviewer'])
        self.assertEqual(self.controller.state['stage'],'qa')

    def test_retry_unchanged_work_preserves_assignment_and_owner_stop(self):
        self.adopted()
        for role in ('developer','planner','qa','devops','environment_engineer','technical_lead'):
            with self.subTest(role=role):
                self.controller.persist(stage='waiting_for_quota',resume_role=role)
                self.controller.retry()
                self.assertEqual(self.controller.state['stage'],role)
        with self.assertRaisesRegex(RuntimeError,'No blocked stage'):
            self.controller.retry()
        self.controller.persist(stage='needs_attention')
        with patch.object(team,'competing_processes',return_value=[{'ProcessId':123}]):
            with self.assertRaisesRegex(RuntimeError,'Stop coordinator'):
                self.controller.retry()

    def test_dirty_initialization_requires_explicit_adoption(self):
        self.write('app.txt', 'owner changes')
        with self.assertRaisesRegex(RuntimeError, 'adopt-dirty'):
            self.controller.initialize()
        self.controller.initialize(adopt=True)
        self.assertTrue(self.controller.state['adopted_dirty'])
        self.assertEqual(self.controller.state['stage'], 'code_reviewer')
        self.assertEqual(self.git('log', '--format=%s').decode().strip(), 'Fixture baseline')

    def test_gate_order_and_exact_fingerprint(self):
        expected = self.approvals()
        for role in team.GATES:
            receipt = self.controller.state['receipts'][role]
            self.assertEqual(receipt['snapshot'], expected)
            self.assertEqual(receipt['report']['status'], 'passed')

    def test_source_change_invalidates_all_previous_approvals(self):
        old = self.approvals()
        self.write('app.txt', 'changed after review')
        self.controller.step()
        self.assertEqual(self.roles[-1], 'code_reviewer')
        self.assertEqual(set(self.controller.state['receipts']), {'code_reviewer'})
        self.assertNotEqual(self.controller.state['snapshot'], old)

    def test_read_only_and_qa_edits_rejected(self):
        self.adopted()
        for role in [*team.READ_ONLY, 'qa']:
            with self.subTest(role=role):
                self.effects[role] = lambda r=role: self.write('app.txt', r)
                self.controller.persist(snapshot=team.snapshot(self.project)['fingerprint'])
                with self.assertRaisesRegex(RuntimeError, 'changed source'):
                    self.controller.execute(role)
                self.assertNotIn(role, self.controller.state.get('receipts', {}))

    def test_planner_may_only_edit_valid_task_graph(self):
        self.controller.initialize()
        self.effects['planner'] = lambda: self.write('tasks.md', '- [ ] **T2 Planned work** | todo | Dependencies: None.\n')
        self.controller.execute('planner')
        self.assertEqual(team.backlog(self.project)[1], ['T2'])
        self.effects['planner'] = lambda: self.write('app.txt', 'unauthorized')
        with self.assertRaisesRegex(RuntimeError, 'outside tasks.md'):
            self.controller.execute('planner')

    def test_retry_budget_stops_repeated_gate_rejections(self):
        self.adopted()
        self.responses['code_reviewer'] = report('changes_requested', ['Fix demonstrated failure'])
        for _ in range(self.controller.config['max_fix_attempts'] + 1):
            self.controller.execute('code_reviewer')
        self.assertEqual(self.controller.state['stage'], 'technical_lead')
        self.assertEqual(self.controller.state['strategy_failure']['kind'], 'source_repair')

    def test_new_qa_issue_has_its_own_budget_despite_old_total(self):
        self.adopted()
        self.controller.persist(attempts=99)
        for finding in ['Repair authorization in app.ts:12', 'Repair Turkish disclosure in rooms.tsx:146', 'Repair delivery receipt in messages.tsx:84']:
            self.responses['qa'] = report('changes_requested', [finding])
            self.controller.execute('qa')
            self.assertEqual(self.controller.state['stage'], 'developer')
            self.assertEqual(self.controller.state['attempts'], 1)

    def test_repeated_issue_is_not_reset_by_an_additional_finding_or_line_change(self):
        self.adopted()
        for i in range(self.controller.config['max_fix_attempts'] + 1):
            self.responses['qa'] = report('changes_requested', ['Fix authorization in app.ts:' + str(10+i), 'Separate issue ' + str(i)])
            self.controller.execute('qa')
        self.assertEqual(self.controller.state['stage'], 'technical_lead')
        self.assertEqual(self.controller.state['attempts'], 3)

    def test_source_repair_strategy_returns_to_developer_without_qa_approval(self):
        self.adopted()
        self.controller.persist(stage='technical_lead', strategy_failure={'kind':'source_repair'})
        plan={'snapshot':self.controller.state['snapshot'],'kind':'source_repair','instructions':'Test the actual translator key normalization before changing the catalog.','evidence':['Existing lookup trims whitespace.']}
        self.effects['technical_lead'] = lambda: team.save(self.controller.folder / 'recovery-plan.json', plan)
        self.responses['technical_lead'] = report('completed')
        self.controller.execute('technical_lead')
        self.assertEqual(self.controller.state['stage'], 'developer')
        self.assertEqual(self.controller.state['attempts'], 0)
        self.assertNotIn('qa', self.controller.state['receipts'])
        self.assertEqual(self.controller.state['repair_strategy'], plan)

    def test_call_budget_prevents_another_worker(self):
        self.adopted()
        self.controller.persist(calls=self.controller.config['max_calls_per_start'])
        self.controller.step()
        self.assertEqual(self.roles, [])
        self.assertEqual(self.controller.state['stage'], 'needs_attention')

    def test_blocked_planner_keeps_intake_unconsumed(self):
        self.controller.initialize()
        team.save(self.controller.folder / 'inbox' / 'owner.json', {'text': 'Preserve this request'})
        self.responses['planner'] = report('blocked')
        self.controller.step()
        self.assertEqual(self.controller.state['stage'], 'needs_attention')
        self.assertEqual(len(self.controller.inputs()), 1)
        self.controller.step()
        self.assertEqual(self.roles, ['planner'])
        self.assertEqual(self.controller.state['seen_inputs'], [])
        self.responses['planner'] = report('completed')
        self.controller.persist(stage='planner')
        self.controller.step()
        self.assertEqual(self.controller.inputs(), [])

    def test_stale_commit_denied_without_changing_existing_index(self):
        expected = self.approvals()
        self.write('app.txt', 'unreviewed')
        self.git('add', 'app.txt')
        before = self.git('diff', '--cached', '--binary')
        with self.assertRaisesRegex(RuntimeError, 'exact reviewed snapshot'):
            self.controller.commit(expected, 'Do not commit stale source')
        self.assertEqual(self.git('diff', '--cached', '--binary'), before)

    def test_current_commit_preserves_owner_staged_changes(self):
        expected = self.approvals()
        self.git('add', 'app.txt')
        before = self.git('diff', '--cached', '--binary')
        with self.assertRaisesRegex(RuntimeError, 'Index already'):
            self.controller.commit(expected, 'Preserve owner index')
        self.assertEqual(self.git('diff', '--cached', '--binary'), before)

    def test_manual_commit_requires_every_gate_then_records_local_head(self):
        expected = self.approvals()
        qa = self.controller.state['receipts'].pop('qa')
        with self.assertRaisesRegex(RuntimeError, 'Missing current qa'):
            self.controller.commit(expected, 'Reviewed fixture change')
        self.controller.state['receipts']['qa'] = qa
        head = self.controller.commit(expected, 'Reviewed fixture change')
        self.assertEqual(self.git('rev-parse', 'HEAD').decode().strip(), head)
        self.assertEqual(self.controller.state['stage'], 'release_ready')
        self.assertEqual(self.git('status', '--porcelain'), b'')
        self.assertEqual(self.git('remote'), b'')

    def test_owner_stop_prevents_execution_and_requires_explicit_resume(self):
        self.controller.initialize()
        self.controller.stop.write_text('Owner stop', encoding='utf-8')
        with self.assertRaises(InterruptedError):
            self.controller.execute('developer')
        with self.assertRaisesRegex(RuntimeError, 'Owner STOP'):
            self.controller.acquire()
        self.assertEqual(self.roles, [])
        self.controller.acquire(resume=True)
        self.assertFalse(self.controller.stop.exists())
        self.controller.release()

    def test_invalid_task_graphs_rejected(self):
        cases = {
            'cycle': '- [ ] **T1 Work** | todo | Dependencies: T2.\n- [ ] **T2 Work** | todo | Dependencies: T1.\n',
            'missing': '- [ ] **T1 Work** | todo | Dependencies: T9.\n',
            'duplicate': '- [ ] **T1 Work** | todo | Dependencies: None.\n' * 2,
            'checkbox': '- [x] **T1 Work** | todo | Dependencies: None.\n',
        }
        for name, contents in cases.items():
            with self.subTest(name=name):
                self.write('tasks.md', contents)
                with self.assertRaises(ValueError):
                    team.backlog(self.project)

    def test_report_validation_rejects_missing_evidence_and_false_pass(self):
        bad = report()
        bad['evidence'] = []
        with self.assertRaises(ValueError):
            team.validate_report(bad, 'qa')
        with self.assertRaises(ValueError):
            team.validate_report(report(findings=['Unresolved failure']), 'qa')
        with self.assertRaises(ValueError):
            team.validate_report({**report(), 'extra': True}, 'qa')
        self.assertEqual(team.validate_report(report('blocked'), 'qa')['status'], 'blocked')

    def test_developer_cannot_modify_controller_policy(self):
        self.controller.initialize()
        self.effects['developer'] = lambda: self.write('agent-team/team.json', '{}')
        with self.assertRaisesRegex(RuntimeError, 'protected team policy'):
            self.controller.execute('developer')

    def test_gate_race_restarts_review_without_running_worker(self):
        self.adopted()
        self.controller.execute('code_reviewer')
        self.write('app.txt', 'race between schedule and gate')
        self.controller.execute('qa')
        self.assertEqual(self.roles, ['code_reviewer'])
        self.assertEqual(self.controller.state['stage'], 'code_reviewer')
        self.assertEqual(self.controller.state['receipts'], {})

    def test_operations_requires_repeated_failures_and_routes_findings_to_planner(self):
        self.controller.initialize()
        self.controller.config['operations_interval_seconds'] = 0
        with patch.object(team.urllib.request, 'urlopen', side_effect=OSError('offline fixture')):
            self.controller.check_operations()
            self.assertFalse(self.controller.state.get('pending_operations', False))
            self.controller.check_operations()
        self.assertTrue(self.controller.state['pending_operations'])
        self.responses['operations'] = report('changes_requested', ['Public readiness unavailable twice'])
        self.controller.step()
        self.assertEqual(self.roles, ['operations'])
        self.assertEqual(self.controller.state['stage'], 'planner')
        self.assertFalse(self.controller.state['pending_operations'])
        response = unittest.mock.MagicMock()
        response.__enter__.return_value = response
        response.status = 200
        response.read.return_value = b'{"status":"ready","release":"fixture"}'
        with patch.object(team.urllib.request, 'urlopen', return_value=response):
            self.controller.check_operations()
        self.assertEqual(self.controller.state['health_failures'], 0)
        self.assertFalse(self.controller.state['health_incident_open'])

    def worker_metadata(self):
        role_dir = self.home / 'agents' / 'qa'
        role_dir.mkdir(parents=True)
        team.save(role_dir / 'role.json', {'id': 'qa', 'worker': True, 'sandbox': self.controller.worker_sandbox('qa')})
        (role_dir / 'prompt.md').write_text('Return test evidence only.', encoding='utf-8')

    def test_failed_cli_turn_rejects_even_valid_output_report(self):
        self.worker_metadata()
        fake = unittest.mock.MagicMock()
        fake.pid = 123456
        fake.stdout = io.StringIO('{"type":"turn.failed","error":{"message":"fixture failure"}}\n')
        fake.stdin = io.StringIO()
        fake.returncode = 1
        fake.poll.return_value = 1

        def spawn(args, **kwargs):
            self.assertEqual(args[args.index('--model') + 1], 'gpt-6-sol')
            self.assertIn('model_reasoning_effort="medium"', args)
            team.save(Path(args[args.index('-o') + 1]), report())
            return fake

        with patch.object(team.shutil, 'which', return_value='fake-codex'), patch.object(team.subprocess, 'Popen', side_effect=spawn), patch.object(team, 'attach_worker_job', return_value=None):
            with self.assertRaisesRegex(RuntimeError, 'CLI failed'):
                self.controller.run_worker('qa')
        self.assertIsNone(self.controller.state['worker_pid'])

    def test_quiet_worker_observes_stop_and_timeout(self):
        self.worker_metadata()
        self.controller.config['stop_grace_seconds'] = 0
        self.controller.config['worker_timeout_seconds'] = -1
        fake = unittest.mock.MagicMock()
        fake.pid = 123456
        fake.stdin = io.StringIO()
        fake.stdout = io.StringIO('')
        fake.returncode = None
        with patch.object(team.shutil, 'which', return_value='fake-codex'), patch.object(team.subprocess, 'Popen', return_value=fake), patch.object(team, 'terminate_owned') as terminate, patch.object(team, 'attach_worker_job', return_value=None):
            with self.assertRaisesRegex(TimeoutError, 'deadline'):
                self.controller.run_worker('qa')
            terminate.assert_called_once_with(fake)
            self.controller.stop.write_text('Owner stop', encoding='utf-8')
            fake.stdin = io.StringIO()
            with self.assertRaises(InterruptedError):
                self.controller.run_worker('qa')
        self.assertIsNone(self.controller.state['worker_pid'])

    def test_publication_refuses_wrong_stage_commit_and_dirty_snapshot(self):
        expected = self.approvals()
        head = self.controller.commit(expected, 'Reviewed fixture change')
        self.controller.persist(stage='ready_for_commit')
        with self.assertRaisesRegex(RuntimeError, 'exact committed'):
            self.controller.publish(head)
        self.controller.persist(stage='release_ready')
        with self.assertRaisesRegex(RuntimeError, 'exact committed'):
            self.controller.publish('0' * 40)
        self.write('app.txt', 'unreviewed release edit')
        with self.assertRaisesRegex(RuntimeError, 'exact committed'):
            self.controller.publish(head)
        self.git('add', 'app.txt')
        self.write('app.txt', 'owner changes\n')
        staged = self.git('diff', '--cached', '--binary')
        with self.assertRaisesRegex(RuntimeError, 'clean workspace'):
            self.controller.publish(head)
        self.assertEqual(self.git('diff', '--cached', '--binary'), staged)

    def test_publication_sends_only_reviewed_head_to_expected_remote(self):
        expected = self.approvals()
        head = self.controller.commit(expected, 'Reviewed fixture change')
        actual_git = team.git
        calls = []

        def safe_git(project, *args):
            calls.append(args)
            if args[:2] == ('remote', 'get-url'):
                return b'https://github.com/bolatahmett/AfterDark.git\n'
            if args[0] == 'ls-remote':
                return (head + '\trefs/heads/main\n').encode()
            if args[0] == 'push':
                return b''
            return actual_git(project, *args)

        with patch.object(team, 'git', side_effect=safe_git):
            self.assertEqual(self.controller.publish(head), head)
        self.assertIn(('push', 'origin', head + ':refs/heads/main'), calls)
        self.assertEqual(self.controller.state['stage'], 'published')

    def test_failed_and_quota_stages_preserve_partial_edits_without_auto_review(self):
        self.controller.initialize()
        original = self.controller.state['snapshot']
        for stage in ('needs_attention', 'waiting_for_quota'):
            with self.subTest(stage=stage):
                self.write('app.txt', 'retained partial edits ' + stage)
                self.controller.persist(stage=stage, reason='Explicit retry required', snapshot=original)
                self.controller.step()
                self.controller.step()
                self.assertEqual(self.controller.state['stage'], stage)
                self.assertEqual(self.controller.state['snapshot'], original)
                self.assertEqual(self.roles, [])
                self.assertEqual((self.project / 'app.txt').read_text(encoding='utf-8'), 'retained partial edits ' + stage)

    def test_loop_stop_interruption_preserves_work_and_requires_explicit_retry(self):
        self.controller.initialize()

        def interrupted_developer():
            self.write('app.txt', 'partial work before owner stop')
            self.controller.stop.write_text('Owner stop', encoding='utf-8')
            raise InterruptedError('Owner STOP')

        self.effects['developer'] = interrupted_developer
        with patch.object(self.controller, 'check_operations') as health:
            self.controller.loop(once=True)
        health.assert_not_called()
        self.assertEqual(self.controller.state['stage'], 'needs_attention')
        self.assertEqual(self.controller.state['resume_role'], 'developer')
        self.assertEqual(self.controller.state['controller_status'], 'stopped')
        self.assertTrue(self.controller.stop.exists())
        self.assertFalse(self.controller.lock.exists())
        self.assertEqual((self.project / 'app.txt').read_text(encoding='utf-8'), 'partial work before owner stop')
        self.controller.step()
        self.assertEqual(self.roles, ['developer'])


    def test_scoped_pass_accepts_limitations_but_still_rejects_real_findings(self):
        for role in team.GATES:
            with self.subTest(role=role):
                scoped = report()
                scoped['limitations'] = ['Physical-device checks are outside this source-review scope']
                self.assertEqual(team.validate_report(scoped, role), scoped)
                scoped['findings'] = ['Actual authorization failure at the reviewed path']
                with self.assertRaisesRegex(ValueError, 'Unresolved findings'):
                    team.validate_report(scoped, role)
        legacy = report()
        del legacy['limitations']
        with self.assertRaisesRegex(ValueError, 'Invalid report fields'):
            team.validate_report(legacy, 'code_reviewer')

    def test_required_qa_acceptance_remains_blocked_with_limitations(self):
        self.controller.initialize(adopt=False)
        self.controller.persist(stage='qa')
        blocked = report('blocked')
        blocked['limitations'] = ['Required browser acceptance could not run']
        self.responses['qa'] = blocked
        self.controller.step()
        self.assertEqual(self.controller.state['stage'], 'needs_attention')
        self.assertEqual(self.controller.state['receipts'], {})

    def test_issue_intake_rejects_control_only_text_and_preserves_normal_text(self):
        for invalid in ('', ' \n\t ', '\x18', 'Visible\x00text', '\u200b', 'a' * 8001):
            with self.subTest(text=repr(invalid[:30])):
                with self.assertRaises(ValueError):
                    team.validate_intake(invalid)
        self.assertEqual(team.validate_intake('  Mobile issue\nSteps:\tclose the page  '), 'Mobile issue\nSteps:\tclose the page')

    def test_missing_acceptance_hands_independent_ready_work_to_planner(self):
        self.write('tasks.md', '- [ ] **T1 Work** | in_progress | Dependencies: None.\n- [ ] **T2 Other** | todo | Dependencies: None.\n')
        self.controller.initialize(adopt=True)
        self.controller.persist(stage='qa', task='T1')
        self.responses['qa'] = report('blocked')
        self.responses['qa']['limitations'] = ['Required authorized browser is unavailable']
        self.controller.step()
        self.assertEqual(self.controller.state['stage'], 'planner')
        self.assertEqual(self.controller.state['deferred_reports'][0]['task'], 'T1')
        self.assertEqual(self.controller.state['receipts'], {})
        self.assertEqual(self.roles, ['qa'])


class LocalWaitTests(unittest.TestCase):
    setUp=TeamTests.setUp
    write=TeamTests.write
    git=TeamTests.git
    run_role=TeamTests.run_role
    adopted=TeamTests.adopted
    def prepare_wait(self, seconds=60):
        self.adopted()
        self.controller.persist(stage='qa',task='T1')
        result=report('blocked')
        result['next_action']=f'WAIT_LOCAL_RATE_LIMIT seconds={seconds}; Resume only incomplete scenarios'
        result['evidence']=['Local synthetic endpoint returned 429; observed Retry-After 60 seconds']
        self.responses['qa']=result
        self.controller.step()

    def test_wait_does_not_call_agents_before_deadline_and_survives_reload(self):
        self.prepare_wait()
        self.assertEqual(self.controller.state['stage'],'waiting_local')
        restored=team.Team(self.project,self.home,runner=self.run_role)
        restored.step()
        self.assertEqual(self.roles,['qa'])
        with patch.object(team.time,'time',return_value=restored.state['local_wait']['not_before']+1):
            restored.step()
        self.assertEqual(restored.state['stage'],'qa')
        self.assertEqual(self.roles,['qa'])
        self.assertIn('qa',restored.state['reports'])

    def test_stop_prevents_due_wait_resume(self):
        self.prepare_wait()
        self.controller.stop.write_text('Owner STOP',encoding='utf-8')
        with patch.object(team.time,'time',return_value=self.controller.state['local_wait']['not_before']+1):
            self.controller.step()
        self.assertEqual(self.controller.state['stage'],'waiting_local')
        self.assertEqual(self.roles,['qa'])

    def test_changed_source_requires_review_and_invalidates_affected_gate(self):
        self.prepare_wait()
        self.write('app.txt','changed while waiting')
        with patch.object(team.time,'time',return_value=self.controller.state['local_wait']['not_before']+1):
            self.controller.step()
        self.assertEqual(self.controller.state['stage'],'code_reviewer')
        self.assertEqual(self.controller.state['receipts'],{})

    def test_two_attempt_budget_survives_source_changes(self):
        self.prepare_wait()
        for n in range(2):
            self.controller.persist(stage='qa')
            self.controller.step()
        self.assertEqual(self.controller.state['stage'],'needs_attention')
        self.assertEqual(self.controller.state['attention_kind'],'local_wait_exhausted')
        self.assertEqual(self.controller.state['local_wait_attempts']['T1:local_rate_limit'],2)

    def test_unknown_blocker_and_invalid_delay_do_not_auto_retry(self):
        for action in ('Wait for owner approval','WAIT_LOCAL_RATE_LIMIT seconds=0; invalid',
                       'WAIT_LOCAL_RATE_LIMIT seconds=3601; invalid'):
            with self.subTest(action=action):
                result=report('blocked');result['next_action']=action
                self.assertFalse(self.controller.schedule_local_wait('qa',result,{'fingerprint':'test'},'report'))

    def test_non_qa_or_source_findings_cannot_schedule_wait(self):
        result=report('blocked');result['next_action']='WAIT_LOCAL_RATE_LIMIT seconds=60; retry'
        self.assertFalse(self.controller.schedule_local_wait('devops',result,{'fingerprint':'test'},'report'))
        result['findings']=['Authorization bug']
        self.assertFalse(self.controller.schedule_local_wait('qa',result,{'fingerprint':'test'},'report'))


if __name__ == '__main__':
    unittest.main()
