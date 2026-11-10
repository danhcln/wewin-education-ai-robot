"""Loopback HTTP + read-only SQLite readiness, never seeds or crawls."""
import json
from urllib.request import urlopen
from server_ops import inspect
from src.config import settings
from src.mcp.bridge_status import read_status


if __name__ == '__main__':
    with urlopen('http://127.0.0.1:8000/health', timeout=5) as response:
        health = json.load(response)
    database = inspect(settings.DATABASE_PATH)
    result = {'api': health.get('status'), 'sqlite': database['integrity'],
              'fts_consistent': database['fts']['consistent'],
              'public_searchable': database['public_searchable'], 'bridge': read_status()}
    print(json.dumps(result))
    raise SystemExit(0 if result['api']=='healthy' and result['fts_consistent'] and result['bridge']=='connected' else 1)
