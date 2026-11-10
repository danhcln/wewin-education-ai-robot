import {EducationPanel} from '../media/EducationPanel';
import {DirectSpeaker} from '../media/DirectSpeaker';
import React,{useEffect,useState} from 'react';
import {Play,Pause,Square,Search,Volume2,RefreshCw,Video as VideoIcon,ShieldCheck,ExternalLink} from 'lucide-react';
import {useAuth} from '../context/AuthContext';
import {mediaRequest} from '../services/media';
import type {MediaConfig,Video} from '../services/media';
import {autoMedia} from '../services/autoMedia';
import {useAutoPlayer} from '../media/useAutoPlayer';
import {WifiSpeaker} from '../media/WifiSpeaker';
import {VoiceMediaPanel} from '../media/VoiceMediaPanel';
import {voiceMedia} from '../services/voiceMedia';
const labels:Record<string,string>={PLAYER_DISCONNECTED:'Chưa có thiết bị phát đang kết nối',PLAYER_READY:'YouTube Player sẵn sàng',VIDEO_SELECTED:'Đã chọn video — chưa phát',BUFFERING:'Đang tải video',PLAYING:'Đang phát',PAUSED:'Đã tạm dừng',STOPPED:'Đã dừng',ENDED:'Đã hết video',AUTOPLAY_BLOCKED:'Trình duyệt chặn tự động phát',ERROR:'Player gặp lỗi'};
const phaseLabels:Record<string,string>={ready:'Đã kết nối',connecting:'Đang kết nối',waiting_player:'Chờ YouTube',disconnected:'Đã ngắt',auth_required:'Cần đăng nhập',conflict:'Tab khác đang sử dụng',disabled:'Đã tắt tự kết nối'};
const button='inline-flex items-center justify-center gap-2 rounded-xl px-3 py-2.5 text-sm font-semibold disabled:opacity-40 disabled:cursor-not-allowed transition-colors';
export function MediaPlayer(){
 const [voiceEnabled,setVoiceEnabled]=useState(false);
 const {isAuthenticated,openAuthModal}=useAuth();
 const autoPlayer=useAutoPlayer(isAuthenticated);
 const {host,deviceId,phase,message,status,devices,refresh,start:startPlayer,disconnect,disabled}=autoPlayer;
 const [config,setConfig]=useState<MediaConfig|null>(null),[query,setQuery]=useState(''),[scope,setScope]=useState<'wewin'|'all'>('wewin');
 const [videos,setVideos]=useState<Video[]>([]),[error,setError]=useState(''),[notice,setNotice]=useState(''),[busy,setBusy]=useState(false),[volume,setVolume]=useState(60);
 const showError=(error:unknown)=>setError(error instanceof Error?error.message:'Không xử lý được yêu cầu player.');
 useEffect(()=>{let active=true;const poll=()=>mediaRequest<MediaConfig>('config').then(value=>{if(active)setConfig(value);}).catch(()=>{if(active)setConfig(null);});void poll();const timer=setInterval(poll,5000);return()=>{active=false;clearInterval(timer);};},[]);
 const ready=phase==='ready'&&status?.connected;
 const canControl=Boolean(ready&&status?.selected_video&&!status?.pending_command);
 const search=async(latest=false)=>{
  setBusy(true);setError('');setNotice('');
  try{const result=await autoMedia<{status:string;message?:string;videos:Video[]}>('tool',{tool:latest?'youtube_list_wewin_videos':'youtube_search',arguments:latest?{limit:6}:{query,scope,limit:6},device_id:deviceId});if(result.status!=='ok')throw new Error(result.message||'Không tìm được video.');setVideos(result.videos);if(!result.videos.length)setNotice('Không tìm thấy video phù hợp.');setConfig(await mediaRequest<MediaConfig>('config'));}
  catch(error){showError(error);}finally{setBusy(false);}
 };
 const control=async(action:string,video?:Video)=>{
  setError('');setNotice('');
  if(voiceEnabled&&['select','play','pause','resume','stop'].includes(action)){
   try{const chosen=video||status?.selected_video;const r=await voiceMedia<{status:string}>('action',{action,request_id:crypto.randomUUID(),...((action==='select'||action==='play')&&chosen?{video_id:chosen.video_id}:{})});if(!['intent_accepted','duplicate_request'].includes(r.status))throw new Error('Ý định media chưa được nhận.');setNotice('Đã nhận ý định; chờ browser và ESP32 xác nhận.');await refresh();}catch(e){showError(e);}return;
  }
  try{const result=await autoMedia<{status:string;state?:string;message?:string}>('tool',{tool:'youtube_control',arguments:{action,request_id:crypto.randomUUID(),...(video?{video_id:video.video_id}:{}),...(action==='volume'?{volume}:{})},device_id:deviceId});
   if(!['command_confirmed','command_pending','duplicate_request'].includes(result.status))throw new Error(result.message||'Player chưa xác nhận được lệnh.');
   if(result.status==='command_pending')setNotice('Đã nhận lệnh, đang chờ YouTube Player xác nhận.');await refresh();
  }catch(error){showError(error);}
 };
  return <div className="space-y-5 min-w-0 pb-8">
    <section className="bg-gradient-to-r from-[#123B86] to-[#1463E8] rounded-2xl p-5 sm:p-6 text-white flex flex-wrap gap-4 justify-between items-center">
      <div><div className="flex items-center gap-2 text-blue-100 text-xs font-semibold uppercase tracking-wider"><VideoIcon size={16}/> WeWIN Education · YouTube</div>
        <h1 className="text-2xl font-bold mt-2">Media Player</h1><p className="text-blue-100 text-sm mt-1">Tìm video, chọn nội dung và điều khiển trình phát trên laptop.</p></div>
      <div className="text-xs rounded-xl border border-white/25 bg-white/10 p-3 grid grid-cols-2 sm:grid-cols-3 gap-2">
        <p className="flex items-center gap-1.5"><span className={`w-2 h-2 rounded-full ${config?'bg-emerald-400':'bg-red-400'}`}/> Backend: {config?'Đã kết nối':'Chưa kết nối'}</p>
        <p className="flex items-center gap-1.5"><span className={`w-2 h-2 rounded-full ${config?.mcp_status==='connected'?'bg-emerald-400':'bg-amber-400'}`}/> MCP Cloud: {config?.mcp_status==='connected'?'Đã kết nối':'Đang kết nối'}</p>
        <p className="flex items-center gap-1.5"><span className={`w-2 h-2 rounded-full ${isAuthenticated?'bg-emerald-400':'bg-amber-400'}`}/> Quản trị: {isAuthenticated?'Đã xác thực':'Chưa đăng nhập'}</p>
        <p className="flex items-center gap-1.5"><span className={`w-2 h-2 rounded-full ${['ready','waiting_player'].includes(phase)?'bg-emerald-400':'bg-slate-300'}`}/> WebSocket: {['ready','waiting_player'].includes(phase)?'Đã kết nối':phaseLabels[phase]||phase}</p>
        <p className="flex items-center gap-1.5"><span className={`w-2 h-2 rounded-full ${deviceId?'bg-emerald-400':'bg-slate-300'}`}/> Thiết bị: {deviceId?'Đã đăng ký':'Chưa tạo'}</p>
        <p className="flex items-center gap-1.5"><span className={`w-2 h-2 rounded-full ${ready?'bg-emerald-400':'bg-amber-400'}`}/> YouTube Player: {ready?'Sẵn sàng nhận lệnh':'Đang chuẩn bị'}</p>
      </div>
    </section>
    {config&&!config.api_key_configured&&<div role="status" className="rounded-xl border border-amber-200 bg-amber-50 text-amber-900 p-4 text-sm">Chưa cấu hình YouTube API key ở backend. Tìm kiếm live và Channel ID chưa được xác minh. Xem hướng dẫn Phase 7C.1; không nhập API key vào trang này.</div>}
    {config?.test_fixture&&<div role="status" className="rounded-xl border border-amber-300 bg-amber-50 text-amber-900 p-4 text-sm font-semibold">MÔI TRƯỜNG KIỂM THỬ: metadata YouTube là fixture, không phải kết quả API live hoặc kênh WeWIN đã xác minh.</div>}
    {error&&<div role="alert" className="rounded-xl border border-red-200 bg-red-50 text-red-800 p-4 text-sm break-words">{error}</div>}
    {notice&&<div role="status" className="rounded-xl border border-blue-200 bg-blue-50 text-blue-900 p-3 text-sm">{notice}</div>}
    {!isAuthenticated && (
      <div className="bg-amber-50 border border-amber-200 rounded-2xl p-4 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 shadow-xs">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-amber-100 flex items-center justify-center text-amber-700 shrink-0">
            <ShieldCheck size={20} />
          </div>
          <div>
            <h3 className="text-sm font-bold text-amber-900">Trình duyệt chưa xác thực Quản trị viên</h3>
            <p className="text-xs text-amber-700">Cần đăng nhập phiên quản trị để kết nối Robot WeWIN và điều khiển Media Player.</p>
          </div>
        </div>
        <button
          onClick={openAuthModal}
          className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-xs font-semibold rounded-xl shadow-xs transition-colors shrink-0 cursor-pointer"
        >
          Đăng nhập Quản trị viên
        </button>
      </div>
    )}

    {/* HERO CARD: Direct YouTube Speaker */}
    <DirectSpeaker authenticated={isAuthenticated} autoPlayer={autoPlayer} />

    {/* Legacy / Debug Tools Collapsible */}
    <details className="border border-slate-200 rounded-2xl overflow-hidden bg-slate-50/50">
      <summary className="p-4 text-xs font-bold text-slate-500 uppercase tracking-wider cursor-pointer hover:bg-slate-100 transition-colors">
        Công cụ kỹ thuật / Legacy
      </summary>
      <div className="p-4 sm:p-6 space-y-6 border-t border-slate-200 bg-white">
        <EducationPanel authenticated={isAuthenticated}/><VoiceMediaPanel authenticated={isAuthenticated} onEnabled={setVoiceEnabled}/>
        {!voiceEnabled&&<WifiSpeaker authenticated={isAuthenticated} videoState={status?.state} videoId={status?.selected_video?.video_id}/>}
    <div className="grid xl:grid-cols-[minmax(0,1.35fr)_minmax(300px,1fr)] gap-5 items-start">
      <section className="bg-white border border-slate-200 rounded-2xl overflow-hidden min-w-0">
        <div className="p-4 flex flex-wrap items-center justify-between gap-2 border-b border-slate-100"><h2 className="font-bold text-slate-800">Thiết bị phát của bạn</h2>
          <span className={`text-xs font-semibold px-2 py-1 rounded-lg ${ready&&status?.state==='PLAYING'?'bg-emerald-50 text-emerald-700':'bg-slate-100 text-slate-600'}`}>{phase==='waiting_player'?'Đang chờ YouTube Player…':phase==='connecting'?'Đang kết nối player…':labels[ready?status?.state||'PLAYER_READY':'PLAYER_DISCONNECTED']}</span></div>
        <div className="p-4 bg-slate-900 rounded-xl text-center text-slate-300 text-xs">
          <VideoIcon className="mx-auto mb-2 text-blue-400" size={24}/>
          <p>Khung phát video chính đã tích hợp ở mục &quot;Phát YouTube qua loa WeWIN&quot; phía trên.</p>
        </div>
        <div className="p-4 space-y-4">
          <div className="flex flex-wrap gap-2">
            {!isAuthenticated?<button className={`${button} bg-blue-600 text-white`} onClick={openAuthModal}>Đăng nhập để tự kết nối</button>:
              <><button className={`${button} bg-blue-600 text-white`} onClick={startPlayer} disabled={phase==='connecting'}><RefreshCw size={16}/>{disabled?'Kết nối player':'Kết nối lại'}</button>
              <button className={`${button} bg-slate-100 text-slate-700`} onClick={()=>void disconnect(false).catch(showError)} disabled={!deviceId}>Ngắt kết nối</button>
              <button className={`${button} text-slate-600 border border-slate-200`} onClick={()=>void disconnect(true).catch(showError)} disabled={!deviceId}>Quên thiết bị</button></>}
          </div>
          <p className="text-xs text-slate-500">Default Player: {devices.find(d=>d.is_default)?.name||'Chưa chọn'} · Kết nối: {phaseLabels[phase]||phase}</p>
          {devices.length>1&&<label className="block text-xs text-slate-600">Chọn Default Player<select aria-label="Default Player" value={devices.find(d=>d.is_default)?.device||''} className="ml-2 border rounded p-2" onChange={e=>void autoMedia('default',{device_id:e.target.value}).then(()=>refresh()).catch(showError)}>{devices.map(d=><option key={d.device} value={d.device}>{d.name} · {d.device.slice(0,8)}</option>)}</select></label>}
          {message&&<p role="status" className="text-xs text-blue-700">{message}</p>}
          {status?.selected_video?<div><h3 className="font-semibold text-slate-900 break-words">{status.selected_video.title}</h3><p className="text-xs text-slate-500 mt-1">{status.selected_video.channel_title} · {status.selected_video.is_wewin?'Đúng kênh WeWIN đã xác minh':'YouTube — không gắn nhãn WeWIN'}</p></div>:<p className="text-sm text-slate-500">Chưa chọn video. Chọn từ kết quả tìm kiếm; thao tác chọn chưa phát video.</p>}
          <div className="flex flex-wrap gap-2"><button className={`${button} bg-blue-600 text-white`} disabled={!canControl} onClick={()=>control('play')}><Play size={16}/>Play</button><button className={`${button} bg-slate-100 text-slate-700`} disabled={!canControl} onClick={()=>control('pause')}><Pause size={16}/>Pause</button><button className={`${button} bg-slate-100 text-slate-700`} disabled={!canControl} onClick={()=>control('resume')}><Play size={16}/>Resume</button><button className={`${button} bg-slate-100 text-slate-700`} disabled={!canControl} onClick={()=>control('stop')}><Square size={16}/>Stop</button></div>
          <div className="flex items-center gap-3 text-sm text-slate-600"><Volume2 size={16}/><label htmlFor="media-volume">Âm lượng</label><input id="media-volume" type="range" min="0" max="100" value={volume} onChange={e=>setVolume(Number(e.target.value))} className="min-w-0 flex-1 accent-blue-600"/><button className="text-blue-700 font-semibold disabled:opacity-40" disabled={!canControl} onClick={()=>control('volume')}>Đặt {volume}%</button></div>
          {status?.pending_command&&<p className="text-xs text-blue-700">Lệnh {status.pending_command.action}: {status.pending_command.command_status} — chưa xác nhận trạng thái mới.</p>}
          {status?.state==='AUTOPLAY_BLOCKED'&&<p role="alert" className="text-sm text-amber-800 bg-amber-50 rounded-lg p-3">Bấm nút Play trực tiếp trong khung YouTube để cho phép phát. Hệ thống không vượt chính sách autoplay của trình duyệt.</p>}
          {status?.message&&<p className="text-sm text-slate-600">{status.message}</p>}
          <p className="text-xs text-slate-400">Ghép nối sẽ tải player chính thức từ YouTube. Giữ nguyên điều khiển và quảng cáo của YouTube. <a className="underline" href="https://www.youtube.com/t/terms" target="_blank" rel="noreferrer">Điều khoản YouTube</a> · <a className="underline" href="https://policies.google.com/privacy" target="_blank" rel="noreferrer">Chính sách Google</a></p>
        </div>
      </section>
      <section className="bg-white border border-slate-200 rounded-2xl p-4 min-w-0 space-y-4">
        <div><h2 className="font-bold text-slate-900">Khám phá video</h2><p className="text-xs text-slate-500 mt-1 flex items-center gap-1"><ShieldCheck size={14}/>{config?.channel?.verified&&!config.test_fixture?'Channel ID đã xác minh qua API':'Kênh @WeWINEducation — chờ xác minh API live'}</p></div>
        <div className="flex rounded-xl bg-slate-100 p-1 text-xs font-semibold">{(['wewin','all'] as const).map(s=><button key={s} onClick={()=>{setScope(s);setVideos([]);}} className={`flex-1 px-2 py-2 rounded-lg ${scope===s?'bg-white text-blue-700 shadow-sm':'text-slate-500'}`}>{s==='wewin'?'WeWIN Education':'Tất cả YouTube'}</button>)}</div>
        <form onSubmit={e=>{e.preventDefault();void search();}} className="flex gap-2"><input aria-label="Từ khóa YouTube" maxLength={160} value={query} onChange={e=>setQuery(e.target.value)} placeholder="Ví dụ: Cambridge Movers" className="min-w-0 flex-1 border border-slate-200 rounded-xl px-3 py-2.5 text-sm focus:outline-blue-500"/><button aria-label="Tìm video" disabled={busy||!query.trim()} className={`${button} bg-blue-600 text-white`}><Search size={17}/></button></form>
        {scope==='wewin'&&<button onClick={()=>search(true)} disabled={busy} className="text-sm text-blue-700 font-semibold disabled:opacity-40">Xem video WeWIN mới nhất →</button>}
        {busy&&<p role="status" className="text-sm text-blue-600">Đang truy vấn YouTube API…</p>}
        {!videos.length&&!busy&&<div className="text-center py-10 text-slate-400"><Search className="mx-auto mb-3" size={30}/><p className="text-sm">Tìm video theo từ khóa hoặc xem video WeWIN mới nhất.</p></div>}
        <div className="space-y-3">{videos.map(v=><article key={v.video_id} className="rounded-xl border border-slate-200 p-3 space-y-2"><div className="flex gap-3">{v.thumbnail?<img src={v.thumbnail} alt="" className="w-28 h-16 rounded-lg object-cover shrink-0"/>:<div className="w-20 bg-slate-100 rounded-lg shrink-0"/>}<div className="min-w-0"><h3 className="text-sm font-semibold text-slate-800 break-words line-clamp-3">{v.title}</h3><p className="text-xs text-slate-500 mt-1 break-words">{v.channel_title}</p>{v.is_wewin&&<span className="text-[10px] text-blue-700 font-bold">WeWIN · đã xác minh Channel ID</span>}</div></div><div className="flex items-center justify-between gap-2"><button disabled={!ready||!!status?.pending_command||!v.embeddable} onClick={()=>control('select',v)} className="text-xs font-bold text-blue-700 disabled:text-slate-400">Chọn video</button><a href={v.url} target="_blank" rel="noreferrer" className="text-xs text-slate-500 inline-flex items-center gap-1">Xem trên YouTube <ExternalLink size={12}/></a></div><p className="text-[10px] text-slate-400">{v.embeddable?'API cho phép nhúng; khả năng phát cần player xác nhận.':'Video không cho nhúng hoặc không khả dụng.'}</p></article>)}</div>
      </section>
    </div>
      </div>
    </details>
  </div>;
}
