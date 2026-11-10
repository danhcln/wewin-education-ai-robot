"""Explicit operator-only audio file server. --plan is read-only; no Auto-Sync/Cloud."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from src.media.audio_server import main
if __name__=='__main__':main()
