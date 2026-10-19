"""Quota recovery fixtures; no model or account calls."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch, Mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import quota
import team


def limits(primary=0, secondary=66):
    return {'rateLimitsByLimitId': {'codex': {'limitId': 'codex',
            'primary': {'usedPercent': primary}, 'secondary': {'usedPercent': secondary}}}}


class QuotaTests(unittest.TestCase):
    def test_available_only_with_positive_window_evidence(self):
        self.assertEqual(quota.availability(limits()), 'available')
        for value in (None, {}, {'rateLimitsByLimitId': {}},
                      {'rateLimits': {'primary': None, 'secondary': None}}):
            self.assertEqual(quota.availability(value), 'unknown')
        for value in (True, '0', float('nan'), float('inf'), -1):
            self.assertEqual(quota.availability(limits(value)), 'unknown')

    def test_exhausted_weekly_or_primary_and_server_denial_stay_paused(self):
        for value in (limits(100), limits(0, 100), {**limits(), 'ordinaryUsageAllowed': False}):
            self.assertEqual(quota.availability(value), 'exhausted')
        for key, value in (('spendControlReached', True), ('rateLimitReachedType', 'weekly')):
            data=limits();data['rateLimitsByLimitId']['codex'][key]=value
            self.assertEqual(quota.availability(data), 'exhausted')

    def controller(self):
        c=team.Team.__new__(team.Team)
        c.state={'stage':'waiting_for_quota','failure_kind':'quota','resume_role':'qa',
                 'snapshot':'old','calls':7,'delivery_calls':{'T60':12},'receipts':{}}
        c.stop=Mock();c.stop.exists.return_value=False
        c.config={'codex':'codex'};c.project=Path('.')
        c.persist=lambda **changes:c.state.update(changes)
        c.event=Mock()
        return c

    def test_resumes_without_resetting_budgets_or_granting_approval(self):
        c=self.controller()
        with patch.object(team,'read_limits',return_value=limits()) as read, patch.object(team.shutil,'which',return_value='codex'), patch.object(team,'snapshot',return_value={'fingerprint':'old','scopes':{}}):
            c.resume_quota()
        read.assert_called_once()
        self.assertEqual(c.state['stage'],'qa')
        self.assertEqual(c.state['calls'],7)
        self.assertEqual(c.state['delivery_calls'],{'T60':12})
        self.assertEqual(c.state['receipts'],{})

    def test_source_change_requires_review(self):
        c=self.controller()
        with patch.object(team,'read_limits',return_value=limits()), patch.object(team.shutil,'which',return_value='codex'), patch.object(team,'snapshot',return_value={'fingerprint':'new','scopes':{}}):
            c.resume_quota()
        self.assertEqual(c.state['stage'],'code_reviewer')

    def test_stop_policy_and_poll_deadline_prevent_probe(self):
        for scenario in ('stop','policy','deadline'):
            c=self.controller()
            if scenario=='stop':c.stop.exists.return_value=True
            if scenario=='policy':c.state['failure_kind']='policy'
            if scenario=='deadline':c.state['quota_next_check_at']=float('inf')
            with patch.object(team,'read_limits') as read:c.resume_quota()
            read.assert_not_called()
            self.assertEqual(c.state['stage'],'waiting_for_quota')

    def test_failed_or_exhausted_probe_is_throttled_without_worker_call(self):
        for value in (None, limits(100), RuntimeError('probe failure')):
            c=self.controller()
            with patch.object(team,'read_limits',side_effect=value if isinstance(value,Exception) else None,return_value=value) as read, patch.object(team.shutil,'which',return_value='codex'):
                c.resume_quota();c.resume_quota()
            read.assert_called_once()
            self.assertEqual(c.state['stage'],'waiting_for_quota')
            self.assertEqual(c.state['calls'],7)


if __name__=='__main__':unittest.main()
