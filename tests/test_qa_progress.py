"""QA continuation and blocker routing contracts with synthetic workers only."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import team
import qa_progress
import test_team


def progress(task='T1',snapshot='current',done=('T1.entry',),remaining=('T1.expiry',)):
    return {'task':task,'snapshot':snapshot,
            'completed':[{'id':item,'evidence':['Observed synthetic browser scenario '+item]} for item in done],
            'remaining':list(remaining)}


class ProgressValidationTests(unittest.TestCase):
    def test_scoped_handoff_is_normalized_without_trusting_controller_metadata(self):
        scopes={'application':'a'*64,'environment':'b'*64,'team':'c'*64}
        value={**progress(),'scopes':scopes,'report':'previous-worker-report.json'}
        self.assertEqual(qa_progress.validate_progress(value,'T1','current',current_scopes=scopes),progress())
        self.assertEqual(value['report'],'previous-worker-report.json')
        for key in ('application','environment'):
            with self.subTest(scope=key),self.assertRaisesRegex(ValueError,'scope is stale'):
                qa_progress.validate_progress(value,'T1','current',current_scopes={**scopes,key:'d'*64})
        self.assertEqual(qa_progress.validate_progress(value,'T1','current',
                         current_scopes={**scopes,'team':'d'*64}),progress())

    def test_malformed_or_unknown_handoff_metadata_is_rejected(self):
        invalid=[{'scopes':None},{'scopes':{}},{'scopes':{'application':'old'}},
                 {'report':None},{'report':''},{'approved':True}]
        for metadata in invalid:
            with self.subTest(metadata=metadata),self.assertRaises(ValueError):
                qa_progress.validate_progress({**progress(),**metadata},'T1','current')

    def test_progress_cannot_drop_pending_or_completed_scenarios(self):
        previous=progress(remaining=('T1.expiry','T1.recovery'))
        invalid=[progress(done=('T1.entry','T1.expiry'),remaining=()),
                 progress(done=('T1.expiry',),remaining=('T1.recovery',)),
                 progress(done=('T1.entry','T1.new'),remaining=('T1.recovery',))]
        for value in invalid:
            with self.assertRaises(ValueError):qa_progress.validate_progress(value,'T1','current',previous)

    def test_stale_task_snapshot_duplicates_empty_evidence_and_repeated_work_rejected(self):
        invalid=[None,{},progress(task='T2'),progress(snapshot='old'),
                 progress(remaining=('T1.entry',)),progress(done=())]
        empty=progress();empty['completed'][0]['evidence']=[];invalid.append(empty)
        for value in invalid:
            with self.assertRaises(ValueError):qa_progress.validate_progress(value,'T1','current')
        with self.assertRaisesRegex(ValueError,'no new scenario'):
            qa_progress.validate_progress(progress(),'T1','current',progress())

    def test_only_qa_incomplete_without_defects_or_capabilities_is_accepted(self):
        result=test_team.report('incomplete')
        self.assertEqual(team.validate_report(result,'qa')['status'],'incomplete')
        for role in team.ROLES-{'qa'}:
            with self.assertRaises(ValueError):team.validate_report(result,role)
        for key,value in (('findings',['Source defect']),('capability_requests',['browser']),('evidence',[])):
            with self.assertRaises(ValueError):team.validate_report({**result,key:value},'qa')
        for status in ('clear','completed','changes_requested'):
            with self.assertRaises(ValueError):team.validate_report(test_team.report(status),'qa')


class ContinuationTests(unittest.TestCase):
    setUp=test_team.TeamTests.setUp
    write=test_team.TeamTests.write
    git=test_team.TeamTests.git
    run_role=test_team.TeamTests.run_role
    adopted=test_team.TeamTests.adopted

    def prepare(self):
        self.adopted();self.controller.step()
        self.assertEqual(self.controller.state['stage'],'qa')

    def submit(self,done=('T1.entry',),remaining=('T1.expiry',),status='incomplete'):
        c=self.controller
        value=progress(snapshot=c.state['snapshot'],done=done,remaining=remaining)
        team.save(c.folder/'artifacts'/'qa'/'continuation.json',value)
        self.responses['qa']=test_team.report(status)
        c.step()

    def test_partial_then_complete_preserves_evidence_and_requires_real_pass(self):
        self.prepare();self.submit()
        c=self.controller
        self.assertEqual(c.state['stage'],'qa')
        self.assertNotIn('qa',c.state['receipts'])
        self.assertIn('code_reviewer',c.state['receipts'])
        first=c.state['reports']['qa']
        self.assertEqual(c.context('qa')['qa_progress']['remaining'],['T1.expiry'])
        self.submit(done=('T1.entry','T1.expiry'),remaining=(),status='passed')
        self.assertEqual(c.state['stage'],'devops')
        self.assertEqual(c.state['receipts']['qa']['report']['status'],'passed')
        self.assertTrue((self.project/first).exists())
        self.assertEqual(len(c.state['qa_progress']['completed']),2)

    def test_worker_can_extend_scoped_context_without_losing_results(self):
        self.prepare();self.submit(remaining=('T1.loading','T1.expiry'))
        c=self.controller
        value={**c.context('qa')['qa_progress']}
        value['completed']=[*value['completed'],{'id':'T1.loading','evidence':['Observed held requests']}]
        value['remaining']=['T1.expiry']
        team.save(c.folder/'artifacts'/'qa'/'continuation.json',value)
        old_report=value['report'];self.responses['qa']=test_team.report('incomplete');c.step()
        restored=team.Team(self.project,self.home,runner=self.run_role)
        self.assertEqual(restored.state['stage'],'qa')
        self.assertEqual(restored.state['qa_progress']['completed'],value['completed'])
        self.assertEqual(restored.state['qa_progress']['remaining'],['T1.expiry'])
        self.assertNotEqual(restored.state['qa_progress']['report'],old_report)
        self.assertEqual(restored.state['qa_progress']['scopes'],c.state['scope_fingerprints'])
        self.assertEqual(restored.state['qa_continuation_attempts'],{'T1':2})
        self.assertNotIn('qa',restored.state['receipts'])

    def test_scoped_handoff_cannot_reuse_changed_application_evidence(self):
        self.prepare();c=self.controller
        value=progress(snapshot=c.state['snapshot'])
        value['scopes']={**c.state['scope_fingerprints'],'application':'a'*64}
        team.save(c.folder/'artifacts'/'qa'/'continuation.json',value)
        self.responses['qa']=test_team.report('incomplete');c.step()
        self.assertEqual(c.state['attention_kind'],'qa_progress_invalid')
        self.assertIn('scope is stale',c.state['reason'])
        self.assertNotIn('qa',c.state['receipts'])

    def test_no_progress_stops_instead_of_repeating_paid_work(self):
        self.prepare();self.submit();self.submit()
        c=self.controller
        self.assertEqual(c.state['attention_kind'],'qa_progress_invalid')
        calls=c.state['calls'];c.step()
        self.assertEqual(c.state['calls'],calls)
        self.assertNotIn('qa',c.state['receipts'])

    def test_continuation_budget_survives_restart_and_reports_remaining_ids(self):
        self.prepare();self.submit(remaining=('T1.two','T1.three','T1.four'))
        self.controller=team.Team(self.project,self.home,runner=self.run_role)
        self.submit(done=('T1.entry','T1.two'),remaining=('T1.three','T1.four'))
        self.submit(done=('T1.entry','T1.two','T1.three'),remaining=('T1.four',))
        c=self.controller
        self.assertEqual(c.state['attention_kind'],'qa_continuation_exhausted')
        self.assertIn('T1.four',c.state['reason'])
        self.assertEqual(c.state['qa_continuation_attempts']['T1'],2)
        self.assertNotIn('qa',c.state['receipts'])

    def test_pass_cannot_hide_pending_scenarios_or_use_stale_manifest(self):
        self.prepare();self.submit()
        self.submit(done=('T1.entry','T1.expiry'),remaining=('T1.extra',),status='passed')
        self.assertEqual(self.controller.state['attention_kind'],'qa_progress_invalid')
        self.assertNotIn('qa',self.controller.state['receipts'])
        self.controller.persist(stage='qa')
        value=progress(snapshot='stale')
        team.save(self.controller.folder/'artifacts'/'qa'/'continuation.json',value)
        self.responses['qa']=test_team.report('incomplete');self.controller.step()
        self.assertIn('stale',self.controller.state['reason'])

    def test_stop_and_changed_acceptance_scope_cannot_reuse_progress(self):
        self.prepare();self.submit()
        c=self.controller
        c.stop.write_text('Owner STOP',encoding='utf-8')
        with self.assertRaises(InterruptedError):c.execute('qa')
        old_count=c.state['qa_continuation_attempts'].copy()
        c.state['scope_fingerprints']={**c.state['scope_fingerprints'],'environment':'changed'}
        self.assertIsNone(c.matching_qa_progress())
        self.assertEqual(c.state['qa_continuation_attempts'],old_count)

    def test_blocked_source_defect_routes_to_bounded_repair_not_owner(self):
        self.prepare();c=self.controller
        c.persist(attention_kind='worker_failure',failure_kind='transport')
        self.responses['qa']=test_team.report('blocked',['Source defect in app.txt'])
        c.step()
        self.assertEqual(c.state['stage'],'developer')
        self.assertIsNone(c.state['attention_kind'])
        self.assertIsNone(c.state['failure_kind'])
        self.assertEqual(c.state['attempts'],1)
        self.assertNotIn('qa',c.state['receipts'])


if __name__=='__main__':unittest.main()
