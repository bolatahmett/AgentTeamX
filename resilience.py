"""Deterministic runtime scopes, checkpoints and failure classification."""
import hashlib
import json
import re
from pathlib import Path


# Evidence lines that record delivery, not the acceptance contract. Editing them must not
# invalidate QA evidence for unchanged application and environment files.
DELIVERY_LINE=re.compile(r'^\s*(?:Delivery record|Delivered|Source[ /\w-]*deliver(?:ed|y)|Shared QA update|[\w -]*review repair|Planner opening condition)\b',re.I)
ROW_LINE=re.compile(r'^- \[[ xX]\] \*\*(T\d+[A-Z]?)\b(.*?)\*\*\s*\|\s*(?:todo|in_progress|blocked|done)\s*\|(.*)$')


def tasks_contract_digest(text):
    """Digest of the acceptance contract in tasks.md.

    Excludes checkbox/status, delivery-record lines and the work log and everything after it, so only
    a change to the task definitions or acceptance text counts as an environment-scope change."""
    kept=[]
    for line in text.replace('\r\n','\n').split('\n'):
        if line.startswith('## Work log'):break
        if DELIVERY_LINE.match(line):continue
        match=ROW_LINE.match(line)
        if match:line='- **'+match.group(1)+match.group(2)+'** |'+match.group(3).rstrip()
        kept.append(line.rstrip())
    return hashlib.sha256('\n'.join(kept).encode('utf-8')).hexdigest()


def scopes(files, overrides=None):
    """Scope digests. overrides maps a file name to the digest to use instead of its content hash."""
    overrides=overrides or {}
    groups={'application':{},'environment':{},'team':{}}
    for name,digest in files.items():
        digest=overrides.get(name,digest)
        if name in {'tasks.md','agent.md','AGENTS.md','CLAUDE.md','writing-block.md'} or (
                name.startswith(('docs/product/','docs/launch/','docs/design/')) and
                name!='docs/product/agent-team-setup.md'):
            groups['environment'][name]=digest
            continue
        group=('team' if name.startswith('agent-team/') or name=='Team.cmd' else
               'environment' if name.startswith(('scripts/','.github/')) else 'application')
        if name.startswith('docs/'):
            continue
        groups[group][name]=digest
    return {name:hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()
            for name,value in groups.items()}


def failure_kind(error):
    if isinstance(error,PermissionError):return 'filesystem'
    text=str(error).lower()
    if any(x in text for x in ('quota_limit','out of credits','usage limit','usage_limit','insufficient_quota')):return 'quota'
    if any(x in text for x in ('policy','permission','access denied','sandbox')):return 'policy'
    if any(x in text for x in ('deadline','timeout','timed out')):return 'timeout'
    if any(x in text for x in ('transport','connection reset','cli failed','no structured report')):return 'transport'
    if 'cleanup' in text:return 'cleanup'
    if 'build' in text:return 'build'
    return 'validation'


def allowed_artifact(root, path):
    if path.is_relative_to(root):return True
    if root.name!='team-v2' or root.parent.name!='.supervisor':return False
    project=root.parent.parent
    return any(path.is_relative_to((project/name).resolve()) for name in
               ('apps/web/.next-verify','apps/api/dist','packages/contracts/dist'))


def checkpoint(folder, name, scope, artifacts, evidence, save):
    if name not in {'prepare','build','browser','cleanup'}:raise ValueError('Unknown checkpoint')
    root=Path(folder).resolve();records={}
    if not artifacts or not evidence:raise ValueError('Checkpoint requires artifacts and evidence')
    for value in artifacts:
        path=Path(value).resolve()
        if not allowed_artifact(root,path) or not path.is_file():raise ValueError('Checkpoint artifact outside runtime or approved build outputs')
        import os
        records[os.path.relpath(path,root)]=hashlib.sha256(path.read_bytes()).hexdigest()
    result={'scope':scope,'artifacts':records,'evidence':evidence}
    save(root/'checkpoints'/(name+'.json'),result)
    return result


def reusable(folder, record, scope):
    if not isinstance(record,dict) or record.get('scope')!=scope or not record.get('artifacts'):return False
    root=Path(folder).resolve()
    for value,digest in record['artifacts'].items():
        path=(root/value).resolve()
        if not allowed_artifact(root,path) or not path.is_file():return False
        if hashlib.sha256(path.read_bytes()).hexdigest()!=digest:return False
    return bool(record.get('evidence'))
