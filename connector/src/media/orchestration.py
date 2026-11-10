"""One media authority; async intent admission, generation fence and actual ACKs."""
from collections import OrderedDict, deque
import logging
import re
import threading
import time
from uuid import uuid4
from .intent import intent
from .resolver import MediaResolver
from .youtube import MediaError

log = logging.getLogger('WEWIN_MEDIA')

def owner():
    # src.api.__init__ eagerly constructs app; import only after module loading.
    from src.api.browser_sessions import OWNER
    return OWNER


class MediaSession:
    def __init__(self, browser, youtube, stream, control, capture_devices):
        self.browser, self.youtube, self.stream, self.control = browser, youtube, stream, control
        self.capture_devices = capture_devices
        self.resolver = MediaResolver(youtube)
        self.lock = threading.RLock()
        self.jobs = deque()
        self.requests = OrderedDict()
        self.generation = 0
        self.current = {'state': 'IDLE', 'generation': 0, 'last_error': None}
        self.closed = threading.Event()
        self.thread = None

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.closed.clear()
        self.thread = threading.Thread(target=self._run, daemon=True, name='wewin-media-session')
        self.thread.start()

    def shutdown(self):
        self.closed.set()
        self.stream.stop()

    def status(self):
        with self.lock:
            return {**self.current, 'hardware_audio_verified': False,
                    'video_playing': self.current.get('browser_state') == 'PLAYING',
                    'stream_playing': self.current.get('stream_state') == 'PLAYING',
                    'stream_error': self.current.get('last_error')}

    def submit(self, body, device_id=None):
        target = self.control.config.get('default_device')
        if not target:
            try:
                target = self.control.device()['device_id']
            except ValueError:
                target = None
        if device_id is not None and target is not None and device_id != target:
            return {'status': 'wrong_device', 'playback_confirmed': False}
        action = body.get('action')
        if action == 'command':
            parsed = intent(body.get('utterance'), self.current['state'] not in ('IDLE', 'ENDED', 'ERROR'))
            body = {**body, **parsed}
            action = body['action']
        elif action in ('play', 'replace'):
            raw_q = body.get('query', '')
            parsed = intent(raw_q, self.current['state'] not in ('IDLE', 'ENDED', 'ERROR'))
            if parsed.get('action') in ('stop', 'pause', 'resume', 'mute_robot', 'unmute_robot', 'set_volume', 'increase_volume', 'decrease_volume'):
                action = parsed['action']
                body = {**body, **parsed}
            elif parsed.get('action') in ('play', 'replace') and parsed.get('query'):
                body['query'] = parsed['query']
        if action == 'status':
            return self.status()
        if action in ('set_volume', 'increase_volume', 'decrease_volume', 'mute_robot', 'unmute_robot'):
            try:
                device = self.control.device()
            except ValueError:
                return {'status': 'device_unavailable'}
            cur_vol = device.get('volume', 70)
            if action == 'set_volume':
                new_vol = max(0, min(100, int(body.get('value', 70))))
            elif action == 'increase_volume':
                new_vol = min(100, cur_vol + body.get('delta', 10))
            elif action == 'decrease_volume':
                new_vol = max(0, cur_vol + body.get('delta', -10))
            elif action == 'mute_robot':
                new_vol = 0
            elif action == 'unmute_robot':
                new_vol = cur_vol if cur_vol > 0 else 70
            
            with self.lock:
                gen = self.generation
            if action == 'mute_robot':
                job_id = self.control.mute(gen)
                new_vol = 0
            elif action == 'unmute_robot':
                job_id = self.control.unmute(None, gen)
                new_vol = self.control.device().get('volume', 70)
            else:
                job_id = self.control.set_volume(new_vol, gen)
            return {'status': 'intent_accepted', 'action': action, 'volume': new_vol, 'job_id': job_id}
        if action not in ('play', 'replace', 'select', 'pause', 'resume', 'stop', 'interrupt', 'ended', 'next'):
            return {'status': 'unrecognized_media_intent'}
        rid = body.get('request_id')
        if not isinstance(rid, str) or not re.fullmatch('[a-zA-Z0-9_-]{8,64}', rid):
            return {'status': 'invalid_request_id'}
        signature = (action, body.get('query'), body.get('video_id'), device_id, bool(body.get('owned_audio')), tuple(body.get('queue', [])))
        with self.lock:
            if rid in self.requests:
                return {'status': 'duplicate_request' if self.requests[rid] == signature else 'request_conflict'}
            if len(self.jobs) >= 8:
                return {'status': 'media_busy'}
            self.requests[rid] = signature
            while len(self.requests) > 128:
                self.requests.popitem(last=False)
            self.generation += 1
            gen = self.generation
            self.current.update(generation=gen, updated_at=time.time(), last_error=None, requested_action=action)
            if action in ('play', 'replace', 'select', 'next'):
                self.current['state'] = 'RESOLVING'
            elif action == 'resume':
                self.current['state'] = 'LOADING'
            elif action in ('pause', 'interrupt', 'stop', 'ended'):
                self.current['state'] = 'STOPPING'
            if action in ('pause','interrupt') and self.current.get('source_kind')=='owned_asset':
                self.current['position_ms']=self.current.get('base_offset_ms',0)+(self.stream.status().get('device_report') or {}).get('position_ms',0)
            # Invalidate queued work and stop production immediately; old jobs guard every step.
            self.jobs.clear()
            self.stream.stop(graceful=(action == 'ended'))
            self.current['stream_state'] = self.stream.status().get('state', 'STOPPING')
            self.jobs.append((gen, dict(body), device_id))
            self.start()
        log.info('WEWIN_MEDIA %s_requested generation=%d', action, gen)
        return {'status': 'intent_accepted', 'generation': gen, 'playback_confirmed': False}

    def _guard(self, gen):
        if self.closed.is_set() or gen != self.generation:
            raise MediaError('obsolete_generation', 'Ý định đã được thay thế.')

    def _update(self, gen, **values):
        with self.lock:
            self._guard(gen)
            self.current.update(values, updated_at=time.time())

    def _browser(self, gen, action, video_id=None):
        self._guard(gen)
        args = {'action': action, 'request_id': uuid4().hex, 'media_generation': gen}
        if video_id:
            args['video_id'] = video_id
        answer = self.browser.command(owner(), args, self.youtube, device=self.current.get('browser_device_id'))
        self._guard(gen)
        if answer.get('status') != 'command_confirmed':
            raise MediaError('browser_' + answer.get('status', 'not_confirmed'), 'Player chưa ACK đúng trạng thái.')
        self._update(gen, browser_state=answer.get('state'))
        return answer

    def _browser_status(self):
        return self.browser.status(owner(), self.current.get('browser_device_id'))

    def _retire(self, gen, graceful=False):
        self.stream.stop(graceful=graceful)
        job_id = self.control.send('end' if graceful else 'stop', gen)
        until = time.monotonic() + 6
        while time.monotonic() < until:
            self._guard(gen)
            device = self.control.device()
            actual = device.get('stream', {})
            status = self.stream.status()
            if device.get('ack') == job_id and not status.get('transport_active', False) and status.get('state') in ('IDLE', 'ERROR') and actual.get('state') in ('IDLE', 'ERROR') and not actual.get('worker_running'):
                # ERROR with an unreleased owner is not an IDLE success.
                if actual.get('state') == 'ERROR' and actual.get('owner_released') is not True:
                    raise MediaError('device_release_not_confirmed', 'Thiết bị chưa xác nhận nhả loa.')
                self._update(gen, stream_state='IDLE')
                return
            time.sleep(.05)
        raise MediaError('device_release_timeout', 'Chưa có xác nhận dừng từ thiết bị.')

    def _execute(self, gen, body, caller):
        action = body['action']
        if action == 'interrupt':
            action = 'pause'
        self._guard(gen)
        device = self.control.device()
        if caller is not None and device['device_id'] != caller:
            raise MediaError('wrong_device', 'Thiết bị không phải loa mặc định đã ghép.')
        if device.get('file_active'):
            raise MediaError('file_owner_busy', 'File playback đang giữ loa; không trộn hai mode.')
        self._update(gen, device_id=device['device_id'], device_ip=device['ip'])
        if body.get('owned_audio') or self.current.get('source_kind') == 'owned_asset':
            return self._execute_asset(gen, body)
        browser_status = self._browser_status()
        if not browser_status.get('connected'):
            raise MediaError('browser_unavailable', 'Hãy mở Media Player đã đăng nhập.')
        self._update(gen, browser_device_id=browser_status.get('device_id'))
        # Stop/fence first, including a pending native handoff before HELLO.
        self._retire(gen, action == 'ended')
        if action in ('pause', 'stop', 'ended'):
            if action != 'ended' and self._browser_status().get('selected_video'):
                self._browser(gen, 'pause' if action == 'pause' else 'stop')
            self._update(gen, state={'pause': 'PAUSED', 'stop': 'IDLE', 'ended': 'ENDED'}[action], stream_state='IDLE')
            if action in ('stop', 'ended'):
                self._update(gen, browser_device_id=None)
            return
        if action in ('play', 'replace', 'select'):
            if self._browser_status().get('selected_video'):
                self._browser(gen, 'stop')
            if body.get('video_id'):
                video = self.youtube.video(body['video_id'])
                resolved = {'status': 'resolved', 'youtube_video_id': video['video_id'], 'title': video['title'], 'media_id': 'youtube:' + video['video_id']}
            else:
                log.info('WEWIN_MEDIA resolve_requested generation=%d', gen)
                resolved = self.resolver.resolve(body.get('query'), 'wewin', self.status())
            self._guard(gen)
            if resolved.get('status') != 'resolved':
                self._update(gen, candidates=resolved.get('candidates', []))
                raise MediaError('resolver_' + resolved.get('status', 'failed'), 'Không chọn video khi chưa đủ chắc chắn.')
            self._update(gen, session_id=uuid4().hex, media_id=resolved['media_id'], video_id=resolved['youtube_video_id'],
                         title=resolved['title'], state='LOADING', created_at=time.time(), candidates=[])
            log.info('WEWIN_MEDIA resolve_success browser_load generation=%d', gen)
            self._browser(gen, 'select', resolved['youtube_video_id'])
            if action == 'select':
                self._update(gen, state='PAUSED', stream_state='IDLE')
                return
        elif not self.current.get('video_id'):
            raise MediaError('no_media_context', 'Chưa có video để phát tiếp.')

        config = self.control.config
        if config.get('system_mix_consent') is not True or config.get('local_route_confirmed') is not True:
            raise MediaError('capture_consent_required','Chưa xác nhận nguồn system mix và routing.')
        matches = [d for d in self.capture_devices() if d['name'] == config.get('capture_name')]
        if len(matches) != 1:
            raise MediaError('capture_endpoint_changed', 'Chọn lại đúng WASAPI loopback trong cấu hình.')
        self._guard(gen)
        endpoint_idx = body.get('endpoint')
        if endpoint_idx is None or endpoint_idx < 0:
            endpoint_idx = matches[0]['index']
        prepared = self.stream.start(endpoint=endpoint_idx, peer_ipv4=device['ip'],
            allow_system_mix=config.get('system_mix_consent', False) is True,
            local_output_routed_away=config.get('local_route_confirmed', False) is True)
        self._guard(gen)
        self.control.send('start', gen, prepared['descriptor'])
        self._update(gen, stream_state='CONNECTING')
        log.info('WEWIN_MEDIA stream_start_requested generation=%d', gen)

        # Wait for ESP32 HELLO & WASAPI capture ready before commanding browser play
        until = time.monotonic() + 40  # Includes native existing 30s pre-play AI handoff, not duration.
        while time.monotonic() < until:
            self._guard(gen)
            self.stream.heartbeat()
            status = self.stream.status()
            device_status = self.control.device()
            if device_status.get('command_error', 'none') != 'none':
                raise MediaError('device_command_rejected', 'Thiết bị từ chối yêu cầu stream.')
            if not self._browser_status().get('connected'):
                raise MediaError('browser_disconnected', 'Player mất kết nối.')
            self._update(gen, stream_state=status.get('state', 'ERROR'))
            if status.get('state') == 'PLAYING':
                break
            if status.get('state') == 'ERROR':
                raise MediaError('stream_error', 'Live stream báo lỗi; chưa có Hardware PASS.')
            time.sleep(.05)
        else:
            raise MediaError('stream_start_timeout', 'Không nhận được HELLO từ thiết bị.')

        # ESP32 connected and WASAPI capture ready: now command browser playback!
        self._browser(gen, 'resume' if action == 'resume' else 'play')
        log.info('WEWIN_MEDIA browser_playing generation=%d', gen)

        # Wait for audio output confirmation
        until_out = time.monotonic() + 15
        while time.monotonic() < until_out:
            self._guard(gen)
            self.stream.heartbeat()
            status = self.stream.status()
            if not self._browser_status().get('connected'):
                raise MediaError('browser_disconnected', 'Player mất kết nối.')
            self._update(gen, stream_state=status.get('state', 'ERROR'))
            if status.get('state') == 'PLAYING' and (status.get('device_report') or {}).get('output_frames', 0) > 0:
                self._update(gen, state='PLAYING')
                log.info('WEWIN_MEDIA stream_playing generation=%d', gen)
                return
            if status.get('state') == 'ERROR':
                raise MediaError('stream_error', 'Live stream báo lỗi; chưa có Hardware PASS.')
            time.sleep(.05)
        if status.get('state') == 'PLAYING':
            self._update(gen, state='PLAYING')
            return
        raise MediaError('stream_start_timeout', 'Không có ACK output từ thiết bị.')

    def _execute_asset(self, gen, body):
        from .asset_service import get_assets
        from src.streaming.asset_source import AssetSource
        action = body['action']
        offset = 0
        if action in ('pause', 'interrupt', 'resume'):
            status = self.stream.status()
            offset = self.current.get('base_offset_ms', 0) + (status.get('device_report') or {}).get('position_ms', 0)
            offset = self.current.get('position_ms', offset)
        self._retire(gen)
        if action in ('pause','interrupt','stop','ended'):
            self._update(gen, state='PAUSED' if action in ('pause','interrupt') else 'IDLE', position_ms=offset)
            return
        queue = body.get('queue') or self.current.get('queue', [])
        vid = body.get('video_id')
        if action not in ('play', 'replace', 'select'):
            vid = vid or self.current.get('video_id')
        if action == 'next':
            if vid not in queue or queue.index(vid)+1 >= len(queue):
                raise MediaError('no_next_lesson','Không có bài tiếp theo.')
            vid=queue[queue.index(vid)+1]
        if not vid and body.get('query'):
            resolved=self.resolver.resolve(body['query'],'wewin',self.status())
            if resolved.get('status')!='resolved':
                raise MediaError('ambiguous_lesson','Hãy chọn tên bài rõ hơn.')
            vid=resolved['youtube_video_id']
        if not vid:
            raise MediaError('no_media_context','Hãy chọn bài học.')
        video=self.youtube.video(vid)
        if video['channel_id'] != self.youtube.resolve_channel()['channel_id']:
            raise MediaError('wrong_channel','Bài không thuộc WeWIN Education.')
        if self.current.get('source_kind') != 'owned_asset':
            previous=self._browser_status()
            if previous.get('connected') and previous.get('selected_video'):
                self._browser(gen,'stop')
        record,path=get_assets().for_video(vid)
        self._guard(gen)
        device=self.control.device()
        prepared=self.stream.start(endpoint=0,peer_ipv4=device['ip'],
            source_factory=lambda callback:AssetSource(path,callback,offset))
        self.control.send('start',gen,prepared['descriptor'])
        self._update(gen,source_kind='owned_asset',asset_id=record['asset_id'],video_id=vid,title=video['title'],queue=queue,
            base_offset_ms=offset,position_ms=offset,position_kind='estimated_rendered',state='LOADING')
        until=time.monotonic()+40
        while time.monotonic()<until:
            self._guard(gen);self.stream.heartbeat()
            state=self.stream.status()
            if state.get('state')=='PLAYING' and (state.get('device_report') or {}).get('output_frames',0)>0:
                self._update(gen,state='PLAYING',stream_state='PLAYING');return
            if state.get('state')=='ERROR':raise MediaError('stream_error','Không phát được bài.')
            time.sleep(.05)
        raise MediaError('stream_start_timeout','Thiết bị chưa xác nhận output.')

    def _error(self, gen, code):
        if gen != self.generation:
            return
        self.stream.stop()
        try:
            self.control.send('stop', gen)
        except ValueError:
            pass
        try:
            if self._browser_status().get('connected') and self._browser_status().get('selected_video'):
                self._browser(gen, 'stop' if self.current.get('requested_action') == 'stop' else 'pause')
        except Exception:
            pass
        try:
            self._update(gen, state='ERROR', last_error=code, stream_state=self.stream.status().get('state'))
        except MediaError:
            return  # A concurrent newer intent owns the state now.
        log.warning('WEWIN_MEDIA error generation=%d code=%s', gen, code)

    def _monitor(self):
        if self.current['state'] != 'PLAYING':
            return
        gen = self.generation
        if self.current.get('source_kind') == 'owned_asset':
            from .asset_service import get_assets
            if not any(r['asset_id']==self.current.get('asset_id') and r.get('mapping_verified') and r.get('youtube_video_id')==self.current.get('video_id') and r['rights_status']=='approved' for r in get_assets().inventory()):
                self._error(gen,'rights_revoked');return
            self.stream.heartbeat()
            live = self.stream.status()
            report = live.get('device_report') or {}
            self._update(gen, position_ms=self.current.get('base_offset_ms', 0) + report.get('position_ms', 0), stream_state=live.get('state'))
            if live.get('state') == 'IDLE':
                self._update(gen, state='ENDED')
            elif live.get('state') == 'ERROR':
                self._error(gen, live.get('error') or 'stream_error')
            return
        try:
            device = self.control.device()
            if device['ip'] != self.current.get('device_ip') or device['device_id'] != self.current.get('device_id'):
                raise ValueError('device_address_changed')
            browser = self._browser_status()
            if not browser.get('connected'):
                raise ValueError('browser_disconnected')
            if browser.get('state') == 'ENDED':
                self.submit({'action': 'ended', 'request_id': uuid4().hex})
            elif browser.get('state') == 'PAUSED':
                self.submit({'action': 'pause', 'request_id': uuid4().hex})
            elif browser.get('state') in ('ERROR', 'AUTOPLAY_BLOCKED'):
                raise ValueError('browser_error')
            else:
                self.stream.heartbeat()
                live = self.stream.status()
                self._update(gen, stream_state=live.get('state'), browser_state=browser.get('state'))
                if live.get('state') == 'ERROR':
                    raise ValueError('stream_error')
        except ValueError as error:
            self._error(gen, str(error) if str(error) in ('browser_disconnected', 'browser_error', 'stream_error', 'device_address_changed') else 'device_unavailable')

    def _run(self):
        while not self.closed.is_set():
            with self.lock:
                job = self.jobs.popleft() if self.jobs else None
            if job:
                gen, body, caller = job
                try:
                    self._execute(gen, body, caller)
                except MediaError as error:
                    if error.code != 'obsolete_generation':
                        self._error(gen, error.code)
                except ValueError as error:
                    self._error(gen, 'device_unavailable' if str(error) == 'device_unavailable' else 'device_capture_or_transport_failure')
                except Exception:
                    self._error(gen, 'device_capture_or_transport_failure')
            else:
                try:
                    self._monitor()
                except MediaError:
                    pass  # New generation may supersede monitor between its snapshots.
                except Exception:
                    self._error(self.generation, 'media_monitor_failure')
                self.closed.wait(.1)


_session = None
_session_lock = threading.RLock()
def get_session():
    global _session
    with _session_lock:
        if _session is None:
            from .registry import get_registry
            from .routes import youtube
            from src.streaming.service import get_service
            from src.streaming.capture import loopback_devices
            from .device_control import get_control
            _session = MediaSession(get_registry(), youtube, get_service(), get_control(), loopback_devices)
            get_control().handler = lambda body, device: _session.submit({**body, 'owned_audio': True}, device)
            get_control().status_provider = _session.status
    return _session
