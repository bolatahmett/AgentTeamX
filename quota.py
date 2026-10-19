"""Read account quota without starting a model turn or reading credentials."""
import json
import math
import queue
import subprocess
import threading
import time
from background_process import popen


def read_limits(binary, project, attach, terminate, timeout=20):
    process = popen([binary, 'app-server'], cwd=project, stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    text=True, encoding='utf-8', errors='replace', bufsize=1)
    close_job = None
    try:
        close_job = attach(process)
        messages = queue.Queue()
        def read():
            try:
                for line in process.stdout:
                    try: messages.put(json.loads(line))
                    except ValueError: continue
            finally: messages.put(None)
        threading.Thread(target=read, daemon=True).start()
        deadline = time.monotonic() + timeout
        def send(value):
            process.stdin.write(json.dumps(value) + '\n')
            process.stdin.flush()
        def response(request_id):
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0: raise TimeoutError('Quota probe timed out')
                try: value = messages.get(timeout=remaining)
                except queue.Empty: raise TimeoutError('Quota probe timed out') from None
                if value is None: raise RuntimeError('Quota probe exited')
                if not isinstance(value, dict) or value.get('id') != request_id: continue
                if 'error' in value: raise RuntimeError('Quota probe request rejected')
                return value.get('result')
        send({'id': 1, 'method': 'initialize', 'params': {
            'clientInfo': {'name': 'afterdark_quota_monitor', 'version': '1.0'}}})
        response(1)
        send({'method': 'initialized', 'params': {}})
        send({'id': 2, 'method': 'account/rateLimits/read'})
        return response(2)
    finally:
        terminate(process)
        if close_job: close_job()
        for stream in (process.stdin, process.stdout):
            if stream: stream.close()


def availability(result):
    """Only positive, current core-bucket evidence can release a quota pause."""
    if not isinstance(result, dict): return 'unknown'
    if result.get('ordinaryUsageAllowed') is False: return 'exhausted'
    buckets = result.get('rateLimitsByLimitId')
    bucket = buckets.get('codex') if isinstance(buckets, dict) else result.get('rateLimits')
    if not isinstance(bucket, dict) or bucket.get('limitId') not in (None, 'codex'): return 'unknown'
    if bucket.get('spendControlReached') or bucket.get('rateLimitReachedType'): return 'exhausted'
    found = False
    for key in ('primary', 'secondary'):
        window = bucket.get(key)
        if window is None: continue
        if not isinstance(window, dict): return 'unknown'
        used = window.get('usedPercent')
        if isinstance(used, bool) or not isinstance(used, (int, float)) or not math.isfinite(used) or used < 0: return 'unknown'
        found = True
        if used >= 100: return 'exhausted'
    return 'available' if found else 'unknown'
