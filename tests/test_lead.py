"""Technical-lead escalation and local authority contracts without external calls."""
import copy
import unittest

import test_team as fixtures

team = fixtures.team
report = fixtures.report


class LeadTests(unittest.TestCase):
    setUp = fixtures.TeamTests.setUp
    write = fixtures.TeamTests.write
    git = fixtures.TeamTests.git
    run_role = fixtures.TeamTests.run_role

    def blocked_environment(self):
        self.write('app.txt', 'reviewed candidate\n')
        self.controller.initialize(adopt=True)
        self.controller.execute('code_reviewer')
        receipt = copy.deepcopy(self.controller.state['receipts']['code_reviewer'])
        blocked = report('blocked')
        blocked['capability_requests'] = ['browser']
        self.responses['qa'] = blocked
        self.controller.execute('qa')
        self.responses['environment_engineer'] = report('blocked')
        self.controller.step()
        return receipt

    def plan(self, **changes):
        value = {'snapshot': self.controller.state['snapshot'],
                 'capabilities': ['local_runtime', 'browser'],
                 'strategy': 'Restore the local runtime before isolated browser contexts',
                 'evidence': ['The browser attempt found no local application listener']}
        value.update(changes)
        team.save(self.controller.folder / 'recovery-plan.json', value)

    def manifest(self):
        capability = self.controller.state['recovery']['capability']
        value = {'status': 'ready', 'capability': capability,
                 'snapshot': self.controller.state['snapshot'],
                 'evidence': ['Fixture runtime probe passed'], 'qa_bootstrap': 'fixture-bootstrap'}
        if capability == 'browser':
            value.update(local_origin='http://127.0.0.1:3210', isolation_probe={
                'contexts': 2, 'storage_isolated': True, 'page_loaded': True})
        else:
            value['readiness_probe'] = {'passed': True, 'command': 'fixture readiness'}
        team.save(self.controller.folder / 'environment' / 'manifest.json', value)

    def test_failed_environment_dispatches_strategy_before_unrelated_work(self):
        receipt = self.blocked_environment()
        self.assertEqual(self.controller.state['stage'], 'technical_lead')
        self.assertEqual(self.controller.state['receipts']['code_reviewer'], receipt)
        self.assertNotIn('planner', self.roles)
        self.assertNotIn('qa', self.controller.state['receipts'])

    def test_ordered_plan_restores_dependencies_then_returns_to_original_qa(self):
        receipt = self.blocked_environment()
        self.effects['technical_lead'] = self.plan
        self.responses['technical_lead'] = report('completed')
        self.controller.step()
        self.assertEqual(self.roles[-1], 'technical_lead')
        self.assertEqual(self.controller.state['stage'], 'environment_engineer')
        self.assertEqual(self.controller.state['recovery']['capability'], 'local_runtime')
        self.effects['environment_engineer'] = self.manifest
        self.responses['environment_engineer'] = report('completed')
        self.controller.step()
        self.assertEqual(self.controller.state['stage'], 'environment_engineer')
        self.assertEqual(self.controller.state['recovery']['capability'], 'browser')
        self.controller.step()
        self.assertEqual(self.controller.state['stage'], 'qa')
        self.assertEqual(self.controller.state['receipts']['code_reviewer'], receipt)
        self.assertNotIn('qa', self.controller.state['receipts'])
        self.responses['qa'] = report('passed')
        self.controller.step()
        self.assertEqual(self.controller.state['stage'], 'devops')

    def test_invalid_environment_proof_dispatches_lead(self):
        self.blocked_environment()
        self.controller.persist(stage='environment_engineer')
        self.responses['environment_engineer'] = report('completed')
        self.controller.step()
        self.assertEqual(self.controller.state['stage'], 'technical_lead')
        self.assertNotIn('qa', self.controller.state['receipts'])

    def test_invalid_or_stale_plan_never_resumes_qa(self):
        cases = [{'snapshot': 'stale'}, {'capabilities': []},
                 {'capabilities': ['production_credentials']},
                 {'capabilities': ['browser', 'browser']},
                 {'strategy': ''}, {'evidence': []}]
        for changes in cases:
            with self.subTest(changes=changes):
                case = LeadTests()
                case.setUp()
                try:
                    case.blocked_environment()
                    case.effects['technical_lead'] = lambda c=case, x=changes: c.plan(**x)
                    case.responses['technical_lead'] = report('completed')
                    case.controller.step()
                    self.assertEqual(case.controller.state['stage'], 'needs_attention')
                    self.assertNotIn('qa', case.controller.state['receipts'])
                finally:
                    case.doCleanups()

    def test_lead_cannot_change_application_source(self):
        self.blocked_environment()
        self.effects['technical_lead'] = lambda: self.write('app.txt', 'forbidden repair\n')
        with self.assertRaisesRegex(RuntimeError, 'changed source'):
            self.controller.execute('technical_lead')

    def test_strategy_budget_is_snapshot_bound_and_preserves_owner_stop(self):
        self.blocked_environment()
        fingerprint = self.controller.state['snapshot']
        for _ in range(self.controller.config.get('strategy_max_attempts', 2)):
            self.controller.request_strategy(fingerprint, 'fixture-report.json', 'Repeated fixture failure')
        self.assertEqual(self.controller.state['stage'], 'needs_attention')
        self.controller.stop.write_text('Owner STOP', encoding='utf-8')
        with self.assertRaises(InterruptedError):
            self.controller.execute('technical_lead')
        self.assertTrue(self.controller.stop.exists())
        self.assertNotIn('technical_lead', self.roles)
        self.write('app.txt', 'new candidate\n')
        new_fingerprint = team.snapshot(self.project)['fingerprint']
        self.controller.request_strategy(new_fingerprint, 'new-report.json', 'New candidate')
        self.assertEqual(self.controller.state['stage'], 'technical_lead')
        self.assertTrue(self.controller.stop.exists())

    def test_explicit_recovery_after_source_change_restores_review_before_qa(self):
        self.blocked_environment()
        self.controller.persist(stage='needs_attention', resume_role='environment_engineer')
        self.write('app.txt', 'new candidate after coordinator maintenance\n')
        self.controller.recover()
        self.assertEqual(self.controller.state['stage'], 'technical_lead')
        self.assertEqual(self.controller.state['recovery']['resume_role'], 'code_reviewer')
        self.assertEqual(self.controller.state['receipts'], {})
        self.assertFalse(self.controller.lock.exists())

    def test_recovery_does_not_override_policy_or_quota_failure(self):
        self.blocked_environment()
        for stage, kind in [('needs_attention', 'worker_failure'), ('waiting_for_quota', 'local_capability')]:
            with self.subTest(stage=stage):
                self.controller.persist(stage=stage, resume_role='environment_engineer', attention_kind=kind)
                with self.assertRaisesRegex(RuntimeError, 'cannot override'):
                    self.controller.recover()
                self.assertFalse(self.controller.lock.exists())

    def test_configured_local_authority_does_not_expand_read_only_roles(self):
        self.controller.config['execution_sandboxes'] = {role: 'danger-full-access' for role in ('planner', 'developer', 'qa', 'environment_engineer', 'technical_lead')}
        for role in ('planner', 'developer', 'qa', 'environment_engineer', 'technical_lead'):
            with self.subTest(role=role):
                self.assertEqual(self.controller.worker_sandbox(role), 'danger-full-access')
        for role in team.READ_ONLY:
            with self.subTest(role=role):
                self.assertEqual(self.controller.worker_sandbox(role), 'read-only')
        self.controller.config['execution_sandboxes']['developer'] = 'unsafe-typo'
        with self.assertRaises(ValueError):
            self.controller.worker_sandbox('developer')
        with self.assertRaises(ValueError):
            self.controller.worker_sandbox('unknown-role')


if __name__ == '__main__':
    unittest.main()
