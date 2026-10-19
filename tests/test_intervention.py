"""Autonomous coordinator repair tests; no model, account or production calls."""
import ctypes
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from unittest.mock import MagicMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import team
import resilience
import test_team
import guardian


class PersistenceTests(unittest.TestCase):
    def test_transient_replace_failure_retries_same_atomic_payload(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'state.json';team.save(path,{'stage':'old'})
            original=team.os.replace;attempts=[]
            def replace(source,target):
                attempts.append((source,target))
                if len(attempts)<3:raise PermissionError('sharing violation')
                original(source,target)
            with patch.object(team.os,'replace',side_effect=replace),patch.object(team.time,'sleep'):
                team.save(path,{'stage':'new'})
            self.assertEqual(team.load(path),{'stage':'new'})
            self.assertEqual(len(set(attempts)),1)
            self.assertEqual(list(Path(temp).glob('*.tmp')),[])

    def test_failed_persistence_keeps_previous_disk_and_memory_state(self):
        with tempfile.TemporaryDirectory() as temp:
            c=team.Team.__new__(team.Team);c.state_path=Path(temp)/'state.json'
            c.state={'stage':'qa','calls':3};team.save(c.state_path,c.state)
            with patch.object(team.os,'replace',side_effect=PermissionError('sharing violation')),patch.object(team.time,'sleep'):
                with self.assertRaises(PermissionError):c.persist(stage='devops',calls=4)
            self.assertEqual(c.state,{'stage':'qa','calls':3})
            self.assertEqual(team.load(c.state_path),c.state)
            self.assertEqual(list(Path(temp).glob('*.tmp')),[])
            self.assertEqual(resilience.failure_kind(PermissionError('Access is denied')),'filesystem')

    @unittest.skipUnless(os.name=='nt','Windows sharing contract')
    def test_real_windows_reader_lock_recovers_without_partial_state(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'state.json';team.save(path,{'stage':'old'})
            kernel=ctypes.WinDLL('kernel32',use_last_error=True)
            kernel.CreateFileW.argtypes=[ctypes.c_wchar_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p]
            kernel.CreateFileW.restype=ctypes.c_void_p
            kernel.CloseHandle.argtypes=[ctypes.c_void_p]
            handle=kernel.CreateFileW(str(path),0x80000000,3,None,3,0,None)
            self.assertNotIn(handle,(None,ctypes.c_void_p(-1).value))
            release=threading.Timer(.15,lambda:kernel.CloseHandle(handle));release.start()
            try:
                with patch.object(team.os,'replace',wraps=team.os.replace) as replace:
                    team.save(path,{'stage':'resumed'})
                self.assertGreater(replace.call_count,1)
                self.assertEqual(team.load(path),{'stage':'resumed'})
            finally:release.join()


class InterventionTests(unittest.TestCase):
    setUp=test_team.TeamTests.setUp
    write=test_team.TeamTests.write
    git=test_team.TeamTests.git
    run_role=test_team.TeamTests.run_role
    adopted=test_team.TeamTests.adopted

    @unittest.skipUnless(os.name=='nt','Windows sharing contract')
    def test_qa_report_and_progress_survive_real_post_report_state_lock(self):
        self.adopted();c=self.controller;c.step()
        current=team.snapshot(self.project)
        progress={'task':'T1','snapshot':current['fingerprint'],
                  'completed':[{'id':'T1.entry','evidence':['Observed fixture entry']}],
                  'remaining':['T1.history']}
        team.save(c.folder/'artifacts'/'qa'/'continuation.json',progress)
        self.responses['qa']=test_team.report('incomplete')
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.CreateFileW.argtypes=[ctypes.c_wchar_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p]
        kernel.CreateFileW.restype=ctypes.c_void_p
        kernel.CloseHandle.argtypes=[ctypes.c_void_p]
        original_save=team.save;release=None;blocked=[]
        def save_with_reader(path,value):
            nonlocal release
            # The incident occurred after the report was durable, before its
            # continuation transition finished. Hold only this fixture's state.
            if path==c.state_path and 'qa' in value.get('reports',{}) and release is None:
                self.assertTrue((self.project/value['reports']['qa']).is_file())
                handle=kernel.CreateFileW(str(path),0x80000000,3,None,3,0,None)
                self.assertNotIn(handle,(None,ctypes.c_void_p(-1).value))
                release=threading.Timer(.15,lambda:kernel.CloseHandle(handle))
                release.start()
            return original_save(path,value)
        original_replace=team.os.replace
        def replace(source,target):
            try:return original_replace(source,target)
            except PermissionError:
                blocked.append(target)
                raise
        try:
            with patch.object(team,'save',side_effect=save_with_reader),patch.object(team.os,'replace',side_effect=replace):
                c.step()
        finally:
            if release:release.join()
        restored=team.Team(self.project,self.home,runner=self.run_role)
        self.assertTrue(blocked)
        self.assertEqual(set(blocked),{c.state_path})
        self.assertEqual(self.roles,['code_reviewer','qa'])
        self.assertEqual(restored.state['stage'],'qa')
        self.assertEqual(restored.state['qa_progress']['completed'],progress['completed'])
        self.assertEqual(restored.state['qa_progress']['remaining'],['T1.history'])
        self.assertEqual(restored.state['qa_continuation_attempts'],{'T1':1})
        self.assertNotIn('qa',restored.state['receipts'])
        receipt=team.load(self.project/restored.state['reports']['qa'])
        self.assertEqual(receipt['report']['status'],'incomplete')
        self.assertEqual(list(c.folder.glob('*.tmp')),[])

    def stalled(self):
        self.adopted();c=self.controller
        c.config['autonomous_intervention']=True
        team.save(c.home/'team.json',c.config)
        c.step()
        c.persist(stage='needs_attention',resume_role='qa',attention_kind='worker_failure',
                  failure_kind='filesystem',reason='Transient state replacement failed',
                  delivery_calls={'T1':9},release_recovery_calls={'release':4})
        return c

    def repair_result(self):
        c=self.controller
        team.save(c.folder/'artifacts'/'technical_lead'/'intervention-result.json',
                  {'snapshot':c.state['snapshot'],'resume_role':'qa','evidence':['Actual synthetic repair verified']})

    def test_stall_automatically_runs_direct_repair_and_reloads_before_review(self):
        c=self.stalled();c.step()
        self.assertEqual(c.state['stage'],'technical_lead')
        self.assertTrue(c.context('technical_lead')['intervention']['active'])
        self.assertIn('source edits are allowed',c.context('technical_lead')['policy'])
        self.responses['technical_lead']=test_team.report('completed')
        def repair():
            self.write('agent-team/repair.py','# Verified local repair\n')
            self.repair_result()
        self.effects['technical_lead']=repair
        c.step()
        self.assertEqual(c.state['stage'],'code_reviewer')
        self.assertTrue(c.state['controller_reload_required'])
        self.assertFalse(c.state['intervention']['active'])
        self.assertEqual(c.state['delivery_calls'],{'T1':9})
        self.assertEqual(c.state['release_recovery_calls'],{'release':4})
        self.assertEqual(c.state['receipts'],{})
        self.assertEqual(self.roles,['code_reviewer','technical_lead'])

    def test_runtime_only_repair_resumes_qa_without_manufacturing_pass(self):
        c=self.stalled();c.step()
        self.responses['technical_lead']=test_team.report('completed')
        self.effects['technical_lead']=self.repair_result
        c.step()
        self.assertEqual(c.state['stage'],'qa')
        self.assertNotIn('qa',c.state['receipts'])

    def test_stop_and_confirmed_external_boundary_prevent_automatic_work(self):
        c=self.stalled();c.stop.write_text('Owner STOP',encoding='utf-8');c.step()
        self.assertEqual(c.state['stage'],'needs_attention')
        c.stop.unlink();c.step()
        self.responses['technical_lead']=test_team.report('blocked')
        def boundary():
            team.save(c.folder/'artifacts'/'technical_lead'/'intervention-result.json',
                      {'snapshot':c.state['snapshot'],'boundary':'managed_permission',
                       'evidence':['Observed managed policy denial'],
                       'alternatives_tried':['Existing permitted local alternative was unavailable']})
        self.effects['technical_lead']=boundary
        c.step();c.step()
        self.assertEqual(c.state['attention_kind'],'external_blocker')
        self.assertEqual(self.roles,['code_reviewer','technical_lead'])

    def test_budget_waits_and_recovers_automatically_without_resetting_ledgers(self):
        c=self.stalled();c.step()
        incident=c.state['intervention']['incident']
        entry={**c.state['intervention_calls'][incident],'calls':6}
        c.persist(stage='needs_attention',intervention_calls={incident:entry})
        c.step();self.assertEqual(c.state['stage'],'waiting_recovery')
        restored=team.Team(self.project,self.home,runner=self.run_role)
        restored.step();self.assertEqual(restored.state['stage'],'waiting_recovery')
        with patch.object(team.time,'time',return_value=entry['window_started']+3601):restored.step()
        self.assertEqual(restored.state['stage'],'technical_lead')
        self.assertEqual(restored.state['intervention_calls'][incident]['total'],2)
        self.assertEqual(restored.state['delivery_calls'],{'T1':9})
        self.assertEqual(self.roles,['code_reviewer'])

    def test_maintenance_can_run_after_product_budget_without_resetting_it(self):
        c=self.stalled();c.config['max_calls_per_delivery']=0;c.config['max_calls_per_start']=0
        c.step();self.responses['technical_lead']=test_team.report('completed')
        self.effects['technical_lead']=self.repair_result;c.step()
        self.assertEqual(self.roles,['code_reviewer','technical_lead'])
        self.assertEqual(c.state['delivery_calls'],{'T1':9})

    def repaired_with_exhausted_delivery(self,release=False):
        c=self.stalled()
        c.config.update(max_calls_per_delivery=1,max_calls_per_release_recovery=1,max_calls_per_start=0)
        team.save(c.home/'team.json',c.config)
        mission=c.config['delivery_epoch']+':T1'
        c.persist(delivery_calls={mission:24},release_recovery_calls={'historical':4})
        if release:
            c.persist(release_recovery={'active':True,'incident':'fixture-release','phase':'repair'},
                      release_recovery_calls={'release:fixture-release':40})
        c.step()
        self.responses['technical_lead']=test_team.report('completed')
        def repair():
            self.write('agent-team/repair.py','# Verified local machinery repair\n')
            self.repair_result()
        self.effects['technical_lead']=repair
        c.step()
        self.assertEqual(c.state['stage'],'code_reviewer')
        return c,mission

    def test_exhausted_delivery_allows_one_review_qa_devops_pass_after_reload(self):
        c,mission=self.repaired_with_exhausted_delivery()
        incident=c.state['intervention']['incident']
        restored=team.Team(self.project,self.home,runner=self.run_role)
        for _ in team.GATES:restored.step()
        self.assertEqual(self.roles,['code_reviewer','technical_lead',*team.GATES])
        self.assertEqual(restored.state['stage'],'ready_for_commit')
        self.assertEqual(restored.state['delivery_calls'],{mission:24})
        self.assertEqual(restored.state['release_recovery_calls'],{'historical':4})
        self.assertEqual(restored.state['intervention_calls'][incident]['calls'],4)
        self.assertEqual(restored.state['repair_validation']['pending'],[])
        restored.execute('qa')
        self.assertEqual(restored.state['attention_kind'],'call_budget')
        self.assertEqual(self.roles.count('qa'),1)

    def test_repair_validation_cooldown_resumes_gate_without_another_repairer(self):
        c,mission=self.repaired_with_exhausted_delivery()
        incident=c.state['intervention']['incident']
        entry={**c.state['intervention_calls'][incident],'calls':6}
        c.persist(intervention_calls={incident:entry})
        c.step()
        self.assertEqual(c.state['stage'],'waiting_recovery')
        self.assertEqual(c.state['repair_validation']['pending'],team.GATES)
        restored=team.Team(self.project,self.home,runner=self.run_role)
        restored.step();self.assertEqual(restored.state['stage'],'waiting_recovery')
        with patch.object(team.time,'time',return_value=entry['window_started']+3601):
            restored.step();self.assertEqual(restored.state['stage'],'code_reviewer')
            restored.step()
        self.assertEqual(self.roles,['code_reviewer','technical_lead','code_reviewer'])
        self.assertEqual(restored.state['stage'],'qa')
        self.assertEqual(restored.state['delivery_calls'],{mission:24})
        self.assertEqual(restored.state['intervention_calls'][incident]['total'],2)

    def test_repair_validation_honors_global_hourly_budget_and_stop(self):
        c,_=self.repaired_with_exhausted_delivery()
        incident=c.state['intervention']['incident'];entry=c.state['intervention_calls'][incident]
        c.persist(intervention_calls={incident:entry,'other':{**entry,'calls':11}})
        c.step();self.assertEqual(c.state['stage'],'waiting_recovery')
        c.stop.write_text('Owner STOP',encoding='utf-8')
        with patch.object(team.time,'time',return_value=entry['window_started']+3601):c.step()
        self.assertEqual(c.state['stage'],'waiting_recovery')
        self.assertEqual(self.roles,['code_reviewer','technical_lead'])
        with self.assertRaises(InterruptedError):c.execute('code_reviewer')

    def test_repair_validation_cannot_cross_task_batch_source_or_release_scope(self):
        c,_=self.repaired_with_exhausted_delivery()
        current=team.snapshot(self.project)
        self.assertIsNotNone(c.repair_validation('code_reviewer',current))
        # Later gates cannot run before review even with a repair assignment.
        self.assertIsNone(c.repair_validation('qa',current))
        saved=dict(c.state)
        for change in ({'task':'T2'},{'delivery_batch':{'id':'different'}},
                       {'release_recovery':{'active':True,'incident':'new-release'}}):
            with self.subTest(change=change):
                c.state={**saved,**change}
                self.assertIsNone(c.repair_validation('code_reviewer',current))
        c.state=saved
        self.write('app.txt','Changed after repair\n')
        self.assertIsNone(c.repair_validation('code_reviewer',team.snapshot(self.project)))
        c.step()
        self.assertEqual(c.state['attention_kind'],'call_budget')
        self.assertEqual(self.roles,['code_reviewer','technical_lead'])

    def test_failed_verification_consumes_assignment_without_creating_approval(self):
        c,_=self.repaired_with_exhausted_delivery()
        self.responses['code_reviewer']=test_team.report('changes_requested')
        self.responses['code_reviewer']['findings']=['Actual synthetic repair defect']
        c.step()
        self.assertNotIn('code_reviewer',c.state['receipts'])
        self.assertNotIn('code_reviewer',c.state['repair_validation']['pending'])
        c.execute('code_reviewer')
        self.assertEqual(c.state['attention_kind'],'call_budget')
        self.assertEqual(self.roles,['code_reviewer','technical_lead','code_reviewer'])

    def test_controller_crash_during_review_keeps_assignment_for_retry(self):
        c,mission=self.repaired_with_exhausted_delivery()
        incident=c.state['intervention']['incident']
        def crash(role):
            self.roles.append(role);raise RuntimeError('Controller state write failed mid-review')
        c.runner=crash
        with self.assertRaises(RuntimeError):c.execute('code_reviewer')
        restored=team.Team(self.project,self.home,runner=self.run_role)
        self.assertEqual(restored.state['repair_validation']['pending'],team.GATES)
        for _ in team.GATES:restored.step()
        self.assertEqual(restored.state['stage'],'ready_for_commit')
        self.assertEqual(restored.state['delivery_calls'],{mission:24})
        self.assertEqual(restored.state['intervention_calls'][incident]['calls'],5)
        self.assertEqual(restored.state['repair_validation']['pending'],[])

    def test_repaired_release_validation_preserves_both_exhausted_ledgers(self):
        c,mission=self.repaired_with_exhausted_delivery(release=True)
        for _ in team.GATES:c.step()
        self.assertEqual(c.state['stage'],'ready_for_commit')
        self.assertEqual(c.state['delivery_calls'],{mission:24})
        self.assertEqual(c.state['release_recovery_calls'],{'release:fixture-release':40})
        self.assertEqual(self.roles,['code_reviewer','technical_lead',*team.GATES])

    def test_repair_validation_does_not_bypass_quota_wait(self):
        c,_=self.repaired_with_exhausted_delivery()
        pending=c.state['repair_validation']['pending'][:]
        c.persist(stage='waiting_for_quota',resume_role='code_reviewer',failure_kind='quota',
                  quota_next_check_at=team.time.time()+3600)
        c.step()
        self.assertEqual(c.state['stage'],'waiting_for_quota')
        self.assertEqual(c.state['repair_validation']['pending'],pending)
        self.assertEqual(self.roles,['code_reviewer','technical_lead'])

    def test_old_in_memory_controller_handoff_recovers_once_after_reload(self):
        c,mission=self.repaired_with_exhausted_delivery()
        # Model the old finish_intervention: it records a verified report and
        # reload request, but does not yet know the new validation assignment.
        legacy=dict(c.state);legacy.pop('repair_validation')
        team.save(c.state_path,legacy)
        restored=team.Team(self.project,self.home,runner=self.run_role)
        for _ in team.GATES:restored.step()
        self.assertEqual(self.roles,['code_reviewer','technical_lead',*team.GATES])
        self.assertEqual(restored.state['stage'],'ready_for_commit')
        self.assertEqual(restored.state['delivery_calls'],{mission:24})
        restored.persist(stage='code_reviewer')
        restored=team.Team(self.project,self.home,runner=self.run_role)
        restored.execute('code_reviewer')
        self.assertEqual(restored.state['attention_kind'],'call_budget')
        self.assertEqual(self.roles.count('code_reviewer'),2)

    def test_legacy_handoff_cannot_authorize_changed_or_unconfirmed_source(self):
        c,_=self.repaired_with_exhausted_delivery()
        legacy=dict(c.state);legacy.pop('repair_validation')
        path=self.project/legacy['intervention']['report']
        receipt=team.load(path)
        for invalid in ({**receipt,'snapshot':'older'},
                        {**receipt,'report':test_team.report('blocked')}):
            with self.subTest(receipt=invalid):
                team.save(path,invalid);team.save(c.state_path,legacy)
                restored=team.Team(self.project,self.home,runner=self.run_role)
                restored.execute('code_reviewer')
                self.assertNotIn('repair_validation',restored.state)
                self.assertEqual(restored.state['attention_kind'],'call_budget')
        team.save(path,receipt);team.save(c.state_path,legacy)
        self.write('app.txt','Changed since successful repair\n')
        restored=team.Team(self.project,self.home,runner=self.run_role)
        restored.execute('code_reviewer')
        self.assertNotIn('repair_validation',restored.state)
        self.assertEqual(self.roles,['code_reviewer','technical_lead'])

    def test_ordinary_technical_lead_still_cannot_edit_source(self):
        self.adopted();c=self.controller
        self.effects['technical_lead']=lambda:self.write('app.txt','Unexpected source edit\n')
        with self.assertRaisesRegex(RuntimeError,'changed source'):c.execute('technical_lead')

    def test_invalid_result_is_retried_by_coordinator_not_reported_as_external(self):
        c=self.stalled();c.step()
        self.responses['technical_lead']=test_team.report('completed');c.step()
        self.assertEqual(c.state['attention_kind'],'intervention_result_invalid')
        c.step();self.assertEqual(c.state['stage'],'technical_lead')
        self.assertEqual(c.state['intervention_calls'][c.state['intervention']['incident']]['total'],2)

    def test_untyped_local_blocker_cannot_be_parked_as_owner_action(self):
        c=self.stalled();c.step()
        self.responses['technical_lead']=test_team.report('blocked');c.step()
        self.assertEqual(c.state['attention_kind'],'intervention_result_invalid')
        c.step();self.assertEqual(c.state['stage'],'technical_lead')

    def test_unreviewed_maintenance_cannot_jump_directly_to_qa(self):
        c=self.stalled();c.persist(receipts={});c.step()
        self.responses['technical_lead']=test_team.report('completed')
        self.effects['technical_lead']=self.repair_result;c.step()
        self.assertEqual(c.state['stage'],'code_reviewer')

    def test_guardian_wakes_a_stopped_coordinator_for_local_stall(self):
        c=self.stalled();kernel=MagicMock();kernel.CreateMutexW.return_value=1
        def stop(_):c.stop.write_text('Owner STOP',encoding='utf-8')
        child=MagicMock();child.poll.return_value=None
        with patch.object(team,'PROJECT',self.project),patch.object(team,'Team',return_value=c),patch.object(c,'view',return_value={'controller_alive':False}),patch.object(ctypes,'WinDLL',return_value=kernel,create=True),patch.object(ctypes,'get_last_error',return_value=0,create=True),patch.object(guardian,'health',return_value={'status':'ready'}),patch.object(guardian.time,'sleep',side_effect=stop),patch.object(guardian,'background_popen',return_value=child) as spawn:
            guardian.run()
        self.assertEqual(c.state['stage'],'technical_lead')
        spawn.assert_called_once()
        self.assertIn('--resume',spawn.call_args.args[0])

    def test_guardian_reloads_changed_machinery_only_without_active_controller(self):
        c=self.stalled();kernel=MagicMock();kernel.CreateMutexW.return_value=1
        with patch.object(team,'PROJECT',self.project),patch.object(team,'Team',return_value=c),patch.object(c,'view',return_value={'controller_alive':False}),patch.object(ctypes,'WinDLL',return_value=kernel,create=True),patch.object(ctypes,'get_last_error',return_value=0,create=True),patch.object(guardian,'health',return_value={'status':'ready'}),patch.object(guardian,'machinery_fingerprint',side_effect=['old','new']),patch.object(guardian.os,'execv') as reload:
            guardian.run()
        reload.assert_called_once()
        kernel.CloseHandle.assert_called_once()


if __name__=='__main__':unittest.main()
