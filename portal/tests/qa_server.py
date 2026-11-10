"""Disposable browser QA runtime. Uses its own DB, port and test-only credentials."""
import os
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import uvicorn
from backend import db
from backend.auth import hash_password
from backend.learning import seed_library

db.DB=Path(os.environ['WEWIN_QA_DB']).resolve()
db.migrate()
seed_library()
with db.connection() as conn:
    conn.execute('INSERT OR IGNORE INTO users VALUES(?,?,?,?,?,?,?)',('qa-admin','qa-admin','QA Admin (temporary)',hash_password('WeWIN-QA-only-2026!'),'admin',1,int(time.time())))
    conn.execute('INSERT OR IGNORE INTO user_profiles(user_id) VALUES(?)',('qa-admin',))
uvicorn.run('backend.app:app',host='127.0.0.1',port=int(os.environ.get('WEWIN_QA_PORT','8002')))
