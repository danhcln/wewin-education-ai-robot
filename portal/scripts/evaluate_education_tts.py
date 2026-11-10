"""TTS/Opus/ASR round-trip diagnostics on actual model replies, not human MOS.
Independent speech provider shared by all candidates. No mic, robot or speaker.
"""
import asyncio
import json
from pathlib import Path
import re
import sys
import time
import numpy as np
import soundfile as sf

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from ai_server.settings import Settings
from ai_server.providers import Providers
from ai_server.audio import encode_audio,opus_library


def words(text):return re.findall(r'\w+',text.casefold())


def wer(reference,hypothesis):
    a=words(reference);b=words(hypothesis);row=list(range(len(b)+1))
    for i,left in enumerate(a,1):
        new=[i]
        for j,right in enumerate(b,1):new.append(min(row[j]+1,new[-1]+1,row[j-1]+(left!=right)))
        row=new
    return row[-1]/max(len(a),1)


async def main():
    root=ROOT/'artifacts/staging-hardening/education';out=root/'tts';out.mkdir(exist_ok=True)
    engines=Providers(Settings());await engines.load();records=[]
    try:
        for file in sorted(root.glob('hardened-*.json')):
            model=json.loads(file.read_text(encoding='utf-8'))
            for case in model['cases']:
                if case['case'] not in ('vocab_apple','correct_go','wewin_ielts') or not case['reply']:continue
                text=case['reply'];profile={'voice':'F1','language':case['language'],'speech_rate':1}
                started=time.monotonic();wave,rate=await engines.synthesize(text,profile);tts_seconds=time.monotonic()-started
                frames=encode_audio(wave,rate);decoder=opus_library().Decoder(24000,1)
                pcm=np.frombuffer(b''.join(decoder.decode(frame,1440,False) for frame in frames),dtype='<i2')
                folder=out/(case['model'].replace(':','-')+'-'+case['case']);folder.mkdir(exist_ok=True)
                sf.write(folder/'response.wav',pcm,24000,subtype='PCM_16')
                uplink=encode_audio(wave,rate,16000);decoder=opus_library().Decoder(16000,1);input_pcm=b''.join(decoder.decode(frame,960,False) for frame in uplink)
                asr=await engines.transcribe(input_pcm,case['language'].split('-')[0])
                row={'model':case['model'],'case':case['case'],'text':text,'asr_roundtrip':asr,'word_error_rate_proxy':wer(text,asr),'synthesis_seconds':tts_seconds,'audio_duration_s':len(pcm)/24000,'opus_frames':len(frames),'clipping_fraction':float(np.mean(np.abs(pcm.astype(float))>=32767)),'rms':float(np.sqrt(np.mean((pcm.astype(float)/32768)**2))),'human_listening':'NOT_RUN','physical_speaker':'NOT_RUN'}
                records.append(row);(out/'results.json').write_text(json.dumps({'scope':'Synthetic round-trip; ASR errors and TTS errors are conflated; not human intelligibility/MOS','cases':records},ensure_ascii=False,indent=2),encoding='utf-8')
                print(json.dumps({'model':case['model'],'case':case['case'],'wer_proxy':row['word_error_rate_proxy']}),flush=True)
    finally:engines.cpu.shutdown(wait=True,cancel_futures=True)


if __name__=='__main__':asyncio.run(main())
