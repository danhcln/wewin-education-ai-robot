"""Startup snapshot: edits on disk cannot retroactively change this proof."""
import hashlib
from importlib.metadata import version
import os
import platform
import subprocess
import time
from .settings import ROOT


def source_fingerprint():
    h=hashlib.sha256()
    for path in sorted((ROOT/'ai_server').glob('*.py')):
        h.update(path.name.encode()+b'\0'+path.read_bytes()+b'\0')
    return h.hexdigest()


def startup_build():
    try:
        commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True,stderr=subprocess.DEVNULL).strip()
        dirty=bool(subprocess.check_output(['git','status','--porcelain','--','ai_server'],cwd=ROOT,text=True,stderr=subprocess.DEVNULL).strip())
    except (OSError,subprocess.SubprocessError):commit='unavailable';dirty=None
    return {'git_commit':commit,'ai_source_dirty':dirty,'ai_source_sha256':source_fingerprint(),'started_at':int(time.time()),'pid':os.getpid(),'python':platform.python_version(),'uvicorn':version('uvicorn')}
