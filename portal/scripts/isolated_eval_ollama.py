"""Own Ollama 11435/model store on E:, leaving the 11434 runtime untouched.

Copy only the installed 4B manifest's public model layers. Never change global
environment variables, production model manifests, keys or service settings.
Ctrl+C terminates the owned child. Model pulls are explicit separate commands.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]


if __name__=='__main__':
    source=Path.home()/'.ollama/models';target=ROOT/'data/ai-eval-models'
    manifest=Path('manifests/registry.ollama.ai/library/qwen3/4b')
    record=json.loads((source/manifest).read_text())
    target.mkdir(parents=True,exist_ok=True)
    for layer in [record['config'],*record['layers']]:
        name='blobs/'+layer['digest'].replace(':','-');dest=target/name
        if not dest.exists():
            dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source/name,dest)
        with dest.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
        if digest!=layer['digest'].split(':')[1]:raise ValueError('Model layer digest mismatch')
    (target/manifest).parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source/manifest,target/manifest)
    env={**os.environ,'OLLAMA_HOST':'127.0.0.1:11435','OLLAMA_MODELS':str(target),'OLLAMA_NUM_PARALLEL':'1','OLLAMA_MAX_LOADED_MODELS':'1','OLLAMA_KEEP_ALIVE':'2m','OLLAMA_GPU_OVERHEAD':'1073741824'}
    binary=Path.home()/'AppData/Local/Programs/Ollama/ollama.exe'
    with subprocess.Popen([str(binary),'serve'],env=env,cwd=ROOT,creationflags=subprocess.CREATE_NO_WINDOW) as child:
        try:sys.exit(child.wait())
        except KeyboardInterrupt:
            child.terminate();child.wait(timeout=20)
