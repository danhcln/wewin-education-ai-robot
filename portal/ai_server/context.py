"""Keep system/current request/tool facts; remove only oldest complete history.

Qwen3 uses the pinned local tokenizer when available. 64 tokens per message is
a conservative allowance for the current Ollama ChatML envelope (no native tool
definitions). Other families/missing tokenizer fall back to a UTF-8 byte upper
bound, never an optimistic chars/token estimate. Nothing downloads at runtime.
"""
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=2)
def tokenizer(path):
    from tokenizers import Tokenizer
    return Tokenizer.from_file(path)


def prepare_context(messages,model,path,limit=7168):
    if not messages or messages[0].get('role')!='system':raise ValueError('Missing system context')
    current=max((i for i,m in enumerate(messages) if m.get('role')=='user'),default=-1)
    if current<1:raise ValueError('Missing current user request')
    use_exact=model.startswith(('qwen3:','qwen2.5:')) and Path(path).is_file()
    counter=(lambda text:len(tokenizer(path).encode(text,add_special_tokens=False).ids)) if use_exact else (lambda text:len(text.encode('utf-8')))
    count=lambda items:sum(counter(str(m.get('content','')))+64 for m in items)
    # History consists of final user/assistant pairs; tool data is current only.
    history=[dict(m) for m in messages[1:current]]
    if len(history)%2 or any(m.get('role')!=('user' if i%2==0 else 'assistant') for i,m in enumerate(history)):raise ValueError('Invalid conversation history')
    head=[dict(messages[0])];tail=[dict(m) for m in messages[current:]];dropped=0
    while history and (len(history)>8 or count(head+history+tail)>limit):
        history=history[2:];dropped+=1
    kept=head+history+tail;used=count(kept)
    if used>limit:raise ValueError('Required context exceeds budget; request/tool facts were not truncated')
    return kept,{'input_budget_estimate':used,'budget_limit':limit,'counting':'qwen_local_tokenizer_plus_envelope_allowance' if use_exact else 'utf8_byte_upper_bound_plus_envelope','history_pairs_removed':dropped}
