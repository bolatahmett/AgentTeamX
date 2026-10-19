"""Codex-primary / Claude-failover engine routing. Mocked workers only; no paid calls."""
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
import unittest.mock
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import team


def report(status='passed'):
    return {'status': status, 'summary': 'Deterministic test evidence', 'evidence': ['Verified fixture'],
            'findings': [], 'limitations': [], 'capability_requests': [], 'next_action': 'Continue'}


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        self.home = self.project / 'agent-team'
        self.home.mkdir()
        source = Path(team.__file__).parent
        config = json.loads((source / 'team.json').read_text(encoding='utf-8-sig'))
        self.owner_role_engines = config.get('role_engines', {})
        # Routing tests below assume the Codex-primary default; the owner's split is checked separately.
        config.update(auto_commit=False, qa_owns_environment=False, qa_tiers={'enabled': False}, autonomous_intervention=False, role_engines={})
        team.save(self.home / 'team.json', config)
        (self.home / 'report.schema.json').write_text((source / 'report.schema.json').read_text(encoding='utf-8'), encoding='utf-8')
        (self.project / '.gitignore').write_text('.supervisor/\n', encoding='utf-8')
        for args in (('init', '-q'), ('config', 'user.name', 'Fixture'), ('config', 'user.email', 'f@example.invalid'),
                     ('config', 'commit.gpgsign', 'false'), ('add', '.'), ('commit', '-qm', 'Fixture baseline')):
            subprocess.run(['git', '-C', str(self.project), *args], check=True, capture_output=True)
        self.controller = team.Team(self.project, self.home, runner=lambda role: report())
        for role in ('qa', 'developer', 'code_reviewer'):
            d = self.home / 'agents' / role
            d.mkdir(parents=True)
            team.save(d / 'role.json', {'id': role, 'worker': True, 'sandbox': self.controller.worker_sandbox(role)})
            (d / 'prompt.md').write_text('Return evidence.', encoding='utf-8')
        which = patch.object(team.shutil, 'which', side_effect=lambda name: name)
        which.start()
        self.addCleanup(which.stop)

    # ---- routing ----
    def test_codex_is_primary_and_claude_is_failover(self):
        calls = []
        def fake(role, engine):
            calls.append(engine)
            if engine == 'codex':
                raise RuntimeError('QUOTA_LIMIT: wait for account reset and explicitly retry')
            return report()
        with patch.object(self.controller, 'run_worker_engine', side_effect=fake):
            self.assertEqual(self.controller.run_worker('developer')['status'], 'passed')
        self.assertEqual(calls, ['codex', 'claude'])
        self.assertIn('codex', self.controller.state['engines'])
        self.assertNotIn('claude', self.controller.state['engines'])

    def test_exhausted_codex_is_skipped_until_cooldown_and_probe_restore_it(self):
        self.controller.mark_engine('codex', True)
        calls = []
        def fake(role, engine):
            calls.append(engine)
            return report()
        with patch.object(self.controller, 'run_worker_engine', side_effect=fake), \
                patch.object(team, 'read_limits') as probe:
            self.controller.run_worker('qa')
            probe.assert_not_called()  # still inside the probe interval
            self.assertEqual(calls, ['claude'])
            # Interval elapsed and the account endpoint reports quota: return to Codex.
            self.controller.state['engines']['codex']['retry_after'] = time.time() - 1
            with patch.object(team, 'availability', return_value='available'):
                self.controller.run_worker('qa')
        self.assertEqual(calls, ['claude', 'codex'])
        self.assertNotIn('codex', self.controller.state['engines'])

    def test_probe_failure_keeps_codex_marked_and_claude_working(self):
        self.controller.mark_engine('codex', True)
        self.controller.state['engines']['codex']['retry_after'] = time.time() - 1
        with patch.object(self.controller, 'run_worker_engine', return_value=report()) as run, \
                patch.object(team, 'read_limits', side_effect=OSError('offline')):
            self.controller.run_worker('qa')
        self.assertEqual(run.call_args.args[1], 'claude')
        self.assertGreater(self.controller.state['engines']['codex']['retry_after'], time.time())

    def test_claude_quota_returns_work_to_codex_when_it_has_quota(self):
        self.controller.mark_engine('claude', True)
        self.controller.state['engines']['claude']['retry_after'] = time.time() - 1
        calls = []
        def fake(role, engine):
            calls.append(engine)
            if engine == 'claude':
                raise RuntimeError('QUOTA_LIMIT: wait')
            return report()
        # Codex preferred but marked; make Claude the only ready engine, then it exhausts.
        self.controller.mark_engine('codex', True)
        self.controller.state['engines']['codex']['retry_after'] = time.time() - 1
        with patch.object(self.controller, 'run_worker_engine', side_effect=fake), \
                patch.object(team, 'read_limits'), patch.object(team, 'availability', return_value='available'):
            self.controller.run_worker('developer')
        self.assertEqual(calls, ['codex'])

    def test_all_engines_exhausted_raises_quota_for_waiting_state(self):
        with patch.object(self.controller, 'run_worker_engine', side_effect=RuntimeError('QUOTA_LIMIT: x')):
            with self.assertRaisesRegex(RuntimeError, 'QUOTA_LIMIT'):
                self.controller.run_worker('developer')
        self.assertEqual(set(self.controller.state['engines']), {'codex', 'claude'})
        # No ready engine now: no worker call at all, still a quota wait.
        with patch.object(self.controller, 'run_worker_engine') as run:
            with self.assertRaisesRegex(RuntimeError, 'QUOTA_LIMIT'):
                self.controller.run_worker('developer')
            run.assert_not_called()
        self.assertEqual(team.failure_kind(RuntimeError('QUOTA_LIMIT: no engine')), 'quota')

    def test_non_quota_failures_do_not_switch_engines(self):
        with patch.object(self.controller, 'run_worker_engine', side_effect=RuntimeError('CLI failed; inspect log')) as run:
            with self.assertRaisesRegex(RuntimeError, 'CLI failed'):
                self.controller.run_worker('developer')
        self.assertEqual(run.call_count, 1)
        self.assertNotIn('engines', self.controller.state)

    def test_failover_disabled_is_codex_only(self):
        self.controller.config['engine_failover'] = False
        with patch.object(self.controller, 'run_worker_engine', side_effect=RuntimeError('QUOTA_LIMIT: x')) as run:
            with self.assertRaisesRegex(RuntimeError, 'QUOTA_LIMIT'):
                self.controller.run_worker('qa')
        run.assert_called_once_with('qa', 'codex')

    def test_missing_claude_binary_is_not_a_candidate(self):
        with patch.object(team.shutil, 'which', side_effect=lambda n: None if n == 'claude' else n):
            self.assertEqual(self.controller.engine_candidates('qa'), ['codex'])

    def test_role_engine_preference_and_validation(self):
        self.controller.config['role_engines'] = {'code_reviewer': 'claude'}
        self.assertEqual(self.controller.engine_candidates('code_reviewer'), ['claude', 'codex'])
        self.assertEqual(self.controller.engine_candidates('developer'), ['codex', 'claude'])
        self.controller.config['role_engines'] = {'qa': 'other'}
        with self.assertRaises(ValueError):
            self.controller.engine_candidates('qa')

    def test_owner_split_runs_build_and_review_roles_on_claude_and_rest_on_codex(self):
        self.assertEqual(self.owner_role_engines, {'developer': 'claude', 'technical_lead': 'claude', 'code_reviewer': 'claude'})
        self.controller.config['role_engines'] = self.owner_role_engines
        for role in team.ROLES:
            expected = ['claude', 'codex'] if role in self.owner_role_engines else ['codex', 'claude']
            self.assertEqual(self.controller.engine_candidates(role), expected, role)
        # A Claude-preferred role still falls back to Codex when Claude's plan is exhausted.
        calls = []
        def fake(role, engine):
            calls.append(engine)
            if engine == 'claude':
                raise RuntimeError('QUOTA_LIMIT: wait')
            return report()
        with patch.object(self.controller, 'run_worker_engine', side_effect=fake):
            self.assertEqual(self.controller.run_worker('developer')['status'], 'passed')
        self.assertEqual(calls, ['claude', 'codex'])
        self.assertIn('claude', self.controller.state['engines'])

    # ---- Claude command ----
    def test_claude_commands_follow_each_sandbox(self):
        full = self.controller.claude_args('claude', 'developer', 'danger-full-access')
        self.assertIn('--dangerously-skip-permissions', full)
        self.assertEqual(full[full.index('--model') + 1], 'claude-sonnet-5-5')
        self.assertEqual(full[full.index('--effort') + 1], 'medium')
        self.assertEqual(json.loads(full[full.index('--json-schema') + 1])['required'][0], 'status')
        self.assertEqual(full[full.index('--add-dir') + 1], str(self.project))
        self.assertIn('--strict-mcp-config', full)
        self.assertNotIn('--mcp-config', full)
        self.assertEqual(self.controller.claude_args('claude', 'technical_lead', 'danger-full-access')[
            self.controller.claude_args('claude', 'technical_lead', 'danger-full-access').index('--effort') + 1], 'high')
        read_only = self.controller.claude_args('claude', 'code_reviewer', 'read-only')
        self.assertNotIn('--dangerously-skip-permissions', read_only)
        self.assertEqual(read_only[read_only.index('--permission-mode') + 1], 'dontAsk')
        self.assertTrue(read_only[read_only.index('--disallowedTools') + 1].startswith('Edit,Write,NotebookEdit,'))
        self.assertNotIn('Bash,', read_only[read_only.index('--allowedTools') + 1])  # no blanket Bash
        scoped = self.controller.claude_args('claude', 'planner', 'workspace-write')
        self.assertEqual(scoped[scoped.index('--permission-mode') + 1], 'acceptEdits')
        with self.assertRaises(ValueError):
            self.controller.claude_args('claude', 'qa', 'bogus')

    def test_every_claude_sandbox_restricts_tools_and_denies_git_and_network(self):
        for sandbox, role in (('danger-full-access', 'developer'), ('workspace-write', 'planner'), ('read-only', 'code_reviewer')):
            args = self.controller.claude_args('claude', role, sandbox)
            tools = args[args.index('--tools') + 1].split(',')
            self.assertNotIn('WebFetch', tools)
            self.assertNotIn('PowerShell', tools)
            denied = args[args.index('--disallowedTools') + 1]
            for rule in ('Bash(git push *)', 'Bash(git commit *)', 'Bash(curl *)', 'Bash(gh *)', 'Bash(*--output*)'):
                self.assertIn(rule, denied, sandbox)
        scoped = self.controller.claude_args('claude', 'planner', 'workspace-write')
        self.assertEqual(scoped[scoped.index('--allowedTools') + 1], team.CLAUDE_TOOLS)

    def test_quota_patterns_ignore_ordinary_limits_and_paths(self):
        for text in ("You've hit your session limit · resets 2pm (Europe/Istanbul)", 'You have hit your limit',
                     'Claude AI usage limit reached|1792420800', '5-hour limit reached ∙ resets 3am',
                     "You're out of extra usage", 'Credit balance is too low'):
            self.assertIsNotNone(team.CLAUDE_QUOTA.search(text), text)
        for text in ('Output token limit reached', 'Reached maximum number of turns (40)', 'Context limit reached; compacting',
                     'API Error: 429 overloaded'):
            self.assertIsNone(team.CLAUDE_QUOTA.search(text), text)
        self.assertIsNotNone(team.QUOTA.search('Codex plan quota exhausted for this account'))
        self.assertIsNone(team.QUOTA.search('failed reading codex-supervisor-windows/supervisor.py and agent-team/quota.py'))

    def test_quota_is_read_from_error_fields_not_the_whole_event(self):
        event = {'type': 'turn.failed', 'error': {'message': 'build failed'},
                 'item': {'text': 'docs mention a usage limit reached banner'}}
        self.assertEqual(team.error_text(event), 'build failed')
        self.assertIsNone(team.QUOTA.search(team.error_text(event)))
        self.assertIn('usage limit', team.error_text({'type': 'error', 'message': 'You have hit your usage limit'}))
        with self.assertRaisesRegex(RuntimeError, 'CLI failed'):
            self.run_claude([{'type': 'assistant', 'message': {'content': 'usage limit reached text quoted from a file'}},
                             {'type': 'result', 'subtype': 'error_max_turns', 'is_error': True, 'result': 'Reached maximum number of turns'}], 1)

    def test_controller_exits_between_steps_when_machinery_changes(self):
        with patch.object(team, 'competing_processes', return_value=[]), \
                patch.object(self.controller, 'step') as step, \
                patch.object(self.controller, 'check_operations'), \
                patch.object(team, 'machinery_fingerprint', side_effect=['old', 'old', 'new']):
            self.controller.persist(stage='waiting_for_quota')
            self.controller.config['poll_seconds'] = 0
            self.controller.loop()
        self.assertEqual(step.call_count, 2)
        self.assertEqual(self.controller.state['controller_status'], 'stopped')
        self.assertFalse(self.controller.lock.exists())

    def test_unreadable_machinery_does_not_force_reload(self):
        with patch.object(Path, 'read_bytes', side_effect=PermissionError('locked')):
            (self.home / 'x.py').write_text('x', encoding='utf-8')
            self.assertIsNone(team.machinery_fingerprint(self.home))

    def test_invalid_claude_policy_fails(self):
        self.controller.config['claude_models'] = {'default': {'model': 'bad model!'}}
        with self.assertRaisesRegex(ValueError, 'Invalid Claude model policy'):
            self.controller.claude_policy('qa')
        self.controller.config['claude_models'] = {'default': {'model': 'claude-sonnet-5-5', 'reasoning_effort': 'turbo'}}
        with self.assertRaises(ValueError):
            self.controller.claude_policy('qa')

    # ---- stream parsing through the real run_worker_engine ----
    def fake_process(self, lines, returncode=0):
        fake = unittest.mock.MagicMock()
        fake.pid = 424242
        fake.stdout = io.StringIO(''.join(json.dumps(x) + '\n' for x in lines))
        fake.stdin = io.StringIO()
        fake.returncode = returncode
        fake.poll.return_value = returncode
        return fake

    def run_claude(self, lines, returncode=0):
        fake = self.fake_process(lines, returncode)
        captured = {}
        def spawn(args, **kwargs):
            captured['args'] = args
            return fake
        with patch.object(team.subprocess, 'Popen', side_effect=spawn), \
                patch.object(team, 'attach_worker_job', return_value=None):
            result = self.controller.run_worker_engine('qa', 'claude')
        return result, captured['args']

    def test_claude_structured_output_becomes_the_validated_report(self):
        result, args = self.run_claude([
            {'type': 'system', 'subtype': 'init'},
            {'type': 'result', 'subtype': 'success', 'is_error': False, 'result': 'done', 'structured_output': report()}])
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(args[0], 'claude')
        self.assertIsNone(self.controller.state['active_engine'])

    def test_claude_json_text_result_is_accepted_when_structured_output_absent(self):
        result, _ = self.run_claude([{'type': 'result', 'subtype': 'success', 'is_error': False, 'result': json.dumps(report('blocked'))}])
        self.assertEqual(result['status'], 'blocked')

    def test_claude_usage_limit_is_quota_but_generic_error_is_not(self):
        with self.assertRaisesRegex(RuntimeError, 'QUOTA_LIMIT'):
            self.run_claude([{'type': 'result', 'subtype': 'success', 'is_error': True, 'result': 'Claude usage limit reached. Resets 5pm'}], 1)
        with self.assertRaisesRegex(RuntimeError, 'CLI failed'):
            self.run_claude([{'type': 'result', 'subtype': 'error_during_execution', 'is_error': True, 'result': 'HTTP 429 overloaded'}], 1)
        with self.assertRaisesRegex(RuntimeError, 'CLI failed'):
            self.run_claude([{'type': 'system', 'subtype': 'api_retry', 'error': 'rate_limit'},
                             {'type': 'result', 'subtype': 'error_max_turns', 'is_error': True, 'result': 'max turns'}], 1)

    def test_claude_rate_limit_event_uses_limit_status_not_overage_status(self):
        allowed = {'type': 'rate_limit_event', 'rate_limit_info': {
            'status': 'allowed', 'rateLimitType': 'five_hour', 'overageStatus': 'rejected',
            'overageDisabledReason': 'org_level_disabled', 'isUsingOverage': False}}
        result, _ = self.run_claude([allowed, {'type': 'result', 'subtype': 'success', 'is_error': False, 'structured_output': report()}])
        self.assertEqual(result['status'], 'passed')
        rejected = {'type': 'rate_limit_event', 'rate_limit_info': {'status': 'rejected', 'rateLimitType': 'five_hour'}}
        with self.assertRaisesRegex(RuntimeError, 'QUOTA_LIMIT'):
            self.run_claude([rejected, {'type': 'result', 'subtype': 'error_during_execution', 'is_error': True, 'result': 'stopped'}], 1)

    def test_claude_result_without_report_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'no structured report'):
            self.run_claude([{'type': 'result', 'subtype': 'success', 'is_error': False, 'result': 'plain prose'}])

    # ---- guards ----
    def test_competing_process_detection_covers_claude_workers(self):
        project = str(self.project)
        row = {'ProcessId': 99999, 'Name': 'claude.exe',
               'CommandLine': 'claude.exe -p --output-format stream-json --add-dir ' + project}
        self.assertEqual(team.competing_processes(self.project, [row]), [row])
        idle = {'ProcessId': 99998, 'Name': 'claude.exe', 'CommandLine': 'claude.exe'}
        self.assertEqual(team.competing_processes(self.project, [idle]), [])

    def test_waiting_for_quota_resumes_when_claude_cooldown_elapsed(self):
        self.controller.persist(stage='waiting_for_quota', failure_kind='quota', resume_role='developer', snapshot='x')
        self.controller.mark_engine('codex', True)
        self.controller.mark_engine('claude', True)
        with patch.object(team, 'read_limits', return_value={}), patch.object(team, 'availability', return_value='exhausted'):
            self.controller.resume_quota()
            self.assertEqual(self.controller.state['stage'], 'waiting_for_quota')
            self.controller.state['engines']['claude']['retry_after'] = time.time() - 1
            self.controller.state['quota_next_check_at'] = 0
            self.controller.resume_quota()
        self.assertNotEqual(self.controller.state['stage'], 'waiting_for_quota')


if __name__ == '__main__':
    unittest.main()
