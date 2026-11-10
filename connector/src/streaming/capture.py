"""WASAPI render-loopback only; never opens a microphone.

This Phase 1 adapter captures the selected render endpoint's system mix. Caller
must explicitly consent to system-mix capture and configure a silent local route.
FFmpeg is a streaming encoder only; it receives PCM on stdin, never a URL/file.
"""
from collections import deque
import os
import queue
import shutil
import subprocess
import threading
import time


_cached_loopback = None
_cached_loopback_time = 0.0
_loopback_lock = threading.Lock()

def loopback_devices(force_refresh=False):
    global _cached_loopback, _cached_loopback_time
    now = time.monotonic()
    with _loopback_lock:
        if not force_refresh and _cached_loopback is not None and (now - _cached_loopback_time) < 30.0:
            return _cached_loopback
        try:
            from .service import get_service
            svc = get_service()
            if svc and svc.running and _cached_loopback is not None:
                return _cached_loopback
        except Exception:
            pass
        import pyaudiowpatch as pa
        with pa.PyAudio() as audio:
            try:
                wasapi = audio.get_host_api_info_by_type(pa.paWASAPI)
                def_idx = wasapi.get('defaultOutputDevice', -1)
                def_out = audio.get_device_info_by_index(def_idx) if def_idx >= 0 else {}
                def_name = def_out.get('name', '')
            except Exception:
                def_name = ''
            results = []
            for d in audio.get_loopback_device_info_generator():
                if not d.get('isLoopbackDevice'):
                    continue
                is_def = bool(def_name and d['name'].startswith(def_name))
                clean_name = d['name'].replace(' [Loopback]', '').replace('(Loopback)', '').strip()
                results.append(dict(
                    index=int(d['index']),
                    name=d['name'],
                    clean_name=clean_name,
                    is_default=is_def,
                    sample_rate=int(d['defaultSampleRate']),
                    channels=int(d['maxInputChannels']),
                    is_loopback=True
                ))
            _cached_loopback = results
            _cached_loopback_time = now
            return results


def ogg_packets(stream):
    """Incrementally unwrap encoder stdout; no completed Ogg file is stored/sent."""
    packet=bytearray()
    def exact(n):
        data=bytearray()
        while len(data)<n:
            part=stream.read(n-len(data))
            if not part: return bytes(data)
            data.extend(part)
        return bytes(data)
    while True:
        head=exact(27)
        if not head:return
        if len(head)!=27 or head[:4]!=b'OggS':raise ValueError('Encoder output framing failed')
        lacing=exact(head[26])
        if len(lacing)!=head[26]:raise ValueError('Truncated encoder page')
        for size in lacing:
            part=exact(size)
            if len(part)!=size:raise ValueError('Truncated encoder packet')
            packet.extend(part)
            if len(packet)>65536:raise ValueError('Encoder packet exceeds cap')
            if size<255:
                if not packet.startswith((b'OpusHead',b'OpusTags')):
                    if not 1<=len(packet)<=1275:raise ValueError('Invalid encoded Opus size')
                    yield bytes(packet)
                packet.clear()


def encoder_command(ffmpeg, sample_rate, channels):
    if not 8000<=sample_rate<=192000 or not 1<=channels<=8:raise ValueError('Invalid render format')
    return [ffmpeg,'-nostdin','-hide_banner','-loglevel','error','-f','f32le',
            '-probesize','32','-analyzeduration','1','-avioflags','direct','-blocksize','4096',
            '-ar',str(sample_rate),'-ac',str(channels),'-i','pipe:0','-vn','-ac','1','-ar','24000',
            '-c:a','libopus','-application','lowdelay','-b:a','32k','-vbr','off','-frame_duration','20',
            '-page_duration','20000','-flush_packets','1','-f','ogg','pipe:1']


class CapturePipeline:
    def __init__(self, endpoint, on_packet, ffmpeg=None):
        self.endpoint,self.on_packet=endpoint,on_packet
        self.ffmpeg=ffmpeg or os.environ.get('WEWIN_STREAM_FFMPEG') or shutil.which('ffmpeg')
        self.pcm=queue.Queue(maxsize=10)
        self.stop_event=threading.Event()
        self.finish_event=threading.Event()
        self.process=self.audio=self.stream=None
        self.threads=[]
        self.frames_captured=0;self.pcm_dropped=0;self.packets=0;self.error=None

    def start(self):
        import pyaudiowpatch as pa
        if not self.ffmpeg:raise ValueError('FFmpeg encoder is unavailable')
        self.audio=pa.PyAudio()
        try:
            d=self.audio.get_device_info_by_index(self.endpoint)
            host=self.audio.get_host_api_info_by_index(d['hostApi'])
            if not d.get('isLoopbackDevice') or host['type']!=pa.paWASAPI:
                raise ValueError('Only explicit WASAPI render-loopback devices allowed; microphone rejected')
            rate,channels=int(d['defaultSampleRate']),int(d['maxInputChannels'])
            self.process=subprocess.Popen(encoder_command(self.ffmpeg,rate,channels),stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,bufsize=0,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            def callback(data,frame_count,time_info,status):
                if self.stop_event.is_set():return None,pa.paComplete
                self.frames_captured+=frame_count
                try:self.pcm.put_nowait(data)
                except queue.Full:
                    try:self.pcm.get_nowait()
                    except queue.Empty:pass
                    self.pcm_dropped+=1
                    try:self.pcm.put_nowait(data)
                    except queue.Full:pass
                return None,pa.paContinue
            self.stream=self.audio.open(format=pa.paFloat32,channels=channels,rate=rate,input=True,
                input_device_index=self.endpoint,frames_per_buffer=round(rate*.02),stream_callback=callback,start=False)
            self.threads=[threading.Thread(target=self._write,daemon=True),threading.Thread(target=self._read,daemon=True)]
            for thread in self.threads:thread.start()
            self.stream.start_stream()
        except Exception:
            self.stop();raise

    def _write(self):
        try:
            while not self.stop_event.is_set() or (self.finish_event.is_set() and not self.pcm.empty()):
                try:data=self.pcm.get(timeout=.1)
                except queue.Empty:continue
                self.process.stdin.write(data)
        except (OSError,ValueError):
            if not self.stop_event.is_set():self.error='encoder_input_failed';self.stop_event.set()
        finally:
            try:self.process.stdin.close()
            except (OSError,ValueError):pass

    def _read(self):
        try:
            for packet in ogg_packets(self.process.stdout):
                if self.stop_event.is_set() and not self.finish_event.is_set():break
                self.packets+=1;self.on_packet(packet)
            if not self.stop_event.is_set():
                self.error='encoder_exited';self.stop_event.set()
        except (OSError,ValueError):
            if not self.stop_event.is_set():self.error='encoder_output_failed';self.stop_event.set()

    def stop(self,graceful=False):
        if graceful:self.finish_event.set()
        self.stop_event.set()
        if self.stream:
            try:self.stream.stop_stream();self.stream.close()
            except Exception:self.error='capture_stop_failed'
            self.stream=None
        if self.audio:
            self.audio.terminate();self.audio=None
        if self.process:
            try:
                if not graceful:self.process.terminate()
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:self.process.kill();self.process.wait(timeout=2)
        for thread in self.threads:
            if thread is not threading.current_thread():thread.join(timeout=2)
