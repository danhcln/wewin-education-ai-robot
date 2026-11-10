"""Explicit offline import of an approved original audio manifest; no listener or synthesis."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.media.asset_service import AssetService

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--allowed-root', type=Path, required=True)
    parser.add_argument('--asset-root', type=Path, required=True)
    args = parser.parse_args()
    record = json.loads(args.manifest.read_text(encoding='utf-8'))
    print(json.dumps(AssetService(args.asset_root).import_manifest(record, args.allowed_root)))
