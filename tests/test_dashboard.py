"""Read-only dashboard presentation, provenance and output privacy contracts."""
import contextlib
import datetime as dt
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import dashboard


class DashboardTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.project=Path(temp.name);self.folder=self.project/'.supervisor/team-v2'
        self.folder.mkdir(parents=True)
        self.now=dt.datetime(2026,10,18,1,0,tzinfo=dt.timezone.utc)
        self.state={'controller_status':'running','controller_alive':True,'stage':'qa','active_role':'qa','task':'T56','calls':3,'snapshot':'current','reports':{},'receipts':{},'last_summary':'OLD FAILURE MUST NOT BE CURRENT'}
        self.write('events.jsonl',json.dumps({'at':'2026-10-18T00:59:00+00:00','event':'role_started','role':'qa'})+'\n')
        self.state['active_log']='.supervisor/team-v2/logs/active.jsonl'
        items=[{'type':'item.started','item':{'id':'a','type':'command_execution','command':'password=DO_NOT_PRINT; node apps/web/test/i18n.test.mjs','status':'in_progress'}},
               {'type':'item.completed','item':{'id':'a','type':'command_execution','command':'node apps/web/test/i18n.test.mjs','status':'completed','aggregated_output':'PRIVATE RAW OUTPUT'}},
               {'type':'item.started','item':{'id':'b','type':'command_execution','command':'node application-browser-probe.mjs','status':'in_progress'}}]
        self.write('logs/active.jsonl',''.join(json.dumps(e)+'\n' for e in items))
        os.utime(self.folder/'logs/active.jsonl',(self.now.timestamp()-7,)*2)

    def write(self,name,text):
        p=self.folder/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text,encoding='utf-8');return p

    def receipt(self,role,at,summary):
        r={'role':role,'recorded_at':at,'snapshot':'current','report':{'status':'passed','summary':summary,'evidence':['Translation tests passed 11/11','Whitespace checks passed'],'findings':[],'limitations':['Physical-device acceptance unrun'],'next_action':'Continue QA'}}
        p=self.write('reports/'+role+'.json',json.dumps(r));self.state['reports'][role]=str(p.relative_to(self.project));return r

    def frame(self):return dashboard.render(dashboard.collect(self.project,self.state,self.now))

    def test_current_work_is_separate_from_previous_completion(self):
        self.receipt('code_reviewer','2026-10-18T00:58:00+00:00','Disclosure repair passed source review')
        frame=self.frame();current=frame.split('CURRENT WORK')[1].split('CURRENT-SNAPSHOT QUALITY GATES')[0]
        self.assertIn('Agent: qa',current);self.assertIn('1m 00s',current)
        self.assertIn('7s',current.replace('0m 07s','7s'))
        self.assertNotIn('OLD FAILURE',current);self.assertIn('Disclosure repair passed source review',frame)
        self.assertIn('Translation tests passed 11/11',frame)

    def test_raw_commands_outputs_and_secret_values_are_not_displayed(self):
        frame=self.frame()
        self.assertIn('Translation regression tests',frame);self.assertIn('Browser journey / session isolation',frame)
        for secret in ('DO_NOT_PRINT','PRIVATE RAW OUTPUT','password=','node application-browser-probe'):
            self.assertNotIn(secret,frame)
        actions=dashboard.collect(self.project,self.state,self.now)['actions']
        self.assertEqual([a['status'] for a in actions],['completed','in_progress'])

    def test_writing_browser_probe_is_preparation_not_browser_acceptance(self):
        label=dashboard.command_label("Path('browser-probe.mjs').write_text('chrome playwright')")
        self.assertIn('Prepare/update',label)
        self.assertNotIn('Browser journey',label)

    def test_quality_gate_receipts_require_current_snapshot(self):
        self.state['receipts']['code_reviewer']={'snapshot':'old','report':{'status':'passed'}}
        frame=self.frame();self.assertIn('code_reviewer: stale result',frame);self.assertIn('qa: RUNNING',frame)

    def test_missing_partial_or_outside_runtime_files_are_safe(self):
        outside=self.project/'outside.json';outside.write_text('{"secret":"DO_NOT_READ"}',encoding='utf-8')
        self.state['reports']['qa']=str(outside);self.state['active_log']=str(outside)
        self.assertNotIn('DO_NOT_READ',self.frame());self.assertIn('No completed report yet',self.frame())
        self.assertEqual(dashboard.tail_events(self.write('broken.jsonl','partial\n'+json.dumps({'event':'valid'})+'\n{')),[{'event':'valid'}])

    def test_full_reports_include_limits_and_next_action_with_redaction(self):
        self.receipt('qa','2026-10-18T00:58:00+00:00','Test result token=PRIVATE_TOKEN')
        text=dashboard.report_details(self.project,self.state)
        self.assertIn('Physical-device acceptance unrun',text);self.assertIn('Next action: Continue QA',text)
        self.assertNotIn('PRIVATE_TOKEN',text);self.assertIn('[REDACTED]',text)
        self.assertNotIn('credentials',dashboard.safe_text('http://user:credentials@localhost'))

    def test_no_active_worker_shows_waiting_condition_not_old_summary(self):
        self.state.update(active_role=None,stage='needs_attention',reason='Required evidence missing')
        frame=self.frame();self.assertIn('No agent is currently executing',frame)
        self.assertIn('Required evidence missing',frame);self.assertNotIn('OLD FAILURE',frame)

    def test_bounded_log_tail_ignores_partial_first_line(self):
        p=self.write('large.jsonl','x'*1000+'\n'+json.dumps({'event':'recent'})+'\n')
        self.assertEqual(dashboard.tail_events(p,100),[{'event':'recent'}])

    def test_compact_overview_omits_verbose_evidence_and_revisions(self):
        self.receipt('code_reviewer','2026-10-18T00:58:00+00:00','Source review completed')
        frame=dashboard.render_compact(dashboard.collect(self.project,self.state,self.now))
        self.assertIn('QUALITY GATES',frame)
        self.assertIn('Browser journey / session isolation',frame)
        self.assertNotIn('Translation tests passed 11/11',frame)
        self.assertNotIn('reports/',frame)
        self.assertLessEqual(len(frame.splitlines()),42)

    def test_once_watch_is_read_only_and_terminates(self):
        state_file=self.write('state.json',json.dumps(self.state));before=state_file.read_bytes()
        fake=SimpleNamespace(project=self.project,state_path=state_file)
        fake.view=lambda:fake.state
        capture=io.StringIO()
        with contextlib.redirect_stdout(capture):dashboard.watch(fake,once=True)
        self.assertIn('LIVE DETAILS',capture.getvalue());self.assertEqual(state_file.read_bytes(),before)


if __name__=='__main__':unittest.main()
