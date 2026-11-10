"""Private local bridge heartbeat, independent from the API process."""
import json
import os
import tempfile
import time
from pathlib import Path
from src.config import settings


def status_path():
    return Path(os.environ.get('BRIDGE_STATUS_PATH', str(settings.DATABASE_PATH.parent / 'bridge-status.json')))


def publish(state):
    path = status_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.bridge-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump({'state': state, 'pid': os.getpid(), 'updated_at': time.time()}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_status():
    try:
        path = status_path()
        if path.stat().st_size > 2048:
            return 'unknown'
        data = json.loads(path.read_text(encoding='utf-8'))
        age = time.time() - float(data['updated_at'])
        if not 0 <= age <= 45:
            return 'unknown'
        from src.sync.locking import is_pid_active
        if not is_pid_active(int(data['pid'])):
            return 'not_connected'
        return data['state'] if data['state'] in ('connected', 'not_connected') else 'unknown'
    except (OSError, ValueError, KeyError, TypeError):
        return 'unknown'
