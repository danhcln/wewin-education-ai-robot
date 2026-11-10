"""Real local engines, loaded on demand. Never substitutes fixture speech or text."""
import asyncio
import json
import time
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import httpx
import numpy as np
from .context import prepare_context


class ProviderError(Exception):
    pass


def spoken_message(message,done_reason):
    """Never speak partial reasoning from templates that open <think> in the prompt."""
    message=dict(message)
    text=str(message.get('content',''))
    if '</think>' in text:text=text.rsplit('</think>',1)[1]
    if '<think>' in text or done_reason=='length':
        raise ProviderError('LLM chưa tạo xong câu trả lời cuối; không phát phần suy luận hoặc nội dung bị cắt')
    message['content']=text.strip()
    message.pop('thinking',None)
    return message


class Providers:
    def __init__(self,settings):
        self.settings=settings
        self.asr=None
        self.tts=None
        self.lock=asyncio.Lock()
        self.turn_slots=asyncio.Semaphore(1)
        self.cpu=ThreadPoolExecutor(max_workers=1,thread_name_prefix='wewin-speech')

    async def catalog(self):
        try:
            async with httpx.AsyncClient(timeout=4,trust_env=False) as client:
                response=await client.get(self.settings.ollama.rstrip('/')+'/api/tags')
                response.raise_for_status()
                models=[{'id':m['name'],'name':m['name']} for m in response.json()['models']]
        except (httpx.HTTPError,KeyError,ValueError) as exc:
            raise ProviderError('Không đọc được catalog Ollama local') from exc
        styles=Path(self.settings.tts_models)/'voice_styles'
        voices=[{'id':p.stem,'name':'Supertonic '+p.stem} for p in sorted(styles.glob('*.json')) if p.stem in ('F1','F2','F3','F4','F5','M1','M2','M3','M4','M5')]
        # Initially verified staging languages; broader SDK support is not a test result.
        languages=[{'id':'en-US','name':'English'},{'id':'en','name':'English'}]
        if 'base.en' not in self.settings.asr_model:languages.insert(0,{'id':'vi-VN','name':'Tiếng Việt'})
        return {'models':models,'voices':voices,'languages':languages,
                'asr_model_configured':bool(self.settings.asr_model and Path(self.settings.asr_model).is_dir()),
                'asr_language_scope':'Whisper base.en: chỉ tiếng Anh; chưa xác minh ASR tiếng Việt' if 'base.en' in self.settings.asr_model else 'Whisper multilingual local; ngôn ngữ và chất lượng cần nghiệm thu bằng audio',
                'tts_models_configured':bool(voices),'speech_rate_min':0.7,'speech_rate_max':2.0}

    async def load(self):
        async with self.lock:
            if self.asr is None:
                if not self.settings.asr_model or not Path(self.settings.asr_model).is_dir():
                    raise ProviderError('Thiếu model Whisper local; không tự tải hoặc thay ASR bằng mock')
                try:
                    from faster_whisper import WhisperModel
                    self.asr=await asyncio.to_thread(WhisperModel,self.settings.asr_model,device='cpu',compute_type='int8',cpu_threads=2,num_workers=1,local_files_only=True)
                except Exception as exc:
                    raise ProviderError('Không nạp được model ASR local') from exc
            if self.tts is None:
                try:
                    from supertonic import TTS
                    self.tts=await asyncio.to_thread(TTS,model_dir=self.settings.tts_models,auto_download=False,intra_op_num_threads=2,inter_op_num_threads=1)
                except Exception as exc:
                    raise ProviderError('Không nạp được model TTS local') from exc

    async def transcribe(self,pcm,language=None):
        if 'base.en' in self.settings.asr_model and language not in (None,'en'):raise ProviderError('Model base.en không hỗ trợ ngôn ngữ ASR đã chọn')
        def work():
            segments,_=self.asr.transcribe(np.frombuffer(pcm,dtype='<i2').astype(np.float32)/32768,language=language,beam_size=3,vad_filter=False,initial_prompt='WeWIN Education. Cambridge. IELTS. Khóa học tiếng Anh.',condition_on_previous_text=False)
            return ' '.join(s.text.strip() for s in segments).strip()
        return await asyncio.get_running_loop().run_in_executor(self.cpu,work)

    async def synthesize(self,text,profile):
        def work():
            style=self.tts.get_voice_style(voice_name=profile['voice'])
            wave,_=self.tts.synthesize(text=text,voice_style=style,lang=profile['language'].split('-')[0],speed=profile['speech_rate'],total_steps=5,verbose=False)
            return np.asarray(wave,dtype=np.float32).reshape(-1),self.tts.sample_rate
        return await asyncio.get_running_loop().run_in_executor(self.cpu,work)

    async def llm(self,messages,model):
        try:
            async with httpx.AsyncClient(timeout=self.settings.provider_timeout,trust_env=False) as client:
                messages=[dict(m) for m in messages]
                # The previous "do not translate" instruction contradicted real
                # translation lessons. Do the requested task, including translation.
                messages[0]['content']+='\nCarry out the learner\'s request, including translation when asked. Answer questions instead of echoing them. Return JSON with your final spoken answer in reply, without analysis.'
                token_path=self.settings.qwen25_tokenizer if model.startswith('qwen2.5:') else self.settings.tokenizer
                messages,context=prepare_context(messages,model,token_path)
                schema={'type':'object','properties':{'reply':{'type':'string','description':'Your own final helpful answer to the user, never a narration of reasoning or an echo of the question.'}},'required':['reply'],'additionalProperties':False}
                options={'temperature':0.7,'top_p':0.8,'top_k':20,'min_p':0,'num_predict':512,'num_ctx':8192,'num_thread':4}
                if self.settings.llm_gpu_layers>=0:options['num_gpu']=self.settings.llm_gpu_layers
                body={'model':model,'messages':messages,'stream':self.settings.llm_stream,'think':False,'format':schema,'options':options}
                started=time.monotonic();first=None
                if self.settings.llm_stream:
                    chunks=[];result=None;size=0
                    async with client.stream('POST',self.settings.ollama.rstrip('/')+'/api/chat',json=body) as response:
                        response.raise_for_status()
                        async for line in response.aiter_lines():
                            if not line:continue
                            part=json.loads(line)
                            if not isinstance(part,dict) or not isinstance(part.get('message',{}),dict):raise ValueError('Invalid stream object')
                            if 'error' in part:raise ValueError('Ollama stream failed')
                            text=part.get('message',{}).get('content','')
                            if not isinstance(text,str):raise ValueError('Invalid stream text')
                            if text and first is None:first=time.monotonic()-started
                            size+=len(text)
                            if size>16000:raise ValueError('LLM stream exceeds limit')
                            chunks.append(text)
                            if part.get('done'):result=part;break
                    if result is None:raise ValueError('Incomplete LLM stream')
                    message={'content':''.join(chunks)}
                else:
                    response=await client.post(self.settings.ollama.rstrip('/')+'/api/chat',json=body)
                    response.raise_for_status();result=response.json();message=result['message']
                if not isinstance(message,dict):raise ValueError()
                message=spoken_message(message,result.get('done_reason'))
                reply=json.loads(message['content'])['reply']
                if not isinstance(reply,str) or not reply.strip() or len(reply)>1200:raise ValueError()
                question=next(m['content'] for m in reversed(messages) if m['role']=='user')
                fold=lambda text:re.sub(r'[^a-z0-9]','',unicodedata.normalize('NFD',text.casefold()).encode('ascii','ignore').decode())
                if len(fold(question))>12 and fold(reply)==fold(question):raise ProviderError('LLM chỉ lặp lại yêu cầu; chưa có câu trả lời để phát')
                return {'role':'assistant','content':reply.strip(),'metrics':{**context,'first_token_ms':round(first*1000) if first is not None else None,'elapsed_ms':round((time.monotonic()-started)*1000),'eval_count':result.get('eval_count'),'prompt_eval_count':result.get('prompt_eval_count'),'streamed_validated_before_tts':self.settings.llm_stream}}
        except (httpx.HTTPError,KeyError,ValueError,TypeError) as exc:
            raise ProviderError('LLM local lỗi hoặc quá thời gian; không có câu trả lời thay thế') from exc
