"""Capability recovery contracts using isolated Git fixtures and fake workers."""
import copy
import unittest

import test_team as fixtures

report = fixtures.report
team = fixtures.team


class RecoveryTests(unittest.TestCase):
    setUp = fixtures.TeamTests.setUp
    write = fixtures.TeamTests.write
    git = fixtures.TeamTests.git
    run_role = fixtures.TeamTests.run_role

    def blocked_qa(self):
        self.write('app.txt', 'reviewed candidate\n')
        self.controller.initialize(adopt=True)
        self.controller.execute('code_reviewer')
        receipt = copy.deepcopy(self.controller.state['receipts']['code_reviewer'])
        blocked = report('blocked')
        blocked['capability_requests'] = ['browser']
        blocked['limitations'] = ['Required isolated browser sessions are unavailable']
        self.responses['qa'] = blocked
        self.controller.execute('qa')
        return receipt

    def manifest(self, **changes):
        value = {
            'status': 'ready', 'capability': 'browser',
            'snapshot': self.controller.state['snapshot'],
            'evidence': ['Two isolated fixture contexts loaded the local page'],
            'qa_bootstrap': 'fixture-bootstrap',
            'isolation_probe': {'contexts': 2, 'storage_isolated': True, 'page_loaded': True},
            'local_origin': 'http://127.0.0.1:3210',
        }
        value.update(changes)
        team.save(self.controller.folder / 'environment' / 'manifest.json', value)

    def test_typed_browser_block_schedules_environment_before_independent_work(self):
        self.write('tasks.md', '- [ ] **T1 Work** | in_progress | Dependencies: None.\n'
                   '- [ ] **T2 Independent** | todo | Dependencies: None.\n')
        receipt = self.blocked_qa()
        self.assertEqual(self.controller.state['stage'], 'environment_engineer')
        recovery = self.controller.state['recovery']
        self.assertEqual(recovery['capability'], 'browser')
        self.assertEqual(recovery['resume_role'], 'qa')
        self.assertEqual(recovery['snapshot'], receipt['snapshot'])
        self.assertTrue(recovery['report'])
        self.assertNotIn('planner', self.roles)

    def test_verified_environment_resumes_qa_without_forging_qa_receipt(self):
        receipt = self.blocked_qa()
        self.effects['environment_engineer'] = self.manifest
        self.responses['environment_engineer'] = report('completed')
        self.controller.step()
        self.assertEqual(self.roles[-1], 'environment_engineer')
        self.assertEqual(self.controller.state['stage'], 'qa')
        self.assertEqual(self.controller.state['receipts']['code_reviewer'], receipt)
        self.assertNotIn('qa', self.controller.state['receipts'])
        self.responses['qa'] = report('passed')
        self.controller.step()
        self.assertEqual(self.roles[-1], 'qa')
        self.assertEqual(self.controller.state['stage'], 'devops')

    def test_environment_pass_without_manifest_requires_attention(self):
        self.blocked_qa()
        self.responses['environment_engineer'] = report('passed')
        self.controller.step()
        self.assertEqual(self.controller.state['stage'], 'technical_lead')
        self.assertNotIn('qa', self.controller.state['receipts'])

    def test_invalid_manifest_never_counts_as_recovery(self):
        invalid = [
            {'status': 'pending'}, {'capability': 'build_tools'},
            {'snapshot': 'stale'}, {'evidence': []}, {'qa_bootstrap': ''},
            {'isolation_probe': {'contexts': 1, 'storage_isolated': True, 'page_loaded': True}},
            {'isolation_probe': {'contexts': 2, 'storage_isolated': False, 'page_loaded': True}},
            {'isolation_probe': {'contexts': 2, 'storage_isolated': True, 'page_loaded': False}},
            {'local_origin': 'https://sohbetavlusu.com'},
            {'local_origin': 'http://127.0.0.1.evil.example'},
            {'local_origin': 'file:///tmp/page.html'},
        ]
        for changes in invalid:
            with self.subTest(changes=changes):
                # Each invalid proof gets an independent controller fixture.
                case = RecoveryTests()
                case.setUp()
                try:
                    case.blocked_qa()
                    case.responses['environment_engineer'] = report('completed')
                    case.effects['environment_engineer'] = lambda: case.manifest(**changes)
                    case.controller.step()
                    self.assertEqual(case.controller.state['stage'], 'technical_lead')
                    self.assertNotIn('qa', case.controller.state['receipts'])
                finally:
                    case.doCleanups()

    def test_environment_block_does_not_escape_through_planner(self):
        self.write('tasks.md', '- [ ] **T1 Work** | in_progress | Dependencies: None.\n'
                   '- [ ] **T2 Independent** | todo | Dependencies: None.\n')
        self.blocked_qa()
        self.responses['environment_engineer'] = report('blocked')
        self.controller.step()
        self.assertEqual(self.controller.state['stage'], 'technical_lead')
        self.assertNotIn('planner', self.roles)

    def test_repeated_requests_have_two_attempt_budget_per_snapshot(self):
        self.blocked_qa()
        self.effects['environment_engineer'] = self.manifest
        self.responses['environment_engineer'] = report('completed')
        for _ in range(2):
            self.controller.step()
            self.assertEqual(self.controller.state['stage'], 'qa')
            self.controller.step()
        self.assertEqual(self.roles.count('environment_engineer'), 2)
        self.assertEqual(self.controller.state['stage'], 'technical_lead')
        self.assertTrue(self.controller.state['recovery_attempts'])

    def test_owner_stop_prevents_environment_worker(self):
        self.blocked_qa()
        self.controller.stop.write_text('Owner STOP', encoding='utf-8')
        with self.assertRaises(InterruptedError):
            self.controller.execute('environment_engineer')
        self.assertNotIn('environment_engineer', self.roles)

    def test_source_change_invalidates_recovery_and_old_approvals(self):
        old = self.blocked_qa()
        self.manifest()
        self.write('app.txt', 'unreviewed replacement\n')
        self.controller.step()
        self.assertEqual(self.roles[-1], 'code_reviewer')
        self.assertNotEqual(self.controller.state['snapshot'], old['snapshot'])
        self.assertEqual(set(self.controller.state['receipts']), {'code_reviewer'})
        self.assertNotIn('environment_engineer', self.roles)

    def test_environment_cannot_change_application_source(self):
        self.blocked_qa()
        self.effects['environment_engineer'] = lambda: self.write('app.txt', 'forbidden repair\n')
        with self.assertRaisesRegex(RuntimeError, 'changed source'):
            self.controller.execute('environment_engineer')

    def test_capability_report_schema_requires_known_typed_requests(self):
        valid = report('blocked')
        valid['capability_requests'] = ['browser', 'local_runtime', 'build_tools']
        self.assertEqual(team.validate_report(valid, 'qa'), valid)
        for invalid in (None, 'browser', ['production_credentials'], [1]):
            with self.subTest(requests=invalid):
                with self.assertRaises(ValueError):
                    team.validate_report({**valid, 'capability_requests': invalid}, 'qa')
        del valid['capability_requests']
        with self.assertRaises(ValueError):
            team.validate_report(valid, 'qa')

    def test_nonbrowser_recovery_uses_recorded_readiness_probe(self):
        self.blocked_qa()
        self.controller.persist(stage='qa', recovery=None)
        blocked = report('blocked')
        blocked['capability_requests'] = ['local_runtime']
        self.responses['qa'] = blocked
        self.controller.execute('qa')
        self.assertEqual(self.controller.state['recovery']['capability'], 'local_runtime')
        def proof():
            team.save(self.controller.folder / 'environment' / 'manifest.json', {
                'status': 'ready', 'capability': 'local_runtime',
                'snapshot': self.controller.state['snapshot'],
                'evidence': ['Fixture local readiness command passed'],
                'qa_bootstrap': 'fixture-bootstrap',
                'readiness_probe': {'passed': True, 'command': 'fixture readiness'},
            })
        self.effects['environment_engineer'] = proof
        self.responses['environment_engineer'] = report('completed')
        self.controller.step()
        self.assertEqual(self.controller.state['stage'], 'qa')
        self.assertNotIn('qa', self.controller.state['receipts'])


if __name__ == '__main__':
    unittest.main()
