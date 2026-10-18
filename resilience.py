"""Deterministic runtime scopes, checkpoints and failure classification."""
import hashlib
import json
from pathlib import Path


def scopes(files):
    groups={'application':{},'environment':{},'team':{}}
    for name,digest in files.items():
        if name in {'tasks.md','agent.md','AGENTS.md','writing-block.md'} or (
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
    text=str(error).lower()
    if any(x in text for x in ('quota_limit','out of credits','429')):return 'quota'
    if any(x in text for x in ('policy','permission','access denied','sandbox')):return 'policy'
    if 'deadline' in text or 'timeout' in text:return 'timeout'
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
