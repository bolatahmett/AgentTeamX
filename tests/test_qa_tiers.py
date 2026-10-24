"""QA fast paths: scope contract, tiers, preflight, source checks and scenario suites.

All workers and commands are mocked; nothing here starts a model, a browser or a paid service."""
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
import subprocess
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import qa_tiers
import resilience
import team


def report(status='passed', findings=None):
    return {'status': status, 'summary': 'Deterministic test evidence', 'evidence': ['Verified fixture'],
            'findings': findings or [], 'limitations': [], 'capability_requests': [],
            'next_action': 'Continue the reviewed workflow'}


TASKS = ('## Execution rules\n\n- Keep evidence honest.\n\n## Tasks\n\n'
         '- [ ] **T1 Work** | todo | Dependencies: None. Acceptance: the page loads.\n'
         '  Delivery record: nothing yet.\n\n## Work log\n\n- 2026-01-01 started.\n')


class ScopeContractTests(unittest.TestCase):
    def test_bookkeeping_edits_do_not_change_the_contract_digest(self):
        base = resilience.tasks_contract_digest(TASKS)
        status = TASKS.replace('- [ ] **T1 Work** | todo |', '- [x] **T1 Work** | done |')
        record = TASKS.replace('Delivery record: nothing yet.', 'Delivery record: delivered in abc123.')
        log = TASKS + '- 2026-01-02 more evidence.\n'
        crlf = TASKS.replace('\n', '\r\n')
        for variant in (status, record, log, crlf):
            self.assertEqual(resilience.tasks_contract_digest(variant), base)

    def test_acceptance_or_definition_edits_change_the_digest(self):
        base = resilience.tasks_contract_digest(TASKS)
        for variant in (TASKS.replace('the page loads', 'the page loads offline'),
                        TASKS.replace('Work', 'Other work'),
                        TASKS.replace('## Execution rules\n\n- Keep evidence honest.', '## Execution rules\n\n- Skip evidence.')):
            self.assertNotEqual(resilience.tasks_contract_digest(variant), base)

    def test_scopes_overrides_replace_only_the_named_file(self):
        files = {'tasks.md': 'a' * 64, 'src/app.ts': 'b' * 64}
        plain = resilience.scopes(files)
        overridden = resilience.scopes(files, {'tasks.md': 'c' * 64})
        self.assertEqual(plain['application'], overridden['application'])
        self.assertNotEqual(plain['environment'], overridden['environment'])
        self.assertEqual(set(overridden), {'application', 'environment', 'team'})


class PureHelperTests(unittest.TestCase):
    def scopes(self, app='a', env='e'):
        return {'application': app, 'environment': env, 'team': 't'}

    def last(self):
        return {'scopes': self.scopes(), 'ui': 'u', 'snapshot': 's', 'tier': 2, 'at': 'now'}

    def test_tier_selection(self):
        cls = qa_tiers.classify
        self.assertEqual(cls(None, self.scopes(), 'u')[0], 2)
        self.assertEqual(cls(self.last(), self.scopes(), 'u')[0], 0)
        self.assertEqual(cls(self.last(), self.scopes(app='b'), 'u')[0], 1)
        self.assertEqual(cls(self.last(), self.scopes(app='b'), 'other-ui')[0], 2)
        self.assertEqual(cls(self.last(), self.scopes(env='f'), 'u')[0], 2)
        self.assertEqual(cls(self.last(), self.scopes(), 'u', 'forced')[0], 2)
        self.assertEqual(cls({'scopes': {}, 'ui': 'u'}, self.scopes(), 'u')[0], 2)
        self.assertEqual(cls(self.last(), self.scopes(env='f'), 'u', None, True)[0], 1)
        self.assertEqual(cls(self.last(), self.scopes(env='f', app='b'), 'u', None, True)[0], 2)
        self.assertEqual(cls(self.last(), self.scopes(env='f'), 'u', 'forced', True)[0], 2)

    def test_ui_digest_tracks_only_configured_prefixes(self):
        files = {'apps/web/a.tsx': '1', 'apps/api/b.ts': '2'}
        first = qa_tiers.ui_digest(files, ['apps/web/'])
        self.assertEqual(first, qa_tiers.ui_digest({**files, 'apps/api/b.ts': '3'}, ['apps/web/']))
        self.assertNotEqual(first, qa_tiers.ui_digest({**files, 'apps/web/a.tsx': '9'}, ['apps/web/']))

    def test_preflight_reports_each_missing_prerequisite(self):
        cfg = {'tools': ['git'], 'files': ['x.ps1'], 'browser_paths': ['chrome.exe'], 'ports_free': [3443]}
        failures = qa_tiers.preflight('.', cfg, which=lambda n: None, exists=lambda p: False, in_use=lambda p: True)
        self.assertEqual([c for c, _ in failures], ['build_tools', 'build_tools', 'browser', 'local_runtime'])
        ok = qa_tiers.preflight('.', cfg, which=lambda n: '/bin/git', exists=lambda p: True, in_use=lambda p: False)
        self.assertEqual(ok, [])
        blocked = qa_tiers.report_preflight(failures)
        self.assertEqual(blocked['status'], 'blocked')
        self.assertEqual(blocked['capability_requests'], ['build_tools', 'browser', 'local_runtime'])
        team.validate_report(blocked, 'qa')

    def test_fast_path_reports_are_valid_gate_reports_that_claim_no_browser_run(self):
        team.validate_report(qa_tiers.report_unchanged(self.last()), 'qa')
        checks = [{'id': 'lint', 'exit': 0, 'seconds': 3, 'log': 'l.log'}]
        report = qa_tiers.report_source_checks(checks)
        team.validate_report(report, 'qa')
        self.assertIn('browser', ' '.join(report['limitations']))


class SuiteContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.qa = Path(self.temp.name) / 'qa'
        (self.qa / 'suites').mkdir(parents=True)
        (self.qa / 'run.ps1').write_text('exit 0\n', encoding='utf-8')

    def manifest(self, **over):
        value = {'id': 'T64', 'tasks': ['T64'], 'scenarios': ['A', 'B'], 'script': 'run.ps1',
                 'result_file': 'result.json', 'args': ['-S', '{snapshot}']}
        value.update(over)
        return value

    def test_valid_manifest_resolves_inside_the_qa_directory(self):
        suite = qa_tiers.validate_manifest(self.manifest(), self.qa)
        self.assertTrue(suite['script'].is_relative_to(self.qa.resolve()))
        self.assertEqual(suite['timeout_seconds'], 1500)

    def test_unsafe_manifests_are_rejected(self):
        for bad in (self.manifest(script='../run.ps1'), self.manifest(script='/etc/passwd'),
                    self.manifest(result_file='../x.json'), self.manifest(script='missing.ps1'),
                    self.manifest(scenarios=[]), self.manifest(scenarios=['A', 'A']),
                    self.manifest(tasks=['not-a-task']), self.manifest(timeout_seconds=5),
                    self.manifest(args=['ok', 7]), self.manifest(extra=1), {'id': 'x'}):
            with self.assertRaises(ValueError):
                qa_tiers.validate_manifest(bad, self.qa)

    def test_load_suites_reports_invalid_manifests_without_running_them(self):
        (self.qa / 'suites' / 'good.json').write_text(json.dumps(self.manifest()), encoding='utf-8')
        (self.qa / 'suites' / 'bad.json').write_text(json.dumps(self.manifest(script='../x.ps1')), encoding='utf-8')
        suites, errors = qa_tiers.load_suites(self.qa, lambda p: json.loads(p.read_text(encoding='utf-8')))
        self.assertEqual([s['id'] for s in suites], ['T64'])
        self.assertEqual(len(errors), 1)
        self.assertIn('bad.json', errors[0])

    def test_matching_requires_every_task_and_previously_seen_scenario(self):
        suite = qa_tiers.validate_manifest(self.manifest(tasks=['T64', 'T65']), self.qa)
        self.assertIs(qa_tiers.matching_suite([suite], ['T64'], ['A']), suite)
        self.assertIsNone(qa_tiers.matching_suite([suite], ['T64', 'T66'], None))
        self.assertIsNone(qa_tiers.matching_suite([suite], ['T64'], ['A', 'Z']))
        self.assertIsNone(qa_tiers.matching_suite([suite], [], None))

    def test_command_never_goes_through_a_shell_string(self):
        suite = qa_tiers.validate_manifest(self.manifest(), self.qa)
        command = qa_tiers.suite_command(suite, 'snap1', {'powershell': 'pwsh'})
        self.assertEqual(command[:1], ['pwsh'])
        self.assertEqual(command[-2:], ['-S', 'snap1'])
        self.assertIn('-File', command)

    def result(self, **over):
        value = {'suite': 'T64', 'snapshot': 'snap1', 'scenarios': [
            {'id': 'A', 'status': 'passed', 'evidence': ['saw A']}, {'id': 'B', 'status': 'passed', 'evidence': ['saw B']}]}
        value.update(over)
        return value

    def test_suite_passes_only_with_every_scenario_observed_on_this_snapshot(self):
        suite = qa_tiers.validate_manifest(self.manifest(), self.qa)
        self.assertTrue(qa_tiers.evaluate_suite(suite, self.result(), 'snap1')['ok'])
        stale = qa_tiers.evaluate_suite(suite, self.result(), 'snap2')
        self.assertFalse(stale['ok'])
        other = qa_tiers.evaluate_suite(suite, self.result(suite='other'), 'snap1')
        self.assertFalse(other['ok'])
        failed = self.result(); failed['scenarios'][1] = {'id': 'B', 'status': 'failed', 'evidence': ['broke']}
        outcome = qa_tiers.evaluate_suite(suite, failed, 'snap1')
        self.assertEqual((outcome['ok'], outcome['failed']), (False, ['B']))
        missing = self.result(scenarios=self.result()['scenarios'][:1])
        self.assertEqual(qa_tiers.evaluate_suite(suite, missing, 'snap1')['missing'], ['B'])
        skipped = self.result(); skipped['scenarios'][0]['status'] = 'skipped'
        self.assertFalse(qa_tiers.evaluate_suite(suite, skipped, 'snap1')['ok'])
        bare = self.result(); bare['scenarios'][0]['evidence'] = []
        self.assertFalse(qa_tiers.evaluate_suite(suite, bare, 'snap1')['ok'])
        self.assertFalse(qa_tiers.evaluate_suite(suite, None, 'snap1')['ok'])
        self.assertFalse(qa_tiers.evaluate_suite(suite, {'suite': 'T64', 'snapshot': 'snap1'}, 'snap1')['ok'])

    def test_progress_completes_only_pending_scenarios_covered_by_a_passing_suite(self):
        suite = qa_tiers.validate_manifest(self.manifest(), self.qa)
        outcome = qa_tiers.evaluate_suite(suite, self.result(), 'snap1')
        previous = {'task': 'T64', 'snapshot': 'old', 'completed': [{'id': 'A', 'evidence': ['earlier']}], 'remaining': ['B']}
        done = qa_tiers.progress_from_suite(previous, 'T64', 'snap1', suite, outcome)
        self.assertEqual(done['remaining'], [])
        self.assertEqual([i['id'] for i in done['completed']], ['A', 'B'])
        uncovered = {**previous, 'remaining': ['B', 'Z']}
        self.assertIsNone(qa_tiers.progress_from_suite(uncovered, 'T64', 'snap1', suite, outcome))


class ControllerFastPathTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        self.home = self.project / 'agent-team'
        self.home.mkdir()
        config = json.loads((Path(team.__file__).parent / 'team.json').read_text(encoding='utf-8-sig'))
        config.update(auto_commit=False, qa_owns_environment=False, autonomous_intervention=False,
                      engine_failover=False, max_calls_per_delivery=1000, max_calls_per_start=1000,
                      archive_done_tasks=False)
        config['qa_tiers'] = {'enabled': True, 'ui_paths': ['apps/web/'], 'suites': True,
                              'shell': ['powershell', '-NoProfile', '-Command'],
                              'source_checks': [{'id': 'typecheck', 'command': 'pnpm typecheck'},
                                                {'id': 'test', 'command': 'pnpm test'}],
                              'preflight': {}}
        team.save(self.home / 'team.json', config)
        self.write('.gitignore', '.supervisor/\n')
        self.write('tasks.md', TASKS)
        self.write('app.txt', 'original\n')
        self.write('apps/web/page.txt', 'ui\n')
        self.git('init', '-q')
        self.git('config', 'user.name', 'Fixture')
        self.git('config', 'user.email', 'fixture@example.invalid')
        self.git('config', 'commit.gpgsign', 'false')
        self.git('config', 'core.hooksPath', str(self.project / 'no-hooks'))
        self.git('add', '.')
        self.git('commit', '-qm', 'Fixture baseline')
        self.roles = []
        self.owned = []
        self.owned_exit = {}
        self.suite_writer = None
        self.controller = team.Team(self.project, self.home)
        for target in (patch.object(team, 'competing_processes', return_value=[]),
                       patch.object(team.Team, 'run_worker_engine', side_effect=self.engine),
                       patch.object(team.Team, 'run_owned', side_effect=self.fake_owned),
                       patch.object(team.Team, 'qa_hosts', return_value={'powershell': 'pwsh', 'python': sys.executable}),
                       patch.object(team.Team, 'start_qa_runtime', side_effect=self.fake_runtime),
                       patch.object(team.Team, 'stop_qa_runtime', side_effect=lambda handle: self.runtimes.append('stop'))):
            target.start()
            self.addCleanup(target.stop)
        self.runtimes = []

    def write(self, name, text):
        path = self.project / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.project), *args], check=True, capture_output=True).stdout

    def engine(self, role, engine='codex'):
        self.roles.append(role)
        status = getattr(self, 'engine_status', {}).get(role)
        return report(status or ('completed' if role in {'planner', 'developer'} else 'passed'))

    def fake_runtime(self, current):
        self.runtimes.append('start')
        return {'url': 'http://localhost:3443', 'snapshot': current['fingerprint'], 'log': 'runtime.log'}

    def fake_owned(self, args, log, timeout, cwd=None):
        self.owned.append(list(args))
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text('fake\n', encoding='utf-8')
        if self.suite_writer and '-File' in args:
            self.suite_writer(args)
            return 0, 7
        for name, code in self.owned_exit.items():
            if args[-1].endswith(name):
                return code, 2
        return 0, 2

    def fingerprint(self):
        return team.snapshot(self.project)['fingerprint']

    def run_chain(self):
        """Adopt an owner change and run the three gates to ready_for_commit."""
        self.write('app.txt', 'owner changes\n')
        self.controller.initialize(adopt=True)
        for _ in range(3):
            self.controller.step()
        self.assertEqual(self.controller.state['stage'], 'ready_for_commit')

    def rerun_qa(self):
        self.roles.clear()
        self.owned.clear()
        self.controller.persist(stage='qa', snapshot=self.fingerprint(), receipts={})
        self.controller.step()

    def test_first_pass_needs_the_model_and_is_remembered(self):
        self.run_chain()
        self.assertEqual(self.roles, ['code_reviewer', 'qa', 'devops'])
        last = self.controller.state['last_qa_pass']
        self.assertEqual(last['tier'], 2)
        self.assertEqual(last['snapshot'], self.controller.state['snapshot'])

    def test_task_bookkeeping_reuses_the_pass_without_a_model_turn_or_budget(self):
        self.run_chain()
        calls, delivery = self.controller.state['calls'], dict(self.controller.state['delivery_calls'])
        self.write('tasks.md', TASKS.replace('- [ ] **T1 Work** | todo |', '- [x] **T1 Work** | done |')
                   .replace('Delivery record: nothing yet.', 'Delivery record: delivered.') + '- 2026-01-03 recorded.\n')
        self.rerun_qa()
        self.assertEqual(self.roles, [])
        self.assertEqual(self.owned, [])
        self.assertEqual(self.controller.state['stage'], 'devops')
        self.assertEqual(self.controller.state['qa_fast_path']['tier'], 0)
        self.assertIn('qa', self.controller.state['receipts'])
        # code_reviewer is outside the fast path, qa spent nothing: the counters only grew for work that ran.
        self.assertEqual(self.controller.state['calls'], calls)
        self.assertEqual(self.controller.state['delivery_calls'], delivery)

    def test_acceptance_text_edit_requires_a_new_acceptance_turn(self):
        self.run_chain()
        self.write('tasks.md', TASKS.replace('the page loads', 'the page loads offline'))
        self.rerun_qa()
        self.assertEqual(self.roles, ['qa'])
        self.assertEqual(self.controller.state['qa_fast_path']['tier'], 2)

    def test_non_ui_change_passes_on_source_checks_alone(self):
        self.run_chain()
        self.write('app.txt', 'backend only change\n')
        self.rerun_qa()
        self.assertEqual(self.roles, [])
        self.assertEqual([a[-1] for a in self.owned], ['pnpm typecheck', 'pnpm test'])
        self.assertEqual(self.controller.state['stage'], 'devops')
        stored = team.load(self.project / self.controller.state['reports']['qa'])
        self.assertEqual(stored['report']['status'], 'passed')
        self.assertIn('typecheck', stored['report']['evidence'][0])
        self.assertEqual(self.controller.state['last_qa_pass']['tier'], 1)

    def test_failed_source_check_hands_triage_to_the_agent_instead_of_failing_the_gate(self):
        self.run_chain()
        self.write('app.txt', 'backend only change\n')
        self.owned_exit['pnpm test'] = 1
        self.rerun_qa()
        self.assertEqual(self.roles, ['qa'])
        info = self.controller.state['qa_fast_path']
        self.assertEqual([c['id'] for c in info['source_checks']], ['typecheck', 'test'])
        self.assertEqual(info['source_checks'][-1]['exit'], 1)
        self.assertEqual(self.controller.context('qa')['qa_fast_path']['tier'], 1)
        self.assertEqual(self.controller.state['stage'], 'devops')  # the agent, not the check, decided

    def test_source_checks_that_modify_files_do_not_pass(self):
        self.run_chain()
        self.write('app.txt', 'backend only change\n')
        original = self.fake_owned

        def mutate(args, log, timeout, cwd=None):
            self.write('generated.txt', 'created by the check\n')
            return original(args, log, timeout, cwd)
        with patch.object(team.Team, 'run_owned', side_effect=mutate):
            with self.assertRaisesRegex(RuntimeError, 'qa changed source'):
                self.rerun_qa()
        # The tampered tree is never passed by the fast path: it declines, and the changed-source guard rejects the turn.
        self.assertEqual(self.roles, ['qa'])
        self.assertNotEqual(self.controller.state['stage'], 'devops')
        self.assertIn('snapshot-stability', [c['id'] for c in self.controller.state['qa_fast_path']['source_checks']])

    def source_only(self):
        self.controller.config['qa_tiers']['mode'] = 'source_only'

    def test_source_only_first_pass_and_ui_change_use_source_checks_without_a_model_turn(self):
        self.source_only()
        self.run_chain()
        self.assertEqual(self.roles, ['code_reviewer', 'devops'])
        self.assertEqual(self.controller.state['last_qa_pass']['tier'], 1)
        self.write('apps/web/page.txt', 'ui changed\n')
        self.rerun_qa()
        self.assertEqual(self.roles, [])
        self.assertEqual(self.controller.state['stage'], 'devops')
        stored = team.load(self.project / self.controller.state['reports']['qa'])
        self.assertIn('browser acceptance is deferred', stored['report']['summary'])

    def test_source_only_ignores_acceptance_forcing(self):
        self.source_only()
        self.run_chain()
        self.controller.config['qa_acceptance_tasks'] = [self.controller.state.get('task')]
        self.controller.persist(delivery_batch={'id': 'b', 'tasks': ['T1'], 'acceptance_tasks': ['T2']})
        self.write('apps/web/page.txt', 'ui changed\n')
        self.rerun_qa()
        self.assertEqual(self.roles, [])
        self.assertEqual(self.controller.state['qa_fast_path']['tier'], 1)

    def test_uncommitted_ui_change_gets_the_controller_runtime(self):
        self.run_chain()
        cfg = self.controller.qa_tiers_config()
        self.controller.persist(task='T1')
        self.write('app.txt', 'backend only change\n')
        self.assertFalse(self.controller.uncommitted_ui_change(cfg))
        self.write('apps/web/page.txt', 'ui changed\n')
        self.assertTrue(self.controller.uncommitted_ui_change(cfg))

    def test_source_only_failure_requests_developer_repair_without_a_qa_turn(self):
        self.source_only()
        self.run_chain()
        calls = self.controller.state['calls']
        self.write('app.txt', 'backend only change\n')
        self.owned_exit['pnpm test'] = 1
        self.rerun_qa()
        self.assertEqual(self.roles, [])
        stored = team.load(self.project / self.controller.state['reports']['qa'])
        self.assertEqual(stored['report']['status'], 'changes_requested')
        self.assertIn('Source check test failed', stored['report']['findings'][0])
        self.assertIn('fake', stored['report']['findings'][0])
        self.assertEqual(self.controller.state['stage'], 'developer')
        self.assertEqual(self.controller.state['calls'], calls)

    def test_ui_change_needs_browser_acceptance(self):
        self.run_chain()
        self.write('apps/web/page.txt', 'ui changed\n')
        self.rerun_qa()
        self.assertEqual(self.roles, ['qa'])
        self.assertEqual(self.controller.state['qa_fast_path']['tier'], 2)
        self.assertEqual(self.controller.state['last_qa_pass']['tier'], 2)

    def test_missing_prerequisites_block_without_a_model_turn(self):
        self.run_chain()
        self.write('apps/web/page.txt', 'ui changed\n')
        self.controller.config['qa_tiers']['preflight'] = {'files': ['scripts/use-dev-tools.ps1']}
        self.roles.clear()
        self.controller.persist(stage='qa', snapshot=self.fingerprint(), receipts={})
        current = team.snapshot(self.project)
        self.controller.persist(snapshot=current['fingerprint'])
        blocked = self.controller.qa_fast_path()
        self.assertEqual(blocked['status'], 'blocked')
        self.assertEqual(blocked['capability_requests'], ['build_tools'])
        self.assertEqual(self.roles, [])
        self.assertFalse(self.controller.__dict__.get('free_turn'))

    def write_suite(self, scenarios=('T54.a', 'T54.b'), tasks=('T1',)):
        qa = self.home / '..'
        qa = self.controller.folder / 'artifacts' / 'qa'
        (qa / 'suites').mkdir(parents=True, exist_ok=True)
        (qa / 'run-suite.ps1').write_text('exit 0\n', encoding='utf-8')
        manifest = {'id': 'S1', 'tasks': list(tasks), 'scenarios': list(scenarios), 'script': 'run-suite.ps1',
                    'args': ['-ExpectedSnapshot', '{snapshot}'], 'result_file': 'result-S1.json', 'timeout_seconds': 600}
        (qa / 'suites' / 'S1.json').write_text(json.dumps(manifest), encoding='utf-8')

        def writer(args, status='passed'):
            snapshot = args[args.index('-ExpectedSnapshot') + 1]
            (qa / 'result-S1.json').write_text(json.dumps({'suite': 'S1', 'snapshot': snapshot, 'scenarios': [
                {'id': s, 'status': status, 'evidence': ['observed ' + s]} for s in scenarios]}), encoding='utf-8')
        self.suite_writer = writer
        return qa, writer

    def acceptance_rows(self):
        self.write('tasks.md', '- [ ] **T1 - Verify one** | in_progress | Dependencies: None.\n'
                               '- [ ] **T2 - Verify two** | in_progress | Dependencies: None.\n')
        self.git('add', '.'); self.git('commit', '-qm', 'Acceptance rows')
        self.controller.config['qa_acceptance_tasks'] = ['T1', 'T2']
        self.controller.initialize()

    def test_acceptance_sweep_runs_suites_on_one_runtime_and_closes_passing_rows(self):
        self.acceptance_rows()
        self.write_suite()
        self.controller.step()
        # One runtime for the sweep, one for the model turn on the row without a suite.
        self.assertEqual(self.runtimes, ['start', 'stop', 'start', 'stop'])
        text = (self.project / 'tasks.md').read_text(encoding='utf-8')
        self.assertIn('- [x] **T1 - Verify one** | done | Dependencies: None.\n  QA suite S1 passed', text)
        self.assertIn('- [x] **T2 - Verify two** | done | Dependencies: None.\n  QA browser acceptance passed', text)
        self.assertEqual(self.controller.state['snapshot'], self.fingerprint())
        self.assertEqual(self.roles, ['qa'])

    def test_failed_sweep_suite_is_not_rerun_by_the_fast_path_on_the_same_snapshot(self):
        self.acceptance_rows()
        qa, writer = self.write_suite()
        self.suite_writer = lambda args: writer(args, 'failed')
        self.controller.step()
        self.assertEqual(len([a for a in self.owned if '-File' in a]), 1)
        self.assertEqual(self.controller.state['qa_fast_path']['suite']['status'], 'already failed on this snapshot')
        self.assertEqual(self.roles, ['qa'])
        self.assertIn('- [x] **T1 - Verify one** | done', (self.project / 'tasks.md').read_text(encoding='utf-8'))

    def test_unfinished_acceptance_parks_the_row_and_moves_on(self):
        self.acceptance_rows()
        self.engine_status = {'qa': 'blocked'}
        self.controller.step()
        self.assertEqual(self.roles, ['qa'])
        self.assertIn('T1', self.controller.state['parked_tasks'])
        self.assertEqual(self.controller.state['stage'], 'schedule')
        self.engine_status = {}
        self.controller.step()
        self.assertEqual(self.roles, ['qa', 'qa'])
        text = (self.project / 'tasks.md').read_text(encoding='utf-8')
        self.assertIn('- [ ] **T1 - Verify one** | in_progress', text)
        self.assertIn('- [x] **T2 - Verify two** | done', text)

    def test_acceptance_parking_starts_short_and_doubles(self):
        self.acceptance_rows()
        self.controller.config['acceptance_park_minutes'] = 30
        before = time.time()
        self.controller.park_acceptance('T1', 'not finished')
        first = self.controller.state['parked_tasks']['T1']['retry_at'] - before
        self.controller.park_acceptance('T1', 'not finished')
        second = self.controller.state['parked_tasks']['T1']['retry_at'] - before
        self.assertAlmostEqual(first, 1800, delta=5)
        self.assertAlmostEqual(second, 3600, delta=5)
        self.controller.park_acceptance('T2', 'WAIT_LOCAL_RATE_LIMIT seconds=4000; resume later')
        self.assertGreaterEqual(self.controller.state['parked_tasks']['T2']['retry_at'] - before, 4030)

    def test_closed_rows_are_delivered_when_the_queue_is_empty(self):
        self.acceptance_rows()
        self.controller.step()
        self.controller.step()
        # Both rows closed in tasks.md; the empty queue sends the pending change through the gates.
        self.assertTrue(self.git('status', '--porcelain'))
        self.controller.step()
        self.assertIn(self.controller.state['stage'], {'qa', 'devops', 'ready_for_commit'})
        self.assertIn('code_reviewer', self.roles)

    def test_runtime_start_failure_parks_without_a_model_turn(self):
        self.acceptance_rows()
        with patch.object(team.Team, 'start_qa_runtime', side_effect=RuntimeError('web build failed')):
            self.controller.step()
        self.assertEqual(self.roles, [])
        self.assertIn('T1', self.controller.state['parked_tasks'])

    def test_suite_covering_the_assignment_replaces_the_agent_turn(self):
        self.run_chain()
        self.write_suite()
        self.write('apps/web/page.txt', 'ui changed\n')
        self.rerun_qa()
        self.assertEqual(self.roles, [])
        self.assertEqual(self.controller.state['stage'], 'devops')
        self.assertEqual(self.controller.state['qa_fast_path']['suite']['status'], 'ran')
        stored = team.load(self.project / self.controller.state['reports']['qa'])
        self.assertIn('Suite S1', stored['report']['evidence'][0])
        self.assertEqual(self.controller.state['last_qa_pass']['tier'], 2)

    def test_failing_suite_falls_back_to_the_agent_with_the_failed_scenarios(self):
        self.run_chain()
        qa, writer = self.write_suite()
        self.suite_writer = lambda args: writer(args, 'failed')
        self.write('apps/web/page.txt', 'ui changed\n')
        self.rerun_qa()
        self.assertEqual(self.roles, ['qa'])
        self.assertEqual(self.controller.state['qa_fast_path']['suite']['failed'], ['T54.a', 'T54.b'])

    def test_stale_result_from_an_earlier_run_is_never_trusted(self):
        self.run_chain()
        qa, writer = self.write_suite()
        writer(['-ExpectedSnapshot', 'old-snapshot'])
        self.suite_writer = lambda args: None  # the script writes nothing this time
        self.write('apps/web/page.txt', 'ui changed\n')
        self.rerun_qa()
        self.assertEqual(self.roles, ['qa'])
        self.assertFalse((qa / 'result-S1.json').exists())

    def test_suite_must_cover_the_assigned_task_and_recorded_scenarios(self):
        self.run_chain()
        self.write_suite(tasks=('T9',))
        self.write('apps/web/page.txt', 'ui changed\n')
        self.rerun_qa()
        self.assertEqual(self.roles, ['qa'])
        self.assertEqual(self.owned, [])
        self.controller.persist(qa_scenario_universe={'T1': ['T54.a', 'T54.zzz']})
        self.write_suite()
        self.write('apps/web/page.txt', 'ui changed again\n')
        self.rerun_qa()
        self.assertEqual(self.roles, ['qa'])
        self.assertEqual(self.owned, [])

    def test_suite_completes_a_pending_continuation_checklist(self):
        self.run_chain()
        self.write_suite()
        self.write('apps/web/page.txt', 'ui changed\n')
        fingerprint = self.fingerprint()
        scopes = team.snapshot(self.project)['scopes']
        self.controller.persist(qa_progress={'task': 'T1', 'snapshot': fingerprint, 'scopes': scopes, 'report': 'r.json',
                                             'completed': [{'id': 'T54.a', 'evidence': ['earlier']}], 'remaining': ['T54.b']})
        self.rerun_qa()
        self.assertEqual(self.roles, [])
        progress = self.controller.state['qa_progress']
        self.assertEqual(progress['remaining'], [])
        self.assertEqual([i['id'] for i in progress['completed']], ['T54.a', 'T54.b'])
        self.assertEqual(self.controller.state['stage'], 'devops')

    def test_finished_checklist_is_not_demanded_again_on_a_reused_pass(self):
        self.run_chain()
        scopes = team.snapshot(self.project)['scopes']
        self.controller.persist(qa_progress={'task': 'T1', 'snapshot': 'whatever', 'scopes': scopes, 'report': 'r.json',
                                             'completed': [{'id': 'A', 'evidence': ['x']}], 'remaining': []})
        self.rerun_qa()
        self.assertEqual(self.roles, [])
        self.assertEqual(self.controller.state['stage'], 'devops')

    def test_disabled_tiers_always_spend_a_model_turn(self):
        self.run_chain()
        self.controller.config['qa_tiers'] = {'enabled': False}
        self.rerun_qa()
        self.assertEqual(self.roles, ['qa'])

    def test_verification_only_task_is_never_reused(self):
        self.run_chain()
        self.controller.config['qa_acceptance_tasks'] = ['T1']
        self.rerun_qa()
        self.assertEqual(self.roles, ['qa'])
        self.assertIn('verification-only', self.controller.state['qa_fast_path']['reason'])

    def test_migration_upgrades_matching_digests_and_leaves_stale_ones(self):
        self.run_chain()
        current = team.snapshot(self.project)
        legacy, fresh = current['legacy_scopes'], current['scopes']
        self.assertNotEqual(legacy['environment'], fresh['environment'])
        stale = {**legacy, 'environment': 'f' * 64}
        self.controller.persist(scope_algorithm=None, last_completed_scope=dict(legacy),
                                scope_fingerprints=stale, receipts={'qa': {'scopes': dict(legacy)}})
        self.controller.state.pop('scope_algorithm', None)
        self.controller.migrate_scope_algorithm()
        self.assertEqual(self.controller.state['scope_algorithm'], 2)
        self.assertEqual(self.controller.state['last_completed_scope']['environment'], fresh['environment'])
        self.assertEqual(self.controller.state['receipts']['qa']['scopes']['environment'], fresh['environment'])
        self.assertEqual(self.controller.state['scope_fingerprints']['environment'], 'f' * 64)
        before = dict(self.controller.state['receipts'])
        self.controller.migrate_scope_algorithm()
        self.assertEqual(self.controller.state['receipts'], before)


if __name__ == '__main__':
    unittest.main()
