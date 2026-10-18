"""Keep coordinator-owned subprocesses windowless on Windows."""
import os
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
