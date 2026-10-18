"""Read-only operator dashboard. Never launches workers or prints raw command output."""
import datetime as dt
import json
from pathlib import Path
import re
import shutil
import sys
import textwrap
import time


def read_json(path, default=None):
    try:return json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError,ValueError):return default


def safe_text(value):
    value=str(value or '')
    value=re.sub(r'-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----','[PRIVATE KEY REDACTED]',value,flags=re.S)
    value=re.sub(r'(?i)\b(?:bearer\s+)[A-Za-z0-9._~+/=-]+','Bearer [REDACTED]',value)
    value=re.sub(r'([a-zA-Z][a-zA-Z0-9+.-]*://)[^/@\s]+:[^/@\s]+@',r'\1[REDACTED]@',value)
    value=re.sub(r'(?i)\b(password|passwd|token|secret|api_key|authorization|cookie)\s*[:=]\s*(?:"[^"]*"|\x27[^\x27]*\x27|[^\s,;]+)',r'\1=[REDACTED]',value)
    return ''.join(c if c=='\n' or ord(c)>=32 else ' ' for c in value).replace('\x1b',' ')


def tail_events(path, maximum=131072):
    try:
        with path.open('rb') as stream:
            stream.seek(0,2);size=stream.tell();start=max(0,size-maximum);stream.seek(start)
            raw=stream.read(maximum)
        lines=raw.decode('utf-8','replace').splitlines()
        if start:lines=lines[1:]
        result=[]
        for line in lines:
            try:
                event=json.loads(line)
                if isinstance(event,dict):result.append(event)
            except ValueError:pass
        return result
    except OSError:return []


def runtime_path(project, value, subdir):
    try:
        root=(project/'.supervisor/team-v2'/subdir).resolve()
        path=Path(value)
        if not path.is_absolute():path=project/path
        path=path.resolve()
        return path if path.is_relative_to(root) else None
    except (TypeError,ValueError,OSError):return None


def command_label(command):
    # Classify internally; never expose arbitrary shell text, heredocs or output.
    text=str(command or '').lower()
    if any(marker in text for marker in ('write_text', 'apply_patch', 'set-content', 'writefile')):
        return 'Prepare/update source or test artifacts (completion is not a test verdict)'
    labels=[
        (('verify-project-language',),'Project language / UTF-8 checks'),
        (('git diff --check',),'Whitespace checks'),
        (('verify-guest-grace',),'Guest return / nickname lease checks'),
        (('verify-literal-nicknames',),'Nickname allocation / identity checks'),
        (('browser-probe','playwright','puppeteer','chrome','isolation_probe'),'Browser journey / session isolation'),
        (('bootstrap.ps1','serve-loopback','run-probe.ps1'),'Build/start local acceptance environment'),
        (('typecheck',),'TypeScript checks'),
        (('lint',),'Lint checks'),
        (('pnpm build','pnpm --filter @afterdark/web build','pnpm --filter @afterdark/api build'),'Application build'),
        (('i18n.test',),'Translation regression tests'),
        (('node --test','pnpm test','.test.mjs','unittest'),'Automated regression tests'),
        (('pnpm install','npm install','pip install'),'Prepare local dependencies'),
        (('get-nettcpconnection','__recovery_ready','socket.create_connection'),'Check local runtime readiness'),
        (('write_text','apply_patch','set-content'),'Update assigned source / test artifacts'),
        (('get-content','read_text','rg '),'Inspect source / project instructions'),
        (('git status','git diff','rev-parse'),'Inspect source revision / changes'),
    ]
    for needles,label in labels:
        if any(n in text for n in needles):return label
    return 'Local diagnostic / tool command'


def seconds_since(value, now):
    try:
        parsed=dt.datetime.fromisoformat(value.replace('Z','+00:00'))
        if parsed.tzinfo is None:parsed=parsed.replace(tzinfo=dt.timezone.utc)
        return max(0,int((now-parsed).total_seconds()))
    except (AttributeError,TypeError,ValueError):return None


def duration(seconds):
    if seconds is None:return 'unknown'
    return f'{seconds//60}m {seconds%60:02d}s'


def collect(project, state, now=None):
    project=Path(project).resolve();now=now or dt.datetime.now(dt.timezone.utc)
    folder=project/'.supervisor/team-v2'
    events=tail_events(folder/'events.jsonl')
    starts=[e for e in events if e.get('event')=='role_started' and e.get('role')==state.get('active_role')]
    started=starts[-1].get('at') if starts and state.get('active_role') else None
    active=[];last_activity=None
    log=runtime_path(project,state.get('active_log'),'logs')
    if state.get('active_role') and log and log.is_file():
        modified=dt.datetime.fromtimestamp(log.stat().st_mtime,dt.timezone.utc)
        last_activity=max(0,int((now-modified).total_seconds()))
        commands={}
        for e in tail_events(log,262144):
            item=e.get('item') or {}
            if not isinstance(item,dict) or item.get('type')!='command_execution':continue
            status=item.get('status') or ('in_progress' if e.get('type')=='item.started' else 'completed')
            commands[item.get('id') or str(len(commands))]={'label':command_label(item.get('command','')),'status':status}
        active=list(commands.values())[-5:]
    counts={};running={};spent={}
    for event in events:
        role=event.get('role')
        if event.get('event')=='role_started':
            counts[role]=counts.get(role,0)+1;running[role]=event.get('at')
        elif event.get('event')=='role_finished' and role in running:
            try:
                ended=dt.datetime.fromisoformat(event['at'])
                spent[role]=spent.get(role,0)+(seconds_since(running.pop(role),ended) or 0)
            except (ValueError,TypeError):pass
    reports=[]
    for role,value in state.get('reports',{}).items():
        path=runtime_path(project,value,'reports')
        receipt=read_json(path,{}) if path else {}
        if not isinstance(receipt,dict) or not isinstance(receipt.get('report'),dict):continue
        reports.append({**receipt,'role':role,'file':str(path.relative_to(project))})
    reports.sort(key=lambda r:r.get('recorded_at',''),reverse=True)
    config=read_json(project/'agent-team/team.json',{}) or {}
    return {'state':state,'now':now.isoformat(timespec='seconds'),'started_at':started,
            'elapsed_seconds':seconds_since(started,now),'last_activity_seconds':last_activity,
            'actions':active,'reports':reports,'events':events[-8:],'role_counts':counts,'role_seconds':spent,
            'timeout_seconds':config.get('worker_timeout_seconds',1200),
            'call_limit':config.get('max_calls_per_start',24)}


def render(data, width=100):
    s=data['state'];lines=[];width=max(50,min(width,120))
    def add(text=''):
        for paragraph in safe_text(text).splitlines() or ['']:
            lines.extend(textwrap.wrap(paragraph,width=width,replace_whitespace=False) or [''])
    def section(title):add();add(title);add('-'*min(width,72))
    add('AFTERDARK TEAM - LIVE DETAILS | '+data['now'])
    add(f"Controller: {s.get('controller_status','unknown')} | alive={s.get('controller_alive','unknown')} | task={s.get('task') or '-'}")
    add(f"Stage: {s.get('stage')} | STOP requested: {s.get('stop_requested',False)}")
    section('CURRENT WORK')
    if s.get('active_role'):
        add(f"Agent: {s['active_role']} | elapsed: {duration(data['elapsed_seconds'])} | deadline: {duration(data['timeout_seconds'])}")
        if s.get('controller_alive') is not True:add('Controller liveness is unconfirmed; recorded agent activity is not proof it is still running.')
        add('Last log activity: '+duration(data['last_activity_seconds'])+' ago')
        for action in data['actions']:add(f"  [{action['status']}] {action['label']}")
        if not data['actions']:add('Worker starting / reasoning; no command activity recorded yet.')
    else:
        add('No agent is currently executing.')
        if s.get('stage') in {'needs_attention','waiting_for_quota','idle','ready_for_commit','release_ready','published'}:
            add('Waiting condition: '+str(s.get('reason') or s.get('stage')))
        else:add('Next stage: '+str(s.get('stage'))+' (scheduler handoff)')
    add(f"Agent calls this run: {s.get('calls',0)}/{data['call_limit']} | current issue attempts: {s.get('attempts',0)}")
    def approved(role):
        receipt=s.get('receipts',{}).get(role,{})
        if receipt.get('report',{}).get('status')!='passed':return False
        if receipt.get('snapshot')==s.get('snapshot'):return True
        reviewer=s.get('receipts',{}).get('code_reviewer',{})
        if role!='qa' or reviewer.get('snapshot')!=s.get('snapshot'):return False
        old=receipt.get('scopes',{});current=reviewer.get('scopes',{})
        return bool(old) and bool(current) and all(old.get(k)==current.get(k) for k in ('application','environment'))
    section('DELIVERY PROGRESS')
    gates=('code_reviewer','qa','devops')
    done=[r for r in gates if approved(r)]
    add('Completed gates: '+(', '.join(done) or 'none'))
    add('Remaining gates: '+(', '.join(r for r in gates if r not in done) or 'none'))
    add('Current blocker / next action: '+str(s.get('reason') or s.get('stage')))
    next_stage={'environment_engineer':'resume original QA after readiness','code_reviewer':'QA','qa':'DevOps release review','devops':'guarded commit','ready_for_commit':'commit reviewed source','release_ready':'push and trigger CI/deployment','published':'verify exact CI and live release','release_verified':'select next ready work'}
    add('Next handoff: '+next_stage.get(s.get('stage'),'scheduler decision / recorded blocker'))
    add('Failure class: '+str(s.get('failure_kind') or 'none recorded'))
    guardian=s.get('guardian') or {}
    add('Independent supervisor heartbeat: '+str(guardian.get('at') or 'not installed'))
    counts=data.get('role_counts',{})
    add('Repeated starts in retained history: '+(', '.join(str(r)+'='+str(n) for r,n in counts.items() if n>1) or 'none'))
    add('Completed role time in retained history: '+(', '.join(str(r)+' '+duration(n) for r,n in data.get('role_seconds',{}).items()) or 'none'))
    section('CURRENT-SNAPSHOT QUALITY GATES')
    for role in ('code_reviewer','qa','devops'):
        receipt=s.get('receipts',{}).get(role)
        status='not approved'
        if receipt:status=('passed (unchanged runtime scope)' if receipt.get('snapshot')!=s.get('snapshot') else 'passed') if approved(role) else 'stale result or unsuccessful check - review required'
        if s.get('active_role')==role:status='RUNNING'
        add(f"  {role}: {status}")
    section('LAST COMPLETED RESULT - separate from current work')
    if data['reports']:
        last=data['reports'][0];report=last['report']
        add(f"{last['recorded_at']} | {last['role']} | {report.get('status')}")
        add(report.get('summary'))
        for label,key in [('Verified checks','evidence'),('Defects to repair','findings'),('Unrun checks / limitations','limitations')]:
            if report.get(key):
                add(label+':')
                for entry in report[key][:5]:add('  - '+entry)
                if len(report[key])>5:add('  ... use D / report details for the remaining entries.')
        add('Report: '+last['file'])
    else:add('No completed report yet.')
    section('RECENT HANDOFFS (UTC)')
    for event in data['events']:
        detail=event.get('role') or event.get('capability') or ''
        add(f"{event.get('at','?')} | {event.get('event')} | {detail} {event.get('status','')}")
    health=s.get('health') or {}
    section('PUBLICATION / OBSERVATION')
    add(f"Last recorded public health: {health.get('status','unknown')} | release: {health.get('release') or '-'}")
    add('A local check is not production acceptance. Ctrl+C returns to the helper; it does not stop the team.')
    return '\n'.join(lines)


def render_compact(data, width=80):
    """Operator overview; complete evidence remains in report details."""
    s=data['state'];width=max(56,min(width,88));lines=[]
    roles={'code_reviewer':'Code review','qa':'QA','devops':'Release review',
           'environment_engineer':'Test environment','technical_lead':'Technical lead',
           'developer':'Developer','planner':'Planner','operations':'Operations','ux_reviewer':'UX review'}
    stages={'needs_attention':'Needs attention','waiting_for_quota':'Waiting for quota',
            'ready_for_commit':'Ready to commit','release_ready':'Ready to publish',
            'published':'Verifying deployment','release_verified':'Deployment verified',
            'idle':'Waiting for work','schedule':'Selecting work'}
    def stamp(value):
        try:return dt.datetime.fromisoformat(value.replace('Z','+00:00')).astimezone().strftime('%H:%M:%S')
        except (ValueError,AttributeError):return '-'
    def row(label,value):lines.append('  '+label.ljust(18)+safe_text(value))
    def short(value):
        text=safe_text(value)
        text=re.sub(r'\b[a-fA-F0-9]{40,64}\b','[revision]',text)
        return ' '.join(text.split())
    def paragraph(value):
        wrapped=textwrap.wrap(short(value),width=width-4)
        lines.extend('  '+line for line in wrapped[:3])
        if len(wrapped)>3:lines.append('  ... full details: D')
    lines.extend(['='*width,'TEAM LIVE DETAILS   '+stamp(data['now'])+'   |   refresh 30s','='*width])
    running='RUNNING' if s.get('controller_alive') is True else 'UNKNOWN' if s.get('controller_alive') is None else 'STOPPED'
    row('Team',running+'    Task '+str(s.get('task') or '-'))
    row('Stage',stages.get(s.get('stage'),roles.get(s.get('stage'),s.get('stage','-'))))
    active=s.get('active_role') if s.get('controller_alive') is True else None
    row('Agent',roles.get(active,active or '-'))
    if active:
        row('Elapsed',duration(data['elapsed_seconds']))
        row('Activity',data['actions'][-1]['label'] if data['actions'] else 'Starting / reasoning')
        row('Log updated',duration(data['last_activity_seconds'])+' ago')
    if s.get('stop_requested'):row('Stop','Requested')
    lines.append('-'*width)
    lines.append('  QUALITY GATES')
    reviewer=s.get('receipts',{}).get('code_reviewer',{})
    for role in ('code_reviewer','qa','devops'):
        receipt=s.get('receipts',{}).get(role,{})
        approved=receipt.get('report',{}).get('status')=='passed' and receipt.get('snapshot')==s.get('snapshot')
        if not approved and role=='qa' and receipt.get('report',{}).get('status')=='passed' and reviewer.get('snapshot')==s.get('snapshot'):
            old=receipt.get('scopes',{});current=reviewer.get('scopes',{})
            approved=bool(old) and bool(current) and all(old.get(k)==current.get(k) for k in ('application','environment'))
        row(roles[role], 'In progress' if active==role else 'Passed' if approved else 'Pending')
    if s.get('stage') in {'needs_attention','waiting_for_quota'}:
        lines.extend(['-'*width,'  ACTION NEEDED'])
        reason=str(s.get('reason') or 'Inspect full reports')
        if 'changed source' in reason:reason='Source changed during checks; a fresh review is required.'
        paragraph(reason)
    if data['reports']:
        report=data['reports'][0];body=report['report']
        lines.extend(['-'*width,'  LAST RESULT   '+stamp(report.get('recorded_at'))])
        row(roles.get(report['role'],report['role']),body.get('status','-'))
        paragraph(body.get('summary'))
        row('Details',str(len(body.get('evidence',[])))+' evidence entries | '+str(len(body.get('limitations',[])))+' limitations (D)')
    if data['events']:
        lines.extend(['-'*width,'  RECENT ACTIVITY'])
        events={'role_started':'started','role_finished':'finished','capability_requested':'preparation requested','capability_restored':'environment ready','attention':'attention required'}
        for event in data['events'][-4:]:
            who=roles.get(event.get('role'),event.get('role') or '')
            label=events.get(event.get('event'),str(event.get('event','')).replace('_',' '))
            row(stamp(event.get('at')),(who+' '+label).strip()+(' / '+event['status'] if event.get('status') else ''))
    lines.append('-'*width)
    row('Website',(s.get('health') or {}).get('status','unknown')+' (last observation)')
    lines.extend(['-'*width,'  Ctrl+C Back   |   D Full reports in helper   |   No new approval implied','='*width])
    return '\n'.join(lines)


def report_details(project,state):
    data=collect(project,state);lines=[]
    for receipt in data['reports']:
        report=receipt['report']
        lines.append('\n'+'-'*72)
        lines.append(f"{receipt['role']} | {report.get('status')} | {receipt.get('recorded_at')}\n{receipt['file']}")
        lines.append('Summary: '+str(report.get('summary','')))
        for label,key in [('Evidence','evidence'),('Findings','findings'),('Limitations','limitations')]:
            lines.append(label+':')
            lines.extend('  - '+x for x in report.get(key,[]))
        lines.append('Next action: '+str(report.get('next_action','')))
    return safe_text('\n'.join(lines) or 'No completed reports yet.')


def watch(team, interval=30, once=False):
    previous=None
    while True:
        team.state=read_json(team.state_path,{}) or {}
        data=collect(team.project,team.view())
        frame=render_compact(data,shutil.get_terminal_size((80,35)).columns)
        if sys.stdout.isatty() and not once:print('\033[2J\033[H',end='')
        if once or frame!=previous:print(frame,flush=True);previous=frame
        if once:return
        time.sleep(max(.5,interval))
