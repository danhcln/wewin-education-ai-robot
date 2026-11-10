"""Create a new code-only Docker context. No secrets, DBs, model weights or upload."""
import json
import shutil
from pathlib import Path
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]


if __name__=='__main__':
    target=ROOT/'artifacts/self-hosted'/('vps-context-'+uuid4().hex[:12])
    target.mkdir(parents=True,exist_ok=False)
    portal=target/'wewin_education_portal';portal.mkdir()
    for folder in ('backend','ai_server','docs','frontend/dist'):
        shutil.copytree(ROOT/folder,portal/folder,ignore=shutil.ignore_patterns('__pycache__','tests','*.sqlite3','*.log'))
    shutil.copy2(ROOT/'requirements.txt',portal/'requirements.txt')
    connector=ROOT.parent/'Wewin Connector/Wewin_AI_Connector'
    shutil.copytree(connector/'src',target/'Wewin Connector/Wewin_AI_Connector/src',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    for path in (ROOT/'deploy/self-hosted').iterdir():
        if path.is_file():shutil.copy2(path,target/path.name)
    forbidden=[p for p in target.rglob('*') if p.is_file() and (p.name in ('.env','ai_admin_key','admin_sync_token') or p.suffix in ('.sqlite3','.bin','.onnx','.gguf'))]
    if forbidden:raise RuntimeError('Unexpected runtime artifact in code context; do not upload')
    print(json.dumps({'context':str(target),'code_files':sum(p.is_file() for p in target.rglob('*')),'secrets_databases_models_included':False,'uploaded':False}))
