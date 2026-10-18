"""Resilience contracts with fixtures only; no agents, GitHub or production calls."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from unittest.mock import MagicMock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import team
import resilience
import guardian


class ResilienceTests(unittest.TestCase):
    def test_guardian_observes_health_without_waiting_for_active_worker(self):
        import ctypes
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);folder=root/'.supervisor/team-v2';folder.mkdir(parents=True)
            fake=SimpleNamespace(state={'stage':'qa'},config={'operations_interval_seconds':1},view=lambda:{'controller_alive':True})
            ticks=[]
            def tick(_):
                ticks.append(1)
                if len(ticks)==2:(folder/'STOP').write_text('Owner STOP',encoding='utf-8')
            kernel=MagicMock();kernel.CreateMutexW.return_value=1
            with patch.object(team,'PROJECT',root),patch.object(team,'Team',return_value=fake),patch.object(ctypes,'WinDLL',return_value=kernel,create=True),patch.object(ctypes,'get_last_error',return_value=0,create=True),patch.object(guardian,'health',return_value={'status':'ready','release':'fixture'}) as observe,patch.object(guardian.time,'sleep',side_effect=tick),patch.object(guardian.subprocess,'Popen') as spawn:
                guardian.run()
            observe.assert_called();spawn.assert_not_called()
            self.assertEqual(team.load(folder/'health.json')['release'],'fixture')
            self.assertEqual((folder/'STOP').read_text(encoding='utf-8'),'Owner STOP')
            self.assertIsNone(team.load(folder/'guardian.json')['pid'])

    def test_team_and_docs_changes_preserve_runtime_scopes(self):
        a={'apps/web/app.ts':'a','agent-team/team.py':'b','scripts/start.ps1':'c','docs/progress.md':'d'}
        b={**a,'agent-team/team.py':'changed','docs/progress.md':'changed'}
        first=resilience.scopes(a);second=resilience.scopes(b)
        self.assertEqual(first['application'],second['application'])
        self.assertEqual(first['environment'],second['environment'])
        self.assertNotEqual(first['team'],second['team'])

    def test_app_and_environment_changes_invalidate_their_scopes(self):
        first=resilience.scopes({'apps/api/auth.ts':'a','.github/workflows/ci.yml':'b'})
        second=resilience.scopes({'apps/api/auth.ts':'changed','.github/workflows/ci.yml':'changed'})
        self.assertNotEqual(first['application'],second['application'])
        self.assertNotEqual(first['environment'],second['environment'])

    def test_checkpoint_requires_matching_scope_and_unchanged_artifacts(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);artifact=root/'build.json';artifact.write_text('verified build',encoding='utf-8')
            scope={'application':'a','environment':'b'}
            record=resilience.checkpoint(root,'build',scope,[artifact],['Build passed'],team.save)
            self.assertTrue(resilience.reusable(root,record,scope))
            self.assertFalse(resilience.reusable(root,record,{'application':'new'}))
            artifact.write_text('modified',encoding='utf-8')
            self.assertFalse(resilience.reusable(root,record,scope))

    def test_checkpoint_rejects_outside_paths_and_missing_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);outside=root/'outside';outside.write_text('x',encoding='utf-8')
            with self.assertRaises(ValueError):resilience.checkpoint(root/'runtime','build',{},[outside],['x'],team.save)
            with self.assertRaises(ValueError):resilience.checkpoint(root,'build',{},[outside],[],team.save)
            self.assertFalse(resilience.reusable(root,{'scope':{},'artifacts':{'../outside':'x'},'evidence':['x']},{}))

    def test_monitoring_edit_discards_report_and_schedules_review(self):
        from test_team import TeamTests
        f=TeamTests();f.setUp()
        try:
            f.adopted()
            f.effects['qa']=lambda:f.write('Team.cmd','owner monitoring edit')
            f.controller.execute('qa')
            self.assertEqual(f.controller.state['stage'],'code_reviewer')
            self.assertNotIn('qa',f.controller.state['receipts'])
            self.assertNotIn('qa',f.controller.state.get('reports',{}))
        finally:f.doCleanups()

    def test_qa_bootstrap_retry_stays_in_same_role_then_has_bounded_fallback(self):
        from test_team import TeamTests
        f=TeamTests();f.setUp()
        try:
            f.adopted();c=f.controller;c.config['qa_owns_environment']=True
            c.request_recovery('local_runtime','qa',c.state['snapshot'],'fixture')
            self.assertEqual(c.state['stage'],'qa')
            self.assertNotIn('qa',c.state['receipts'])
            c.request_recovery('local_runtime','qa',c.state['snapshot'],'fixture')
            self.assertEqual(c.state['stage'],'environment_engineer')
        finally:f.doCleanups()

    def test_delivery_budget_survives_controller_recreation(self):
        from test_team import TeamTests
        f=TeamTests();f.setUp()
        try:
            f.adopted();c=f.controller;c.config['max_calls_per_delivery']=1
            c.execute('code_reviewer')
            second=team.Team(f.project,f.home,runner=f.run_role)
            second.config['max_calls_per_delivery']=1
            second.execute('qa')
            self.assertEqual(second.state['attention_kind'],'delivery_budget')
            self.assertEqual(f.roles,['code_reviewer'])
        finally:f.doCleanups()

    def test_windowless_controller_is_a_competing_writer(self):
        inventory=[{'ProcessId':987654,'Name':'pythonw.exe','CommandLine':'pythonw.exe C:/project/agent-team/team.py start --resume'}]
        self.assertEqual(len(team.competing_processes(Path('C:/project'),inventory)),1)

    def test_failures_have_distinct_recovery_categories(self):
        for text,kind in [('QUOTA_LIMIT','quota'),('permission denied','policy'),('Role deadline exceeded','timeout'),('Git timed out after -330 seconds','timeout'),('CLI failed','transport'),('cleanup failed','cleanup'),('build failed','build'),('Invalid report','validation')]:
            self.assertEqual(resilience.failure_kind(text),kind)

    def test_only_qa_can_reuse_unchanged_runtime_scope(self):
        current={'fingerprint':'new','scopes':{'application':'a','environment':'b','team':'new'}}
        receipt={'snapshot':'old','scopes':{'application':'a','environment':'b','team':'old'},'report':{'status':'passed'}}
        self.assertTrue(team.gate_valid(receipt,'qa',current))
        self.assertFalse(team.gate_valid(receipt,'code_reviewer',current))
        self.assertFalse(team.gate_valid(receipt,'devops',current))
        current['scopes']['application']='changed'
        self.assertFalse(team.gate_valid(receipt,'qa',current))
        self.assertFalse(team.gate_valid({'snapshot':'old','report':{'status':'passed'}},'qa',current))

    def test_release_delegates_to_existing_exact_snapshot_gate(self):
        calls=[]
        c=SimpleNamespace(state={'stage':'ready_for_commit','snapshot':'exact','task':'T56'},config={'auto_commit':True},commit=lambda *a:calls.append(a))
        self.assertEqual(guardian.release_action(c),'committed')
        self.assertEqual(calls,[('exact','Deliver T56')])

    def test_release_does_not_run_before_gates_or_when_disabled(self):
        c=SimpleNamespace(state={'stage':'qa'},config={'auto_commit':True},commit=lambda *a:self.fail('Premature commit'))
        self.assertIsNone(guardian.release_action(c))
        c.state={'stage':'ready_for_commit'};c.config={}
        self.assertIsNone(guardian.release_action(c))

    def test_push_requires_both_authorized_flags(self):
        calls=[]
        c=SimpleNamespace(state={'stage':'release_ready','commit':'exact'},config={'allow_push':True},publish=lambda x:calls.append(x))
        self.assertIsNone(guardian.release_action(c))
        c.config['allow_deploy']=True
        self.assertEqual(guardian.release_action(c),'pushed');self.assertEqual(calls,['exact'])

    def test_workflow_success_requires_both_exact_sha_runs(self):
        rows=[{'workflowName':name,'headSha':'sha','status':'completed','conclusion':'success'} for name in ('Local application checks','Oracle deployment')]
        with patch.object(guardian.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=json.dumps(rows))):
            self.assertEqual(guardian.workflows('sha')[0],'passed')
            self.assertEqual(guardian.workflows('other')[0],'pending')
        rows[1]['conclusion']='failure'
        with patch.object(guardian.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=json.dumps(rows))):
            self.assertEqual(guardian.workflows('sha')[0],'failed')

    def test_team_only_change_reuses_qa_but_rechecks_review_and_release(self):
        from test_team import TeamTests
        fixture=TeamTests();fixture.setUp()
        try:
            fixture.approvals()
            fixture.write('agent-team/dashboard.py','monitoring update')
            for _ in range(3):fixture.controller.step()
            self.assertEqual(fixture.roles.count('qa'),1)
            self.assertEqual(fixture.roles.count('code_reviewer'),2)
            self.assertEqual(fixture.roles.count('devops'),2)
            self.assertEqual(fixture.controller.state['stage'],'ready_for_commit')
            fixture.controller.commit(fixture.controller.state['snapshot'],'Reviewed fixture monitoring update')
            self.assertEqual(fixture.controller.state['stage'],'release_ready')
        finally:fixture.doCleanups()


if __name__=='__main__':unittest.main()
