"""Pin the public Qwen3 tokenizer for exact local context accounting."""
import hashlib
import json
import argparse
from pathlib import Path
import httpx

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--family',choices=['qwen3','qwen2.5'],default='qwen3');args=parser.parse_args()
    repo='Qwen/Qwen3-4B' if args.family=='qwen3' else 'Qwen/Qwen2.5-7B-Instruct'
    root=Path(__file__).resolve().parents[1];out=root/('data/ai-qwen3-tokenizer' if args.family=='qwen3' else 'data/ai-qwen25-tokenizer');out.mkdir(parents=True,exist_ok=True)
    with httpx.Client(timeout=120,follow_redirects=True,trust_env=False) as client:
        meta=client.get('https://huggingface.co/api/models/'+repo);meta.raise_for_status();revision=meta.json()['sha']
        files={}
        for name in ('tokenizer.json','tokenizer_config.json'):
            response=client.get(f'https://huggingface.co/{repo}/resolve/{revision}/{name}');response.raise_for_status();(out/name).write_bytes(response.content)
            files[name]=hashlib.sha256(response.content).hexdigest()
    receipt={'repo':repo,'revision':revision,'files':files}
    (out/'receipt.json').write_text(json.dumps(receipt,indent=2));print(json.dumps(receipt))
