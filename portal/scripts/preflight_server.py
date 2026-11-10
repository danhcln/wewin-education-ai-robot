"""Disposable loopback runtime. Never points to the live Portal or AI database.

Run each service in its own terminal. Ctrl+C stops only that owned QA service.
"""
import argparse
import os
from pathlib import Path
import secrets
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
OUT=ROOT/'artifacts/connection-preflight'


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('service',choices=['ai','portal']);parser.add_argument('--run-dir',type=Path,default=OUT);parser.add_argument('--ollama',choices=['http://127.0.0.1:11434','http://127.0.0.1:11435'],default='http://127.0.0.1:11434');args=parser.parse_args()
    OUT=args.run_dir.resolve()
    if not OUT.is_relative_to(ROOT/'artifacts'):raise ValueError('QA data must be inside ignored artifacts/')
    OUT.mkdir(parents=True,exist_ok=True)
    key=OUT/'admin-key'
    if not key.exists():
        with key.open('x',encoding='utf-8') as stream:stream.write(secrets.token_urlsafe(48))
    os.environ.update(WEWIN_AI_DB=str(OUT/'ai.sqlite3'),WEWIN_AI_ADMIN_KEY_FILE=str(key),WEWIN_AI_ALLOW_REAL_DEVICES='0',WEWIN_AI_PUBLIC_WS='ws://127.0.0.1:8011/xiaozhi/v1/',WEWIN_AI_ORIGIN='http://127.0.0.1:8011',WEWIN_AI_OLLAMA=args.ollama)
    os.environ.setdefault('WEWIN_AI_DEVICE_ORIGIN','http://127.0.0.1:8011')
    if args.ollama.endswith(':11435'):os.environ['WEWIN_AI_LLM_GPU_LAYERS']='24'
    if args.service=='portal':
        os.environ.update(WEWIN_QA_DB=str(OUT/'education-qa.sqlite3'),WEWIN_EDUCATION_DB=str(OUT/'education-qa.sqlite3'),WEWIN_QA_PORT='8002')
        import runpy
        runpy.run_path(str(ROOT/'tests/qa_server.py'),run_name='__main__')
    else:
        import uvicorn
        uvicorn.run('ai_server.app:app',host='127.0.0.1',port=8011,access_log=False)
