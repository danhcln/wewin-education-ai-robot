"""Read-only protection snapshot, including a consistent Portal backup."""
import hashlib
import json
from pathlib import Path
import sqlite3

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/connection-preflight'


def hashes():
    paths=json.loads((ROOT/'artifacts/self-hosted/protected-before.json').read_text())
    return {name:hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in paths}


if __name__=='__main__':
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/'protected-before.json').write_text(json.dumps(hashes(),indent=2))
    with sqlite3.connect((ROOT/'data/education.sqlite3').as_uri()+'?mode=ro',uri=True) as source,sqlite3.connect(OUT/'education-before.sqlite3') as dest:source.backup(dest)
    print('Captured protected hashes and consistent Portal backup; no service changes.')
