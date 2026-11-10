import React, { useEffect, useRef, useState, useCallback } from 'react';
import { Play, Square, RefreshCw, Volume2, VolumeX, CheckCircle2, AlertCircle, Radio, Sparkles, AlertTriangle } from 'lucide-react';
import { streamRequest, type StreamStatus, type LoopbackDevice } from '../services/stream';
import { voiceMedia } from '../services/voiceMedia';
import { useAutoPlayer } from './useAutoPlayer';

const SAMPLE_VIDEO_URL = 'https://www.youtube.com/watch?v=2_IweGD2uM4';
const SAMPLE_VIDEO_ID = '2_IweGD2uM4';

export function extractYouTubeId(url: string): string | null {
  if (!url) return null;
  const trimmed = url.trim();
  if (/^[A-Za-z0-9_-]{11}$/.test(trimmed)) return trimmed;
  const patterns = [
    /(?:youtu\.be\/|youtube\.com\/(?:embed\/|v\/|watch\?v=|watch\?.+&v=|shorts\/))([A-Za-z0-9_-]{11})/i,
    /^[A-Za-z0-9_-]{11}$/
  ];
  for (const p of patterns) {
    const match = trimmed.match(p);
    if (match && match[1]) return match[1];
  }
  return null;
}

const STATE_LABELS: Record<string, string> = {
  IDLE: 'Sẵn sàng',
  PREPARING: 'Đang chuẩn bị...',
  CONNECTING: 'Đang kết nối Robot...',
  CAPTURING: 'Đang nhận âm thanh Windows...',
  PLAYING: 'Đang phát qua Robot',
  STOPPING: 'Đang dừng...',
  ERROR: 'Có lỗi'
};

export interface DirectSpeakerProps {
  authenticated: boolean;
  autoPlayer: ReturnType<typeof useAutoPlayer>;
}

export function DirectSpeaker({ authenticated, autoPlayer }: DirectSpeakerProps) {
  const player = autoPlayer;

  const [url, setUrl] = useState(SAMPLE_VIDEO_URL);
  const [videoId, setVideoId] = useState(SAMPLE_VIDEO_ID);
  const [uiState, setUiState] = useState<'IDLE' | 'PREPARING' | 'CONNECTING' | 'CAPTURING' | 'PLAYING' | 'STOPPING' | 'ERROR'>('IDLE');
  const [statusText, setStatusText] = useState('Sẵn sàng');
  const [errorMessage, setErrorMessage] = useState('');
  const [autoplayBlocked, setAutoplayBlocked] = useState(false);

  // Hardware & devices
  const [devices, setDevices] = useState<LoopbackDevice[]>([]);
  const [selectedEndpoint, setSelectedEndpoint] = useState<number>(-1);
  const [autoDetectedName, setAutoDetectedName] = useState<string>('Realtek');
  const [robotOnline, setRobotOnline] = useState<boolean>(false);
  const [robotIp, setRobotIp] = useState<string>('');
  const [telemetry, setTelemetry] = useState<StreamStatus | null>(null);

  // Settings
  const [consent, setConsent] = useState<boolean>(() => localStorage.getItem('wewin_audio_consent') !== 'false');
  const [routed, setRouted] = useState<boolean>(() => localStorage.getItem('wewin_audio_routed') !== 'false');

  // Volume & Mute states
  const [robotVolume, setRobotVolume] = useState<number>(70);
  const [robotMuted, setRobotMuted] = useState<boolean>(false);
  const [laptopMuted, setLaptopMuted] = useState<boolean>(false);
  const [laptopNotice, setLaptopNotice] = useState<string>('');
  const volumeDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Save settings
  useEffect(() => {
    localStorage.setItem('wewin_audio_consent', String(consent));
    localStorage.setItem('wewin_audio_routed', String(routed));
  }, [consent, routed]);

  // Sync with autoPlayer selected video (e.g. from Voice Commands)
  useEffect(() => {
    if (player?.status?.selected_video?.video_id) {
      const vid = player.status.selected_video.video_id;
      setVideoId(vid);
      setUrl(player.status.selected_video.url || `https://www.youtube.com/watch?v=${vid}`);
    }
  }, [player?.status?.selected_video]);

  // Watch for autoplay blocked
  useEffect(() => {
    if (player?.status?.state === 'AUTOPLAY_BLOCKED') {
      setAutoplayBlocked(true);
    }
  }, [player?.status?.state]);

  // Load WASAPI devices
  const refreshDevices = useCallback(async () => {
    if (!authenticated) return;
    try {
      const res = await streamRequest<{ devices: LoopbackDevice[] }>('devices');
      if (res?.devices) {
        setDevices(res.devices);
        const def = res.devices.find(d => d.is_default);
        if (def) {
          setAutoDetectedName(def.clean_name || def.name.replace(' [Loopback]', ''));
          if (selectedEndpoint < 0) setSelectedEndpoint(def.index);
        } else if (res.devices.length > 0) {
          setAutoDetectedName(res.devices[0].clean_name || res.devices[0].name.replace(' [Loopback]', ''));
          if (selectedEndpoint < 0) setSelectedEndpoint(res.devices[0].index);
        }
      }
    } catch {
      // Ignore initial devices error if not ready
    }
  }, [authenticated, selectedEndpoint]);

  useEffect(() => {
    void refreshDevices();
  }, [refreshDevices]);

  // Sync Video ID when input changes
  const handleUrlChange = (newUrl: string) => {
    setUrl(newUrl);
    const parsed = extractYouTubeId(newUrl);
    if (parsed) {
      setVideoId(parsed);
      setErrorMessage('');
    }
  };

  // Poll direct/status & send heartbeats
  useEffect(() => {
    if (!authenticated) return;
    let live = true;

    const poll = async () => {
      try {
        const s = await streamRequest<StreamStatus>('direct/status');
        if (!live) return;
        setTelemetry(s);

        // Robot presence check
        const isOnline = Boolean(s.device?.online);
        setRobotOnline(isOnline);
        setRobotIp(s.device?.ip || '');

        if (s.loopback?.clean_name) {
          setAutoDetectedName(s.loopback.clean_name);
        }

        if (typeof s.robot_volume === 'number' && !volumeDebounceRef.current) {
          setRobotVolume(s.robot_volume);
        }
        if (typeof s.robot_muted === 'boolean') {
          setRobotMuted(s.robot_muted);
        }

        // Active stream management
        if (s.transport_active) {
          // Send heartbeat
          void streamRequest('heartbeat', {});

          if (s.hello) {
            setUiState('PLAYING');
            setStatusText(STATE_LABELS['PLAYING']);
          } else {
            setUiState('CONNECTING');
            setStatusText('Đang kết nối Robot...');
          }
        } else {
          // Check player status
          const playerState = player?.status?.state;
          if (playerState === 'VIDEO_SELECTED' || playerState === 'BUFFERING') {
            setUiState('CONNECTING');
            setStatusText('Đang kết nối Robot...');
          } else if (playerState === 'PLAYING') {
            setUiState('PLAYING');
            setStatusText(STATE_LABELS['PLAYING']);
          } else if (playerState === 'PAUSED') {
            setUiState('IDLE');
            setStatusText('Đã tạm dừng');
          } else {
            if (uiState === 'PLAYING' || uiState === 'CAPTURING' || uiState === 'STOPPING') {
              setUiState('IDLE');
              setStatusText(STATE_LABELS['IDLE']);
            }
          }
        }
      } catch {
        // Polling error
      }
    };

    void poll();
    const timer = setInterval(() => void poll(), 1000);
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, [authenticated, uiState, player?.status?.state]);

  const sendVolumeCommand = useCallback(async (vol: number, action: string = 'set') => {
    try {
      await streamRequest('direct/volume', { volume: vol, action });
    } catch {
      // Ignore network hiccup
    }
  }, []);

  const handleVolumeSliderChange = (newVal: number) => {
    setRobotVolume(newVal);
    if (newVal > 0 && robotMuted) setRobotMuted(false);
    if (volumeDebounceRef.current) clearTimeout(volumeDebounceRef.current);
    volumeDebounceRef.current = setTimeout(() => {
      volumeDebounceRef.current = null;
      void sendVolumeCommand(newVal, 'set');
    }, 80);
  };

  const handleAdjustRobotVolume = (delta: number) => {
    const next = Math.max(0, Math.min(100, robotVolume + delta));
    setRobotVolume(next);
    if (next > 0 && robotMuted) setRobotMuted(false);
    if (volumeDebounceRef.current) clearTimeout(volumeDebounceRef.current);
    volumeDebounceRef.current = setTimeout(() => {
      volumeDebounceRef.current = null;
      void sendVolumeCommand(next, 'set');
    }, 80);
  };

  const handleToggleRobotMute = async () => {
    const nextMuted = !robotMuted;
    setRobotMuted(nextMuted);
    await sendVolumeCommand(robotVolume, nextMuted ? 'mute' : 'unmute');
  };

  const handleToggleLaptopMute = () => {
    const secondary = devices.find(d => !d.is_default);
    if (!laptopMuted) {
      if (secondary) {
        setLaptopMuted(true);
        setSelectedEndpoint(secondary.index);
        setLaptopNotice(`Đã chuyển ngõ thu âm thanh sang: ${secondary.clean_name || secondary.name}. Để loa laptop hoàn toàn im tiếng: Hãy vào Windows Settings > Sound > App volume và chọn ngõ ra của trình duyệt (Chrome/Edge) sang thiết bị này.`);
      } else {
        setLaptopNotice('Windows đang dùng chung một ngõ phát vật lý duy nhất (Realtek). Để tắt tiếng loa máy tính mà Robot vẫn phát, cần kết nối thêm màn hình phụ (HDMI/DisplayPort) hoặc cài driver Virtual Audio Cable (VB-CABLE) để tách riêng ngõ phát.');
      }
    } else {
      setLaptopMuted(false);
      const def = devices.find(d => d.is_default);
      if (def) setSelectedEndpoint(def.index);
      setLaptopNotice('Đã khôi phục ngõ phát âm thanh mặc định.');
    }
    setTimeout(() => setLaptopNotice(''), 10000);
  };

  // Unified Playback Orchestration: startVideoOnRobot
  const handleStart = async (overrideVideoId?: string) => {
    const targetId = overrideVideoId || videoId || extractYouTubeId(url);
    if (!targetId) {
      setErrorMessage('Vui lòng dán link video YouTube hợp lệ');
      return;
    }

    setErrorMessage('');
    setAutoplayBlocked(false);
    setUiState('PREPARING');
    setStatusText('Đang chuẩn bị...');

    try {
      setUiState('CONNECTING');
      setStatusText('Đang kết nối Robot...');
      // Unified media action call to backend
      await voiceMedia('action', {
        action: 'play',
        video_id: targetId,
        request_id: crypto.randomUUID(),
        endpoint: selectedEndpoint >= 0 ? selectedEndpoint : undefined
      });
      await player?.refresh();
    } catch (err: unknown) {
      // Fallback: direct/start if voiceMedia fails
      try {
        await streamRequest('direct/start', {
          endpoint: selectedEndpoint,
          peer_ipv4: '',
          port: 8766,
          allow_system_mix: consent,
          local_output_routed_away: routed
        });
      } catch (directErr: unknown) {
        setUiState('ERROR');
        const msg = err instanceof Error ? err.message : 'Không thể khởi động Direct Audio';
        setErrorMessage(msg);
        setStatusText('Có lỗi xảy ra');
      }
    }
  };

  // Stop Direct Audio
  const handleStop = async () => {
    setUiState('STOPPING');
    setStatusText('Đang dừng phát...');

    try {
      await voiceMedia('action', {
        action: 'stop',
        request_id: crypto.randomUUID()
      });
    } catch {
      try {
        await streamRequest('direct/stop', {});
      } catch {}
    } finally {
      await player?.refresh();
      setUiState('IDLE');
      setStatusText(STATE_LABELS['IDLE']);
      setAutoplayBlocked(false);
    }
  };

  // Sample video click
  const handleSampleClick = () => {
    setUrl(SAMPLE_VIDEO_URL);
    setVideoId(SAMPLE_VIDEO_ID);
    void handleStart(SAMPLE_VIDEO_ID);
  };

  // Unlock browser autoplay policy
  const handleUnlockAutoplay = async () => {
    setAutoplayBlocked(false);
    try {
      const iframe = document.getElementById('wewin-youtube-iframe') as HTMLIFrameElement;
      iframe?.contentWindow?.postMessage(JSON.stringify({ event: 'command', func: 'playVideo' }), '*');
    } catch {}
    try {
      await voiceMedia('action', {
        action: 'play',
        video_id: videoId || SAMPLE_VIDEO_ID,
        request_id: crypto.randomUUID()
      });
    } catch {}
  };

  const isBusy = uiState === 'PREPARING' || uiState === 'CONNECTING';
  const isStreaming = uiState === 'PLAYING' || uiState === 'CAPTURING' || uiState === 'STOPPING';
  const isPlaying = uiState === 'PLAYING' || uiState === 'CAPTURING';

  return (
    <div className="space-y-6">
      {/* CARD CHÍNH: Phát YouTube qua loa WeWIN */}
      <section className="bg-white border-2 border-blue-500/30 rounded-3xl p-6 sm:p-8 shadow-xl shadow-blue-500/5 space-y-6">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 pb-4">
          <div>
            <h2 className="text-xl sm:text-2xl font-black text-slate-900 tracking-tight flex items-center gap-2.5">
              <Radio className="text-blue-600 animate-pulse" size={24} />
              Phát YouTube qua loa WeWIN
            </h2>
            <p className="text-slate-500 text-sm mt-1">
              Âm thanh từ video YouTube trên máy tính được truyền realtime qua Wi-Fi tới loa Robot WeWIN.
            </p>
          </div>
          <span
            className={`text-xs font-bold px-3 py-1.5 rounded-full flex items-center gap-1.5 ${
              isPlaying
                ? 'bg-emerald-100 text-emerald-800 animate-pulse'
                : isBusy
                ? 'bg-amber-100 text-amber-800'
                : 'bg-slate-100 text-slate-700'
            }`}
          >
            <span
              className={`w-2 h-2 rounded-full ${
                isPlaying ? 'bg-emerald-500' : isBusy ? 'bg-amber-500' : 'bg-slate-400'
              }`}
            />
            {statusText}
          </span>
        </div>

        {/* Input Link YouTube */}
        <div className="space-y-2">
          <label htmlFor="youtube-url-input" className="block text-xs font-bold uppercase tracking-wider text-slate-700">
            Link YouTube
          </label>
          <div className="flex flex-col sm:flex-row gap-2">
            <input
              id="youtube-url-input"
              type="text"
              value={url}
              onChange={e => handleUrlChange(e.target.value)}
              placeholder="https://www.youtube.com/watch?v=..."
              disabled={isPlaying || isBusy}
              className="flex-1 bg-slate-50 border border-slate-300 rounded-xl px-4 py-3 text-sm text-slate-800 focus:bg-white focus:outline-none focus:ring-2 focus:ring-blue-500 transition-all font-mono"
            />
            <button
              type="button"
              onClick={handleSampleClick}
              disabled={isBusy}
              className="inline-flex items-center justify-center gap-2 bg-indigo-50 hover:bg-indigo-100 text-indigo-700 font-bold px-4 py-3 rounded-xl text-sm transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed shrink-0 border border-indigo-200"
            >
              <Sparkles size={16} />
              Phát video mẫu
            </button>
          </div>
        </div>

        {/* YouTube Embedded Player */}
        <div className="relative aspect-video w-full rounded-2xl overflow-hidden bg-slate-950 shadow-inner border border-slate-200">
          <div ref={player.host} className="absolute inset-0 w-full h-full" />
          {!authenticated && (
            <iframe
              title="YouTube Media Player Preview"
              className="absolute inset-0 w-full h-full border-0"
              src={`https://www.youtube.com/embed/${videoId || SAMPLE_VIDEO_ID}?enablejsapi=1&playsinline=1`}
              allow="autoplay; encrypted-media; picture-in-picture"
              allowFullScreen
            />
          )}
          {autoplayBlocked && (
            <div className="absolute inset-0 bg-slate-900/85 backdrop-blur-xs flex flex-col items-center justify-center p-6 text-white text-center space-y-3 z-10">
              <AlertTriangle className="text-amber-400" size={36} />
              <p className="text-sm font-semibold max-w-md">
                Trình duyệt cần quyền tự phát. Nhấn một lần để cho phép điều khiển video bằng giọng nói.
              </p>
              <button
                type="button"
                onClick={() => void handleUnlockAutoplay()}
                className="bg-blue-600 hover:bg-blue-700 text-white font-bold px-6 py-3 rounded-xl shadow-lg cursor-pointer flex items-center gap-2"
              >
                <Play size={18} />
                Cho phép tự động phát
              </button>
            </div>
          )}
        </div>

        {/* Robot & Windows Audio Status Bar */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 bg-slate-50 border border-slate-200 rounded-2xl p-4 text-sm">
          {/* Robot WeWIN */}
          <div className="flex items-center gap-3">
            <div
              className={`w-3.5 h-3.5 rounded-full shrink-0 ${
                robotOnline ? 'bg-emerald-500 shadow-sm shadow-emerald-500/50' : 'bg-slate-300'
              }`}
            />
            <div>
              <p className="font-bold text-slate-800">Robot WeWIN (Direct Wi-Fi Audio)</p>
              <p className="text-xs text-slate-500">
                {robotOnline ? (
                  <span className="text-emerald-700 font-semibold">● Đã kết nối Wi-Fi Direct {robotIp ? `(${robotIp})` : ''}</span>
                ) : (
                  <span className="text-slate-500">○ Direct Audio tắt · Video phát qua loa máy tính, Lily phát qua loa DODO</span>
                )}
              </p>
            </div>
          </div>

          {/* Âm thanh Windows */}
          <div className="flex items-center gap-3">
            <CheckCircle2 className="text-blue-600 shrink-0" size={18} />
            <div>
              <p className="font-bold text-slate-800">Âm thanh Windows</p>
              <p className="text-xs text-slate-500">
                ✓ Đã phát hiện: <span className="font-semibold text-slate-700">{autoDetectedName}</span>
              </p>
            </div>
          </div>
        </div>

        {/* Audio Controls: Laptop Audio & Robot Volume */}
        <div className="bg-slate-50 border border-slate-200 rounded-2xl p-4 sm:p-5 space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200/60 pb-3">
            <h3 className="font-bold text-slate-800 text-sm flex items-center gap-2">
              <Volume2 className="text-blue-600" size={18} />
              Điều khiển âm thanh
            </h3>
            {/* Âm thanh máy tính: Tắt / Bật */}
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={handleToggleLaptopMute}
                className={`text-xs font-bold px-3 py-1.5 rounded-xl border transition-colors flex items-center gap-1.5 cursor-pointer ${
                  laptopMuted
                    ? 'bg-amber-50 border-amber-300 text-amber-800'
                    : 'bg-white border-slate-300 text-slate-700 hover:bg-slate-100'
                }`}
              >
                {laptopMuted ? <VolumeX size={14} /> : <Volume2 size={14} />}
                {laptopMuted ? 'Bật tiếng máy tính' : 'Tắt tiếng máy tính'}
              </button>
            </div>
          </div>

          {laptopNotice && (
            <p className="text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded-xl p-2.5">
              {laptopNotice}
            </p>
          )}

          {/* Âm lượng Robot WeWIN */}
          <div className="space-y-2">
            <div className="flex items-center justify-between text-xs font-semibold text-slate-700">
              <span className="flex items-center gap-1.5">
                Loa Robot WeWIN:
                {robotMuted && <span className="text-red-600 font-bold">(Đang tắt tiếng)</span>}
              </span>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={handleToggleRobotMute}
                  disabled={!robotOnline}
                  className={`text-xs font-bold px-2.5 py-1 rounded-lg border transition-colors flex items-center gap-1 cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed ${
                    robotMuted
                      ? 'bg-red-50 border-red-300 text-red-700 hover:bg-red-100'
                      : 'bg-white border-slate-300 text-slate-700 hover:bg-slate-100'
                  }`}
                >
                  {robotMuted ? <Volume2 size={13} /> : <VolumeX size={13} />}
                  {robotMuted ? '🔊 Bật tiếng Robot' : '🔇 Tắt tiếng Robot'}
                </button>
                <span className="font-mono text-slate-900 font-bold w-10 text-right">{robotVolume}%</span>
              </div>
            </div>

            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => handleAdjustRobotVolume(-5)}
                disabled={!robotOnline || robotVolume <= 0}
                className="w-9 h-9 rounded-xl bg-white border border-slate-300 text-slate-700 font-bold hover:bg-slate-100 disabled:opacity-40 disabled:cursor-not-allowed flex items-center justify-center cursor-pointer text-sm shrink-0"
                aria-label="Giảm âm lượng Robot 5%"
              >
                −
              </button>
              <input
                type="range"
                min="0"
                max="100"
                step="1"
                value={robotVolume}
                onChange={e => handleVolumeSliderChange(Number(e.target.value))}
                disabled={!robotOnline}
                className="flex-1 accent-blue-600 h-2 bg-slate-200 rounded-lg cursor-pointer disabled:cursor-not-allowed"
                aria-label="Âm lượng loa Robot WeWIN"
              />
              <button
                type="button"
                onClick={() => handleAdjustRobotVolume(5)}
                disabled={!robotOnline || robotVolume >= 100}
                className="w-9 h-9 rounded-xl bg-white border border-slate-300 text-slate-700 font-bold hover:bg-slate-100 disabled:opacity-40 disabled:cursor-not-allowed flex items-center justify-center cursor-pointer text-sm shrink-0"
                aria-label="Tăng âm lượng Robot 5%"
              >
                +
              </button>
            </div>
          </div>
        </div>

        {/* Khi đang chạy: Realtime Streaming Status */}
        {isPlaying && (
          <div className="rounded-2xl bg-emerald-50 border border-emerald-200 p-4 space-y-2">
            <div className="flex flex-wrap items-center justify-between gap-2 text-xs font-semibold text-emerald-800">
              <span className="flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full bg-emerald-500 animate-ping" />
                ● Video đang phát
              </span>
              <span>● Robot đang nhận âm thanh</span>
              <span>
                {telemetry?.packets_sent ?? 0} gói gửi · {telemetry?.device_report?.output_frames ?? 0} khung phát
              </span>
            </div>
          </div>
        )}

        {/* Error message */}
        {errorMessage && (
          <div className="rounded-2xl bg-red-50 border border-red-200 p-4 flex items-start gap-3 text-red-800 text-sm">
            <AlertCircle size={20} className="shrink-0 text-red-600 mt-0.5" />
            <div className="flex-1">
              <p className="font-bold">Không thể phát qua loa WeWIN</p>
              <p className="text-xs text-red-700 mt-0.5">{errorMessage}</p>
            </div>
            <button
              type="button"
              onClick={() => void handleStart()}
              className="text-xs font-bold bg-red-100 hover:bg-red-200 text-red-800 px-3 py-1.5 rounded-lg cursor-pointer transition-colors"
            >
              Thử lại
            </button>
          </div>
        )}

        {/* Action Buttons: START vs STOP */}
        <div className="pt-2">
          {!isStreaming ? (
            <button
              type="button"
              onClick={() => void handleStart()}
              disabled={isBusy}
              className="w-full bg-blue-600 hover:bg-blue-700 text-white font-bold py-4 px-6 rounded-2xl shadow-lg shadow-blue-500/25 text-base sm:text-lg transition-all flex items-center justify-center gap-3 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed active:scale-[0.99]"
            >
              {isBusy ? (
                <>
                  <RefreshCw size={20} className="animate-spin" />
                  {statusText}
                </>
              ) : (
                <>
                  <Play size={20} className="fill-current" />
                  ▶ Phát video qua loa WeWIN
                </>
              )}
            </button>
          ) : (
            <button
              type="button"
              onClick={() => void handleStop()}
              disabled={uiState === 'STOPPING'}
              className="w-full bg-red-600 hover:bg-red-700 text-white font-bold py-4 px-6 rounded-2xl shadow-lg shadow-red-500/25 text-base sm:text-lg transition-all flex items-center justify-center gap-3 cursor-pointer active:scale-[0.99]"
            >
              {uiState === 'STOPPING' ? (
                <>
                  <RefreshCw size={20} className="animate-spin" />
                  Đang dừng phát...
                </>
              ) : (
                <>
                  <Square size={20} className="fill-current" />
                  ■ Dừng phát
                </>
              )}
            </button>
          )}
        </div>

        {/* Collapsible: Tùy chọn nâng cao */}
        <details className="group border border-slate-200 rounded-2xl overflow-hidden bg-slate-50/50">
          <summary className="p-4 text-xs font-bold text-slate-700 uppercase tracking-wider cursor-pointer select-none hover:bg-slate-100/70 transition-colors flex items-center justify-between">
            <span>Tùy chọn nâng cao</span>
            <span className="text-slate-400 group-open:rotate-180 transition-transform">▼</span>
          </summary>
          <div className="p-4 pt-0 space-y-4 border-t border-slate-200/50 text-xs text-slate-600">
            <div>
              <label htmlFor="loopback-device-select" className="block font-bold text-slate-700 mb-1">
                Chọn ngõ âm thanh Windows (WASAPI Loopback):
              </label>
              <select
                id="loopback-device-select"
                value={selectedEndpoint}
                onChange={e => setSelectedEndpoint(Number(e.target.value))}
                disabled={isPlaying}
                className="w-full bg-white border border-slate-300 rounded-xl p-2.5 text-xs text-slate-800"
              >
                <option value={-1}>Tự động chọn (Mặc định Windows: {autoDetectedName})</option>
                {devices.map(d => (
                  <option key={d.index} value={d.index}>
                    {d.clean_name || d.name} {d.is_default ? '★ (Mặc định Windows)' : ''}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-2">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={consent}
                  onChange={e => setConsent(e.target.checked)}
                  disabled={isPlaying}
                  className="rounded border-slate-300 text-blue-600 accent-blue-600"
                />
                <span>Cho phép thu âm thanh đang phát trên Windows (không thu microphone).</span>
              </label>
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={routed}
                  onChange={e => setRouted(e.target.checked)}
                  disabled={isPlaying}
                  className="rounded border-slate-300 text-blue-600 accent-blue-600"
                />
                <span>Xác nhận không mute YouTube trên trình duyệt.</span>
              </label>
            </div>
          </div>
        </details>

        {/* Collapsible: Chi tiết kỹ thuật */}
        <details className="group border border-slate-200 rounded-2xl overflow-hidden bg-slate-50/50">
          <summary className="p-4 text-xs font-bold text-slate-700 uppercase tracking-wider cursor-pointer select-none hover:bg-slate-100/70 transition-colors flex items-center justify-between">
            <span>Chi tiết kỹ thuật (Telemetry)</span>
            <span className="text-slate-400 group-open:rotate-180 transition-transform">▼</span>
          </summary>
          <div className="p-4 pt-0 border-t border-slate-200/50 text-xs text-slate-600 space-y-3 font-mono">
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 pt-3">
              <div className="bg-white p-2.5 rounded-lg border border-slate-200">
                <span className="text-[10px] text-slate-400 block">Gói đã gửi</span>
                <span className="font-bold text-slate-800 text-sm">{telemetry?.packets_sent ?? 0}</span>
              </div>
              <div className="bg-white p-2.5 rounded-lg border border-slate-200">
                <span className="text-[10px] text-slate-400 block">ESP32 đã nhận</span>
                <span className="font-bold text-slate-800 text-sm">{telemetry?.device_report?.packets_received ?? 0}</span>
              </div>
              <div className="bg-white p-2.5 rounded-lg border border-slate-200">
                <span className="text-[10px] text-slate-400 block">Khung giải mã</span>
                <span className="font-bold text-slate-800 text-sm">{telemetry?.device_report?.output_frames ?? 0}</span>
              </div>
              <div className="bg-white p-2.5 rounded-lg border border-slate-200">
                <span className="text-[10px] text-slate-400 block">Buffer Depth</span>
                <span className="font-bold text-slate-800 text-sm">{telemetry?.device_report?.buffer_depth ?? 0}</span>
              </div>
            </div>
            <pre className="bg-slate-900 text-slate-200 p-3 rounded-xl overflow-x-auto text-[11px] max-h-48">
              {JSON.stringify(
                {
                  state: telemetry?.state,
                  hello: telemetry?.hello,
                  session_id: telemetry?.session_id,
                  generation: telemetry?.generation,
                  packets_sent: telemetry?.packets_sent,
                  packets_dropped: telemetry?.packets_dropped,
                  capture_frames: telemetry?.capture_frames,
                  device: telemetry?.device,
                  device_report: telemetry?.device_report,
                  error: telemetry?.error
                },
                null,
                2
              )}
            </pre>
          </div>
        </details>
      </section>
    </div>
  );
}
