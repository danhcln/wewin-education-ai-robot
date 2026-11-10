"""Explicit public model download, only to owned staging Ollama 11435."""
import json
import argparse
from pathlib import Path
import httpx

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--model',choices=['qwen3:8b','qwen2.5:7b'],default='qwen3:8b');args=parser.parse_args()
    last=-1
    with httpx.Client(base_url='http://127.0.0.1:11435',timeout=600,trust_env=False) as client:
        with client.stream('POST','/api/pull',json={'model':args.model,'stream':True}) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                row=json.loads(line)
                if 'error' in row:raise RuntimeError(row['error'])
                pct=int(row.get('completed',0)*100/max(row.get('total',1),1))//10
                if pct!=last or 'completed' not in row:
                    print(json.dumps({'status':row.get('status'),'tens_percent':pct}),flush=True);last=pct
        result=client.post('/api/show',json={'model':args.model});result.raise_for_status()
        Path('artifacts/staging-hardening/model-'+args.model.replace(':','-')+'.json').write_text(json.dumps(result.json(),indent=2),encoding='utf-8')
