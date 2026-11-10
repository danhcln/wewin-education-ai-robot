"""Existing Control Center entrypoint; audited Windows startup implementation."""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.windows_services import main
if __name__ == '__main__':
    raise SystemExit(main())
