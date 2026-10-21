"""Resilience contracts with fixtures only; no agents, GitHub or production calls."""
import json
import os
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
            second.config['max_calls_per_delivery']=1;second.config['park_exhausted_tasks']=False
            second.execute('qa')
            self.assertEqual(second.state['attention_kind'],'delivery_budget')
            self.assertEqual(f.roles,['code_reviewer'])
        finally:f.doCleanups()

    def test_release_recovery_saves_failed_job_logs_for_diagnosis(self):
        from test_team import TeamTests
        f=TeamTests();f.setUp()
        try:
            f.adopted();c=f.controller
            c.persist(published_commit='a'*40)
            team.save(c.folder/'release-observation.json',{'commit':'a'*40,'ci':'failed','workflows':[
                {'workflowName':'Local application checks','conclusion':'success','url':'https://github.com/x/y/actions/runs/1'},
                {'workflowName':'Oracle deployment','conclusion':'failure','url':'https://github.com/x/y/actions/runs/42'}]})
            log='deploy\tmigrate\tERROR relation missing ghp_'+'x'*30+'\n'
            with patch.object(team,'failed_run_log',return_value=log) as run:
                c.begin_release_recovery('a'*40,'Deployment failed')
            run.assert_called_once_with('42')
            done=SimpleNamespace(returncode=0,stdout='ok',stderr='')
            with patch.object(team,'background_run',return_value=done) as gh:
                self.assertEqual(team.failed_run_log('42'),'ok')
            self.assertEqual(gh.call_args[0][0][:4],['gh','run','view','42'])
            self.assertIn('--log-failed',gh.call_args[0][0])
            logs=c.state['release_recovery']['failure_logs']
            self.assertEqual(len(logs),1)
            text=Path(logs[0]).read_text(encoding='utf-8')
            self.assertIn('relation missing',text);self.assertNotIn('ghp_',text)
            self.assertEqual(c.state['stage'],'devops')
        finally:f.doCleanups()

    def test_release_recovery_uses_separate_budget_without_resetting_delivery(self):
        from test_team import TeamTests
        f=TeamTests();f.setUp()
        try:
            f.adopted();c=f.controller
            mission=c.config['delivery_epoch']+':'+str(c.state['task'])
            c.persist(delivery_calls={mission:8},published_commit='a'*40)
            c.begin_release_recovery('a'*40,'Deployment failed')
            c.execute('devops')
            self.assertEqual(f.roles,['devops'])
            self.assertEqual(c.state['delivery_calls'][mission],8)
            self.assertEqual(c.state['release_recovery_calls']['release:'+'a'*40],1)
        finally:f.doCleanups()

    def test_release_recovery_budget_survives_new_candidates_and_restart(self):
        from test_team import TeamTests
        f=TeamTests();f.setUp()
        try:
            f.adopted();c=f.controller;c.persist(published_commit='a'*40)
            c.begin_release_recovery('a'*40,'Failure one')
            c.persist(release_recovery_calls={'release:'+'a'*40:10},published_commit='b'*40)
            second=team.Team(f.project,f.home,runner=f.run_role)
            second.begin_release_recovery('b'*40,'Failure two')
            second.config['max_calls_per_release_recovery']=10
            second.execute('devops')
            self.assertEqual(second.state['release_recovery']['incident'],'a'*40)
            self.assertEqual(second.state['attention_kind'],'release_recovery_budget')
            self.assertEqual(f.roles,[])
            with self.assertRaises(ValueError):second.begin_release_recovery('c'*40,'Unrecorded commit')
        finally:f.doCleanups()

    def test_increased_release_budget_keeps_ledger_and_enforces_new_cap(self):
        from test_team import TeamTests
        f=TeamTests();f.setUp()
        try:
            f.adopted();c=f.controller;c.persist(published_commit='a'*40)
            c.begin_release_recovery('a'*40,'Existing incident')
            key='release:'+'a'*40
            c.persist(release_recovery_calls={key:10})
            second=team.Team(f.project,f.home,runner=f.run_role)
            self.assertEqual(second.config['max_calls_per_release_recovery'],40)
            second.execute('devops')
            self.assertEqual(second.state['release_recovery_calls'][key],11)
            self.assertEqual(f.roles,['devops'])
            second.persist(release_recovery_calls={key:40})
            third=team.Team(f.project,f.home,runner=f.run_role)
            third.execute('code_reviewer')
            self.assertEqual(third.state['attention_kind'],'release_recovery_budget')
            self.assertEqual(third.state['release_recovery_calls'][key],40)
            self.assertEqual(f.roles,['devops'])
            self.assertEqual(third.config['max_fix_attempts'],2)
        finally:f.doCleanups()

    def test_windowless_controller_is_a_competing_writer(self):
        inventory=[{'ProcessId':987654,'Name':'pythonw.exe','CommandLine':'pythonw.exe C:/project/agent-team/team.py start --resume'}]
        self.assertEqual(len(team.competing_processes(Path('C:/project'),inventory)),1)

    def test_controller_from_team_home_is_a_competing_writer(self):
        inventory=[{'ProcessId':987654,'Name':'pythonw.exe','CommandLine':'pythonw.exe '+str(team.HOME/'team.py')+' start --resume'}]
        self.assertEqual(len(team.competing_processes(Path('C:/project'),inventory)),1)

    def test_project_root_comes_from_team_json(self):
        with tempfile.TemporaryDirectory() as root:
            home=Path(root)/'Team';home.mkdir()
            (home/'team.json').write_text('{"project": "../Product"}',encoding='utf-8')
            with patch.dict(os.environ,{},clear=False):
                os.environ.pop('AGENT_TEAM_PROJECT',None)
                self.assertEqual(team.project_root(home),(Path(root)/'Product').resolve())
                os.environ['AGENT_TEAM_PROJECT']=str(Path(root)/'Other')
                self.assertEqual(team.project_root(home),(Path(root)/'Other').resolve())

    def test_failures_have_distinct_recovery_categories(self):
        for text,kind in [('QUOTA_LIMIT','quota'),('permission denied','policy'),('Role deadline exceeded','timeout'),('Git timed out after -330 seconds','timeout'),('CLI failed','transport'),('cleanup failed','cleanup'),('build failed','build'),('Invalid report','validation')]:
            self.assertEqual(resilience.failure_kind(text),kind)

    def test_local_rate_limit_text_is_not_account_quota(self):
        for text in ('Local entry returned HTTP 429','rate limit from localhost','CLI failed: HTTP 429'):
            self.assertNotEqual(resilience.failure_kind(text),'quota')
            self.assertIsNone(team.QUOTA.search(text))
        self.assertEqual(resilience.failure_kind('Account usage limit reached'),'quota')
        self.assertIsNotNone(team.QUOTA.search('You have hit your usage limit'))

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

    def test_disabled_push_continues_delivery_after_local_commit_only_when_configured(self):
        calls=[]
        c=SimpleNamespace(state={'stage':'release_ready','commit':'exact'},config={'allow_push':False},
                          publish=lambda x:self.fail('Push while disabled'),complete_release=lambda **k:calls.append(k))
        self.assertIsNone(guardian.release_action(c))
        c.config['continue_after_local_commit']=True
        self.assertEqual(guardian.release_action(c),'continued');self.assertEqual(calls,[{'local':True}])

    def test_publish_cadence_holds_commits_until_due_then_pushes(self):
        calls=[]
        c=SimpleNamespace(state={'stage':'release_ready','commit':'exact'},config={'allow_push':True,'allow_deploy':True},
                          publish=lambda x:calls.append(('push',x)),complete_release=lambda **k:calls.append(('held',k)),
                          publish_due=lambda:False,held_release=lambda:'exact')
        self.assertEqual(guardian.release_action(c),'continued');self.assertEqual(calls,[('held',{'local':True})])
        c.state={'stage':'idle'};calls.clear()
        self.assertIsNone(guardian.release_action(c));self.assertEqual(calls,[])
        c.publish_due=lambda:True
        self.assertEqual(guardian.release_action(c),'pushed held commits');self.assertEqual(calls,[('push','exact')])
        c.state={'stage':'release_ready','commit':'next'};calls.clear()
        self.assertEqual(guardian.release_action(c),'pushed');self.assertEqual(calls,[('push','next')])

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
