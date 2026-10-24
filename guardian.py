"""Independent supervisor: owns controller lifecycle, observations and release handoffs."""
import json
import hashlib
import datetime as dt
import os
from pathlib import Path
import subprocess
from background_process import run as background_run, popen as background_popen
import sys
import time
import urllib.request

import team
from resilience import failure_kind


def command(*args):
    result=background_run([sys.executable,str(team.HOME/'team.py'),*args],cwd=team.PROJECT,
                          capture_output=True,timeout=120,encoding='utf-8',errors='replace')
    if result.returncode:raise RuntimeError(result.stderr[-600:] or result.stdout[-600:])


def health(config):
    try:
        with urllib.request.urlopen(config['operations_url'],timeout=10) as response:
            value=json.load(response)
            if response.status!=200 or value.get('status')!='ready':raise ValueError('Not ready')
            return {'status':'ready','release':value.get('release')}
    except Exception as exc:return {'status':'unavailable','error':type(exc).__name__}


def workflows(commit):
    # Existing gh login only; never read or print authentication values.
    try:
        result=background_run(['gh','run','list','--repo','bolatahmett/AfterDark','--commit',commit,
                               '--limit','30','--json','workflowName,headSha,status,conclusion,url'],
                              capture_output=True,timeout=30,encoding='utf-8')
        if result.returncode:raise RuntimeError('GitHub workflow observation unavailable')
        rows=json.loads(result.stdout)
    except FileNotFoundError:
        request=urllib.request.Request('https://api.github.com/repos/bolatahmett/AfterDark/actions/runs?head_sha='+commit+'&per_page=30',headers={'User-Agent':'AfterDark-release-observer','Accept':'application/vnd.github+json'})
        with urllib.request.urlopen(request,timeout=20) as response:runs=json.load(response)['workflow_runs']
        rows=[{'workflowName':r['name'],'headSha':r['head_sha'],'status':r['status'],'conclusion':r['conclusion'],'url':r['html_url']} for r in runs]
    selected=[]
    for name in ('Local application checks','Oracle deployment'):
        matching=[r for r in rows if r.get('headSha')==commit and r.get('workflowName')==name]
        if not matching:return 'pending',[]
        row=matching[0];selected.append(row)
        if row.get('status')!='completed':return 'pending',selected
        if row.get('conclusion')!='success':return 'failed',selected
    return 'passed',selected


def release_action(controller):
    s=controller.state;c=controller.config
    if s['stage']=='ready_for_commit' and c.get('auto_commit'):
        controller.commit(s['snapshot'],'Deliver '+str(s.get('task') or 'reviewed application changes'))
        return 'committed'
    publishing=c.get('allow_push') and c.get('allow_deploy')
    due=controller.publish_due() if hasattr(controller,'publish_due') else True
    if s['stage']=='release_ready' and publishing and due:
        controller.publish(s['commit']);return 'pushed'
    if s['stage']=='idle' and publishing and due and hasattr(controller,'held_release'):
        held=controller.held_release()
        if held:controller.publish(held);return 'pushed held commits'
    if s['stage']=='release_ready' and (c.get('continue_after_local_commit') or publishing):
        # Not due yet (or push disabled): keep delivering on gated local commits; the next due
        # publication pushes HEAD, which carries every earlier gated commit with it.
        controller.complete_release(local=True);return 'continued'
    return None


def machinery_fingerprint():
    return team.machinery_fingerprint(team.HOME)


def run():
    folder=team.PROJECT/'.supervisor/team-v2';folder.mkdir(parents=True,exist_ok=True)
    # A Windows named mutex is released by the OS on crashes; no stale PID lock.
    import ctypes
    import hashlib
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateMutexW.restype=ctypes.c_void_p
    mutex=kernel.CreateMutexW(None,False,'Local\\AfterDarkGuardian'+hashlib.sha256(str(team.PROJECT).encode()).hexdigest()[:16])
    if not mutex:raise OSError('Guardian mutex unavailable')
    if ctypes.get_last_error()==183:
        kernel.CloseHandle(ctypes.c_void_p(mutex));return
    previous=team.load(folder/'guardian.json',{}) or {}
    child=None;restarts=previous.get('restart_times',[]);last_health=0;last_loop=time.time();last_verify=0
    observation={};reason='Starting';generation=0;exit_reason='Stopped by STOP'
    initial_machinery=machinery_fingerprint();reload_guardian=False
    try:
        while not (folder/'STOP').exists():
            now=time.time();c=team.Team();s=c.state
            gap=now-last_loop;last_loop=now
            if gap>120:c.event('host_gap',seconds=int(gap),note='Host suspension or scheduler delay; not proven worker failure')
            if now-last_health>=c.config['operations_interval_seconds']:
                observation=health(c.config);last_health=now
                team.save(folder/'health.json',{'at':team.stamp(),**observation})
            view=c.view();observed_exit=False
            if child and child.poll() is not None:
                c.event('controller_exit',exit_code=child.returncode)
                if child.returncode!=0:restarts.append(now);observed_exit=True
                child=None
                # The state loaded at the top of this loop predates the controller's final writes
                # (for example a completed repair); persisting it would roll those writes back.
                c=team.Team();s=c.state;view=c.view()
            if not view['controller_alive'] and not (child and child.poll() is None):
                current_machinery=machinery_fingerprint()
                if initial_machinery is None:initial_machinery=current_machinery
                elif current_machinery and current_machinery!=initial_machinery:
                    reload_guardian=True;exit_reason='Reloading repaired coordinator machinery';break
                if c.lock.exists():
                    # Only the existing inventory-checked acquire path archives stale locks.
                    if team.competing_processes(c.project):reason='Waiting for owned processes to exit';time.sleep(2);continue
                    c.lock.replace(folder/('LOCK.archived-guardian-'+str(time.time_ns())))
                if c.state['stage']=='waiting_for_quota':c.resume_quota()
                if c.state['stage'] in {'needs_attention','waiting_recovery'}:c.schedule_intervention()
                try:action=release_action(c)
                except Exception as exc:
                    c.persist(stage='needs_attention',resume_role='devops',attention_kind='release_failure',reason='Guarded release action failed: '+str(exc))
                    c.event('release_action_failed',failure_kind=failure_kind(exc))
                    action=None
                if action:reason=action;continue
                s=c.state
                if s['stage']=='published':
                    if now-last_verify>=30:
                        last_verify=now
                        try:
                            result,rows=workflows(s['published_commit'])
                            reason='Exact-release CI/deployment observation: '+result
                            team.save(folder/'release-observation.json',{'at':team.stamp(),'commit':s['published_commit'],'ci':result,'workflows':rows,'health':observation})
                            if result=='passed' and observation.get('release')==s['published_commit'] and observation.get('status')=='ready':
                                c.persist(stage='release_verified',release_recovery={**(s.get('release_recovery') or {}),'active':False},reason='Exact CI/deployment and live release verified')
                                c.event('release_verified',commit=s['published_commit'])
                            elif s.get('publication_started_at') and now-dt.datetime.fromisoformat(s['publication_started_at']).timestamp()>c.config.get('release_verify_timeout_seconds',3600):
                                c.begin_release_recovery(s['published_commit'],'Exact release verification deadline exceeded; inspect workflow and live SHA')
                            elif result=='failed':
                                c.begin_release_recovery(s['published_commit'],'CI/deployment failed; inspect exact release workflow')
                        except Exception as exc:reason=str(exc)
                elif s['stage']=='release_verified':
                    c.complete_release()
                elif s['stage'] not in {'needs_attention','waiting_for_quota','ready_for_commit','release_ready','uninitialized'}:
                    restarts=[t for t in restarts if now-t<3600]
                    if s.get('controller_status')=='running' and not observed_exit:
                        # A dead controller leaves controller_status running; count that crash once, not every poll.
                        restarts.append(now);c.persist(controller_status='crashed')
                    if len(restarts)>=3:
                        c.persist(stage='needs_attention',resume_role=s.get('active_role') or s['stage'],reason='Controller crash budget exhausted',attention_kind='controller_crash')
                    else:
                        generation+=1
                        out=(folder/'controller.log').open('a',encoding='utf-8');err=(folder/'controller.err').open('a',encoding='utf-8')
                        try:child=background_popen([sys.executable,str(team.HOME/'team.py'),'start','--resume'],cwd=team.PROJECT,stdout=out,stderr=err)
                        finally:out.close();err.close()
                        reason='Controller started; crashes observed '+str(len(restarts))+'/3 per hour'
            team.save(folder/'guardian.json',{'pid':os.getpid(),'at':team.stamp(),'generation':generation,'reason':reason,'host_gap_seconds':int(gap),'restart_times':restarts})
            time.sleep(2)
    except Exception as exc:
        exit_reason=type(exc).__name__+': '+str(exc)
        # Store structured diagnostics rather than relying on a task's invisible console.
        team.save(folder/'guardian-error.json',{'at':team.stamp(),'kind':failure_kind(exc),'error':exit_reason})
        raise
    finally:
        if child and child.poll() is None:
            # A guardian crash must not manufacture an owner STOP and defeat restart.
            if (folder/'STOP').exists():
                try:child.wait(timeout=20)
                except subprocess.TimeoutExpired:team.terminate_owned(child)
            else:team.terminate_owned(child)
        team.save(folder/'guardian.json',{'pid':None,'at':team.stamp(),'reason':exit_reason,'restart_times':restarts})
        kernel.CloseHandle(ctypes.c_void_p(mutex))
    if reload_guardian and not (folder/'STOP').exists():
        os.execv(sys.executable,[sys.executable,str(Path(__file__).resolve())])


if __name__=='__main__':run()
