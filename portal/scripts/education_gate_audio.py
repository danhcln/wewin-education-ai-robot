"""Synthetic TTS/Opus/Whisper proxy. No robot or subjective pronunciation score."""
import asyncio
import json
from pathlib import Path
import sys
import time
import numpy as np
import soundfile as sf

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from ai_server.settings import Settings
from ai_server.providers import Providers
from ai_server.audio import encode_audio,opus_library
from scripts.evaluate_education_tts import wer


async def main():
    out=ROOT/'artifacts/real-connection-gate/education/audio';out.mkdir(parents=True,exist_ok=True)
    provider=Providers(Settings());await provider.load();records=[]
    try:
        cases=[('Starter','en-US','This is an apple. The ball is red.'),('A1','en-US','She goes to school every day.'),('A2','en-US','I visited my grandparents last weekend.'),('A1-Vietnamese','vi-VN','Không sao đâu, em hãy thử lại nhé.')]
        for level,language,text in cases:
            start=time.monotonic();wave,rate=await provider.synthesize(text,{'voice':'F1','language':language,'speech_rate':1})
            frames=encode_audio(wave,rate,24000);decoder=opus_library().Decoder(24000,1);pcm=np.frombuffer(b''.join(decoder.decode(f,1440,False) for f in frames),dtype='<i2')
            sf.write(out/(level+'.wav'),pcm,24000,subtype='PCM_16')
            uplink=encode_audio(wave,rate,16000);decoder=opus_library().Decoder(16000,1);input_pcm=b''.join(decoder.decode(f,960,False) for f in uplink)
            transcript=await provider.transcribe(input_pcm,language.split('-')[0])
            records.append({'level':level,'text':text,'asr_roundtrip':transcript,'wer_proxy':wer(text,transcript),'opus_frames':len(frames),'clipping_fraction':float(np.mean(np.abs(pcm.astype(float))>=32767)),'elapsed_s':round(time.monotonic()-start,3),'human_pronunciation_review':False,'robot_audio_playback':False})
            (out/'results.json').write_text(json.dumps({'cases':records,'scope':'Synthetic proxy conflates ASR/TTS errors; no phoneme alignment/MOS/robot certification'},ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'cases':len(records),'human_pronunciation_verified':False,'robot_verified':False}))
    finally:provider.cpu.shutdown(wait=True,cancel_futures=True)


if __name__=='__main__':asyncio.run(main())
