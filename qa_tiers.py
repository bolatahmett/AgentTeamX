"""Deterministic QA fast paths: preflight, change tiers, source checks and reusable scenario suites.

Pure helpers only. team.py owns state, process containment and the gate pipeline; nothing here
approves a gate by itself, it only builds the evidence and the report that team.py validates.
"""
import hashlib
import json
import os
import re
import socket
import sys
from pathlib import Path

TASK_ID = re.compile(r'^T\d+[A-Z]?$')
SUITE_ID = re.compile(r'^[A-Za-z0-9_.-]{1,60}$')
SCENARIO_ID = re.compile(r'^[A-Za-z0-9_.:-]{1,120}$')
INTERPRETERS = {'.ps1': 'powershell', '.mjs': 'node', '.js': 'node', '.py': 'python'}
CAPABILITIES = ('browser', 'local_runtime', 'build_tools')


def ui_digest(files, prefixes):
    """Digest of the user-interface files; unchanged means no browser-visible source changed."""
    selected = {name: digest for name, digest in files.items() if any(name.startswith(p) for p in prefixes)}
    return hashlib.sha256(json.dumps(selected, sort_keys=True).encode()).hexdigest()


def classify(last, scopes, ui, forced=None):
    """Return (tier, reason): 0 unchanged, 1 non-UI application change, 2 needs browser acceptance."""
    if forced:
        return 2, forced
    if (not isinstance(last, dict) or not isinstance(last.get('scopes'), dict)
            or not last['scopes'].get('application') or last.get('ui') is None):
        return 2, 'no comparable previous QA pass'
    if last['scopes'].get('environment') != scopes.get('environment'):
        return 2, 'acceptance contract or environment files changed'
    if last['ui'] != ui:
        return 2, 'user-interface files changed'
    if last['scopes']['application'] == scopes.get('application'):
        return 0, 'application and environment unchanged since the last QA pass'
    return 1, 'application changed outside the user-interface paths'


def expand(project, value):
    path = Path(os.path.expandvars(value))
    return path if path.is_absolute() else Path(project) / path


def port_in_use(port):
    for host in ('127.0.0.1', '::1'):
        try:
            with socket.create_connection((host, int(port)), timeout=.5):
                return True
        except OSError:
            continue
    return False


def preflight(project, cfg, which=None, exists=None, in_use=None):
    """Cheap, certain prerequisites for a QA turn. Returns [(capability, message)]; empty means go."""
    which = which or (lambda name: None)
    exists = exists or (lambda path: Path(path).exists())
    in_use = in_use or port_in_use
    failures = []
    for tool in cfg.get('tools', []):
        if not which(tool):
            failures.append(('build_tools', 'Required tool is not on PATH: ' + tool))
    for value in cfg.get('files', []):
        if not exists(expand(project, value)):
            failures.append(('build_tools', 'Required file is missing: ' + value))
    browsers = cfg.get('browser_paths') or []
    if browsers and not any(exists(expand(project, value)) for value in browsers):
        failures.append(('browser', 'No configured browser executable or QA browser directory exists'))
    for port in cfg.get('ports_free', []):
        if in_use(port):
            failures.append(('local_runtime', 'Loopback port %s is in use; a stale or unowned listener blocks the owned QA runtime' % port))
    return failures


def _report(status, summary, evidence, findings=(), limitations=(), next_action='Continue', capability_requests=()):
    return {'status': status, 'summary': summary, 'evidence': list(evidence), 'findings': list(findings),
            'limitations': list(limitations), 'next_action': next_action, 'capability_requests': list(capability_requests)}


GATES_NOT_COVERED = [
    'This controller-run stage exercised no browser journey; mandatory browser acceptance, physical-device checks, '
    'owner acceptance and production acceptance remain separate and unrun unless another report records them.']


def report_unchanged(last):
    return _report('passed',
                   'Controller reuse: application and environment scopes are unchanged since the last QA pass, so its evidence still applies.',
                   ['Last QA pass snapshot %s (tier %s) at %s; application and environment scope digests match the current snapshot.'
                    % (last.get('snapshot', '?'), last.get('tier', '?'), last.get('at', '?'))],
                   limitations=GATES_NOT_COVERED,
                   next_action='Continue to the next gate; the controller keeps the snapshot-bound receipts.')


def report_source_checks(results, scope='Only non-UI application files changed since the last QA pass.'):
    evidence = ['%s: exit %s in %ss (log %s)' % (r['id'], r['exit'], r['seconds'], r['log']) for r in results]
    return _report('passed',
                   'Controller-run source checks passed on the exact current snapshot (' + ', '.join(r['id'] for r in results) + '). '
                   + scope,
                   evidence, limitations=GATES_NOT_COVERED,
                   next_action='Continue to the next gate; browser acceptance stays open on its task rows.')


def log_tail(path, lines=25, limit=4000):
    """Last lines of a check log for a repair finding; empty when unreadable."""
    try:
        text = Path(path).read_bytes()[-65536:].decode('utf-8', errors='replace')
    except OSError:
        return ''
    return '\n'.join(text.strip().splitlines()[-lines:])[-limit:]


def report_source_failures(project, failed):
    """source_only mode: a failed source check is a developer repair, not a QA model turn."""
    findings = []
    for r in failed:
        tail = log_tail(Path(project) / r['log'])
        findings.append('Source check %s failed with exit %s (log %s). Fix the cause and keep the check passing.%s'
                        % (r['id'], r['exit'], r['log'], ('\nLog tail:\n' + tail) if tail else ''))
    return _report('changes_requested',
                   'Controller-run source checks failed on the exact current snapshot (' + ', '.join(r['id'] for r in failed) + ').',
                   ['%s: exit %s in %ss (log %s)' % (r['id'], r['exit'], r['seconds'], r['log']) for r in failed],
                   findings=findings, limitations=GATES_NOT_COVERED,
                   next_action='Developer repairs the failing source checks; QA reruns them on the repaired snapshot.')


def report_suite(manifest, outcome, seconds):
    evidence = ['Suite %s ran %d scenarios in %ss against the current snapshot (result %s).'
                % (manifest['id'], len(manifest['scenarios']), seconds, manifest['result_file'])]
    evidence += ['%s: %s' % (sid, outcome['evidence'][sid][0]) for sid in manifest['scenarios']]
    return _report('passed',
                   'Controller-run scenario suite %s passed every listed scenario on the current snapshot.' % manifest['id'],
                   evidence,
                   limitations=['Physical-device checks, owner acceptance and production acceptance remain separate and unrun.'],
                   next_action='Continue to the next gate.')


def report_preflight(failures):
    caps = []
    for capability, _ in failures:
        if capability not in caps:
            caps.append(capability)
    return _report('blocked',
                   'QA did not start: deterministic local prerequisites are missing, so no model turn was spent.',
                   ['Preflight: ' + message for _, message in failures],
                   limitations=['Mandatory browser acceptance cannot run until the local capability is recovered.'],
                   next_action='Recover the missing local capability (' + ', '.join(caps) + ') and resume QA against the same snapshot.',
                   capability_requests=caps)


# ---------------------------------------------------------------- scenario suites
def _inside(base, relative):
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute() or '..' in Path(relative).parts:
        raise ValueError('Suite paths must be relative to the QA artifact directory')
    target = (Path(base) / relative).resolve()
    if not target.is_relative_to(Path(base).resolve()):
        raise ValueError('Suite path escapes the QA artifact directory')
    return target


def validate_manifest(value, qa_dir):
    """Validate a QA-authored suite manifest and resolve its paths; raises ValueError."""
    required = {'id', 'tasks', 'scenarios', 'script', 'result_file'}
    if not isinstance(value, dict) or not required <= set(value) or set(value) - required - {'args', 'timeout_seconds', 'description'}:
        raise ValueError('Suite manifest requires id, tasks, scenarios, script and result_file')
    if not isinstance(value['id'], str) or not SUITE_ID.match(value['id']):
        raise ValueError('Invalid suite id')
    tasks, scenarios = value['tasks'], value['scenarios']
    if (not isinstance(tasks, list) or not tasks or not all(isinstance(t, str) and TASK_ID.match(t) for t in tasks)):
        raise ValueError('Suite tasks must be task IDs')
    if (not isinstance(scenarios, list) or not scenarios or len(scenarios) > 200 or
            not all(isinstance(s, str) and SCENARIO_ID.match(s) for s in scenarios) or len(set(scenarios)) != len(scenarios)):
        raise ValueError('Suite scenarios must be unique stable IDs')
    script = _inside(qa_dir, value['script'])
    result = _inside(qa_dir, value['result_file'])
    if script.suffix.lower() not in INTERPRETERS or not script.is_file():
        raise ValueError('Suite script must be an existing .ps1, .mjs, .js or .py file')
    args = value.get('args', [])
    if not isinstance(args, list) or len(args) > 20 or not all(isinstance(a, str) and 0 < len(a) <= 200 and '\0' not in a for a in args):
        raise ValueError('Invalid suite arguments')
    timeout = value.get('timeout_seconds', 1500)
    if not isinstance(timeout, int) or isinstance(timeout, bool) or not 60 <= timeout <= 3600:
        raise ValueError('Suite timeout must be 60-3600 seconds')
    return {'id': value['id'], 'tasks': list(tasks), 'scenarios': list(scenarios), 'script': script,
            'result_path': result, 'result_file': value['result_file'], 'args': list(args), 'timeout_seconds': timeout}


def load_suites(qa_dir, read):
    """Return (valid manifests, [error text]); an invalid manifest is reported, never run."""
    suites, errors = [], []
    folder = Path(qa_dir) / 'suites'
    if not folder.is_dir():
        return suites, errors
    for path in sorted(folder.glob('*.json')):
        try:
            suites.append(validate_manifest(read(path), qa_dir))
        except (ValueError, OSError, TypeError) as exc:
            errors.append('%s: %s' % (path.name, exc))
    return suites, errors


def matching_suite(suites, required_tasks, universe=None):
    """The suite that covers every assigned task and any previously enumerated scenario."""
    wanted = set(required_tasks)
    if not wanted:
        return None
    for suite in suites:
        if wanted <= set(suite['tasks']) and (not universe or set(universe) <= set(suite['scenarios'])):
            return suite
    return None


def suite_command(suite, snapshot_value, hosts, url=''):
    """argv for a suite script; arguments are plain tokens, never a shell string.
    {url} is the controller-owned runtime base URL (empty when no runtime was started)."""
    kind = INTERPRETERS[suite['script'].suffix.lower()]
    args = [a.replace('{snapshot}', snapshot_value).replace('{url}', url) for a in suite['args']]
    if kind == 'powershell':
        return [hosts['powershell'], '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', str(suite['script']), *args]
    if kind == 'node':
        return [hosts['node'], str(suite['script']), *args]
    return [hosts.get('python') or sys.executable, '-I', str(suite['script']), *args]


def evaluate_suite(suite, result, snapshot_value):
    """Judge a suite result file. ok only when every listed scenario passed on this exact snapshot."""
    outcome = {'ok': False, 'passed': [], 'failed': [], 'missing': list(suite['scenarios']), 'problems': [], 'evidence': {}}
    if not isinstance(result, dict) or result.get('suite') != suite['id']:
        outcome['problems'].append('result is missing or belongs to another suite')
        return outcome
    if result.get('snapshot') != snapshot_value:
        outcome['problems'].append('result snapshot does not match the current snapshot')
        return outcome
    listed = result.get('scenarios')
    if not isinstance(listed, list):
        outcome['problems'].append('result has no scenario list')
        return outcome
    by_id = {s.get('id'): s for s in listed if isinstance(s, dict)}
    outcome['missing'] = []
    for sid in suite['scenarios']:
        item = by_id.get(sid)
        evidence = item.get('evidence') if item else None
        if item is None or item.get('status') not in {'passed', 'failed'}:
            outcome['missing'].append(sid)
        elif item['status'] == 'failed':
            outcome['failed'].append(sid)
        elif not isinstance(evidence, list) or not evidence or not all(isinstance(e, str) and e.strip() for e in evidence):
            outcome['problems'].append('scenario %s passed without observed evidence' % sid)
        else:
            outcome['passed'].append(sid)
            outcome['evidence'][sid] = evidence
    outcome['ok'] = (not outcome['failed'] and not outcome['missing'] and not outcome['problems']
                     and len(outcome['passed']) == len(suite['scenarios']))
    return outcome


def progress_from_suite(previous, task, snapshot_value, suite, outcome):
    """Continuation checklist that completes every pending scenario from a fully passing suite, or None."""
    if not outcome['ok']:
        return None
    remaining = list(previous['remaining'])
    if not remaining or not set(remaining) <= set(outcome['passed']):
        return None
    completed = [dict(item) for item in previous['completed']]
    completed += [{'id': sid, 'evidence': outcome['evidence'][sid][:3]} for sid in remaining]
    return {'task': task, 'snapshot': snapshot_value, 'completed': completed, 'remaining': []}
