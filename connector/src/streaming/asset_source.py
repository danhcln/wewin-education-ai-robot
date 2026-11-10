"""Paced owned-file source using the existing Opus packetizer. Never accepts URLs."""
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time
from .capture import ogg_packets


class AssetSource:
    def __init__(self, path, on_packet, offset_ms=0):
        self.path = Path(path).resolve(strict=True)
        self.on_packet = on_packet
        if type(offset_ms) is not int or not 0 <= offset_ms <= 86400000:
            raise ValueError('invalid_asset_offset')
        self.offset_ms = offset_ms
        self.frames_captured = self.pcm_dropped = 0
        self.error = None
        self.eof = threading.Event()
        self.closed = threading.Event()
        self.process = None

    def start(self):
        ffmpeg = os.getenv('WEWIN_STREAM_FFMPEG') or shutil.which('ffmpeg')
        if not ffmpeg:
            raise ValueError('ffmpeg_missing')
        # Accurate decoding seek for a local approved file. Re-encoding resets Opus
        # pre-skip; native near-position resume remains subject to hardware validation.
        args = [ffmpeg, '-nostdin', '-hide_banner', '-loglevel', 'error', '-i', str(self.path),
                '-ss', str(self.offset_ms / 1000), '-vn', '-ac', '1', '-ar', '24000',
                '-c:a', 'libopus', '-application', 'lowdelay', '-b:a', '32k', '-vbr', 'off',
                '-frame_duration', '20', '-page_duration', '20000', '-flush_packets', '1', '-f', 'ogg', 'pipe:1']
        self.process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.thread = threading.Thread(target=self._run, daemon=True, name='owned-opus-source')
        self.thread.start()

    def _run(self):
        try:
            deadline = time.monotonic()
            for packet in ogg_packets(self.process.stdout):
                if self.closed.wait(max(0, deadline - time.monotonic())):
                    return
                self.on_packet(packet)
                self.frames_captured += 480
                # Backpressure must never cause a catch-up burst/drop-oldest.
                deadline = max(deadline + .020, time.monotonic())
            if self.process.wait(timeout=3) != 0:
                self.error = 'asset_decode_failed'
            elif not self.closed.is_set():
                self.eof.set()
        except Exception:
            if not self.closed.is_set():
                self.error = 'asset_decode_failed'

    def stop(self, graceful=False):
        self.closed.set()
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
        if hasattr(self, 'thread') and self.thread is not threading.current_thread():
            self.thread.join(timeout=4)
        if self.process and self.process.stdout:
            self.process.stdout.close()
