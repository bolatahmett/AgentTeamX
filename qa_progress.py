"""Validate bounded QA handoffs without promoting observations to approval."""
import re


def validate_progress(value, task, snapshot, previous=None, current_scopes=None):
    required={'task','snapshot','completed','remaining'}
    if (not isinstance(value, dict) or not required<=set(value) or
            set(value)-required-{'scopes','report'}):
        raise ValueError('QA continuation requires task, snapshot, completed and remaining')
    if value['task']!=task or value['snapshot']!=snapshot:
        raise ValueError('QA continuation task or snapshot is stale')
    # Workers may extend the enriched checklist supplied in their context.
    # Check supplied provenance, then discard controller-owned metadata.
    if 'scopes' in value:
        scopes=value['scopes']
        if (not isinstance(scopes,dict) or set(scopes)!={'application','environment','team'} or
                not all(isinstance(s,str) and re.fullmatch(r'[a-f0-9]{64}',s) for s in scopes.values())):
            raise ValueError('Invalid QA continuation scopes')
        if current_scopes is not None and any(scopes[k]!=current_scopes.get(k) for k in ('application','environment')):
            raise ValueError('QA continuation application or environment scope is stale')
    if 'report' in value and (not isinstance(value['report'],str) or not value['report'].strip()):
        raise ValueError('Invalid QA continuation report metadata')
    completed=value['completed'];remaining=value['remaining']
    if not isinstance(completed,list) or not isinstance(remaining,list) or len(completed)+len(remaining)>200:
        raise ValueError('Invalid QA scenario lists')
    def valid_id(value):
        return isinstance(value,str) and re.fullmatch(r'[A-Za-z0-9_.:-]{1,120}',value)
    ids=[]
    for item in completed:
        if not isinstance(item,dict) or set(item)!={'id','evidence'} or not valid_id(item['id']):
            raise ValueError('Invalid completed QA scenario')
        evidence=item['evidence']
        if not isinstance(evidence,list) or not evidence or not all(isinstance(s,str) and s.strip() for s in evidence):
            raise ValueError('Completed QA scenarios require observed evidence')
        ids.append(item['id'])
    if not all(valid_id(item) for item in remaining) or len(set(ids+remaining))!=len(ids+remaining):
        raise ValueError('Duplicate or invalid QA scenario IDs')
    if previous:
        old_done={item['id'] for item in previous['completed']}
        old_all=old_done | set(previous['remaining'])
        if set(ids+remaining)!=old_all or not old_done<=set(ids):
            raise ValueError('QA continuation dropped or replaced previously assigned scenarios')
        if not set(ids)-old_done:
            raise ValueError('QA continuation made no new scenario progress')
    if not ids:raise ValueError('QA continuation requires observed scenario progress')
    return {key:value[key] for key in ('task','snapshot','completed','remaining')}
