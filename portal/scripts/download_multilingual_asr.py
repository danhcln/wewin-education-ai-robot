"""Explicit host-only public MIT model download. Never touches firmware/assets."""
from pathlib import Path
from huggingface_hub import snapshot_download

if __name__=='__main__':
    root=Path(__file__).resolve().parents[1]
    path=snapshot_download('Systran/faster-whisper-base',revision='ebe41f70d5b6dfa9166e2c581c45c9c0cfc57b66',local_dir=root/'data/ai-whisper-base',allow_patterns=['config.json','model.bin','tokenizer.json','vocabulary.*'],token=False)
    print('Host ASR model downloaded to',path)
