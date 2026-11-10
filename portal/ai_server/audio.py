"""Raw 60 ms Opus frames via libopus; resampling via FFmpeg's PyAV library."""
import os
from pathlib import Path
import numpy as np

_dll_handle=None


def opus_library():
    global _dll_handle
    if os.name=='nt':
        default=Path(__file__).resolve().parents[2]/'references/xiaozhi/python-client/libs/libopus/win/x64'
        folder=Path(os.environ.get('WEWIN_AI_OPUS_DIR',default))
        if not (folder/'opus.dll').is_file():raise RuntimeError('Missing libopus DLL; configure WEWIN_AI_OPUS_DIR')
        if _dll_handle is None:
            _dll_handle=os.add_dll_directory(str(folder))
            os.environ['PATH']=str(folder)+os.pathsep+os.environ.get('PATH','')
    import opuslib_next
    return opuslib_next


class OpusInput:
    def __init__(self):
        self.decoder=opus_library().Decoder(16000,1)

    def decode(self,frame):
        if not 0<len(frame)<=4096:raise ValueError('Invalid Opus packet size')
        # libopus errors are not ValueError; normalize malformed packets so the
        # gateway closes this session cleanly instead of leaking a server error.
        try:pcm=self.decoder.decode(frame,960,False)
        except opus_library().OpusError as exc:raise ValueError('Invalid Opus packet') from exc
        if len(pcm)!=1920:raise ValueError('Expected 60 ms Opus frame at 16 kHz')
        return pcm


class SpeechBoundary:
    """WebRTC VAD over 20 ms PCM; closes a voiced turn after 900 ms silence."""
    def __init__(self):
        import webrtcvad
        self.vad=webrtcvad.Vad(2);self.voiced=False;self.silence_ms=0

    def finished(self,pcm):
        speech=any(self.vad.is_speech(pcm[i:i+640],16000) for i in range(0,len(pcm),640))
        if speech:self.voiced=True;self.silence_ms=0
        elif self.voiced:self.silence_ms+=60
        return self.voiced and self.silence_ms>=900


def encode_audio(wave,sample_rate,target_rate=24000):
    import av
    frame=av.AudioFrame.from_ndarray(np.asarray(wave,dtype=np.float32).reshape(1,-1),format='flt',layout='mono')
    frame.sample_rate=sample_rate
    resampler=av.AudioResampler(format='s16',layout='mono',rate=target_rate)
    pcm=b''.join(f.to_ndarray().tobytes() for f in resampler.resample(frame)+resampler.resample(None))
    codec=opus_library()
    encoder=codec.Encoder(target_rate,1,codec.APPLICATION_VOIP)
    encoder.bitrate=24000
    samples=target_rate*60//1000;size=samples*2
    if not pcm:return []
    pcm+=b'\0'*((-len(pcm))%size)
    return [encoder.encode(pcm[i:i+size],samples) for i in range(0,len(pcm),size)]
