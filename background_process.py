"""Keep coordinator-owned subprocesses windowless on Windows."""
import os
import shutil
import subprocess


def options(values):
    values=dict(values)
    if os.name=='nt':
        values['creationflags']=values.get('creationflags',0)|subprocess.CREATE_NO_WINDOW
    return values


def run(*args,**kwargs):
    return subprocess.run(*args,**options(kwargs))


def popen(*args,**kwargs):
    return subprocess.Popen(*args,**options(kwargs))


def gh_executable():
    """Absolute gh path: PATH first, then the standard Windows install folders (a service PATH may omit them)."""
    found=shutil.which('gh')
    if found:return found
    for root in (os.environ.get('ProgramFiles'),os.environ.get('ProgramFiles(x86)'),os.environ.get('LOCALAPPDATA')):
        if root:
            for sub in ('GitHub CLI','Programs/GitHub CLI'):
                candidate=os.path.join(root,sub,'gh.exe')
                if os.path.isfile(candidate):return candidate
    return 'gh'
