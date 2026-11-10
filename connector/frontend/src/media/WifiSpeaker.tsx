import {useEffect,useRef,useState} from 'react';
import {streamRequest} from '../services/stream';
import type {StreamStatus,LoopbackDevice} from '../services/stream';
export function WifiSpeaker({authenticated,videoState,videoId}:{authenticated:boolean;videoState?:string;videoId?:string}){
 const [devices,setDevices]=useState<LoopbackDevice[]>([]),[endpoint,setEndpoint]=useState(''),[peer,setPeer]=useState('');
 const [consent,setConsent]=useState(false),[routed,setRouted]=useState(false),[status,setStatus]=useState<StreamStatus|null>(null),[message,setMessage]=useState('');
 const [starting,setStarting]=useState(false);const ending=useRef(false);const descriptor=useRef<Record<string,unknown>|null>(null);const sourceVideo=useRef<string|undefined>(undefined);
 useEffect(()=>{if(!authenticated)return;let active=true;
  const poll=()=>streamRequest<StreamStatus>('status').then(s=>{if(active){setStatus(s);if(s.state&&['CONNECTING','BUFFERING','PLAYING'].includes(s.state))void streamRequest('heartbeat',{}).catch(()=>{});}}).catch(()=>{if(active)setMessage('Backend Wi-Fi Speaker chưa phản hồi; chưa có xác nhận phát.');});
  void poll();const timer=setInterval(poll,1000);
  return()=>{active=false;clearInterval(timer);};
 },[authenticated]);
 useEffect(()=>{
  if(videoState==='ENDED'&&status?.state&&['CONNECTING','BUFFERING','PLAYING'].includes(status.state)&&!ending.current){ending.current=true;void streamRequest<StreamStatus>('end',{}).then(setStatus).catch(()=>setMessage('Chưa xác nhận kết thúc live stream.'));}
 },[videoState,status?.state]);
 useEffect(()=>{
  if(sourceVideo.current&&videoId&&sourceVideo.current!==videoId&&status?.state&&['CONNECTING','BUFFERING','PLAYING'].includes(status.state)){
   sourceVideo.current=videoId;descriptor.current=null;void streamRequest<StreamStatus>('stop',{}).then(s=>{setStatus(s);setMessage('Nguồn video đã đổi. Đang dừng phiên cũ; Start lại để tạo session/generation mới.');}).catch(()=>setMessage('Nguồn đã đổi nhưng chưa xác nhận dừng audio cũ; không bắt đầu phiên mới.'));
  }
 },[videoId,status?.state]);
 const list=async()=>{try{const r=await streamRequest<{status:string;devices:LoopbackDevice[]}>('devices');setDevices(r.devices);setMessage(r.status==='ok'?'Chỉ các đầu vào WASAPI render-loopback được cho phép.':'Thiếu dependency capture trên backend; xem runbook.');}catch{setMessage('Cần đăng nhập để xem endpoint.');}};
 const start=async()=>{setStarting(true);descriptor.current=null;try{const r=await streamRequest<StreamStatus>('start',{endpoint:Number(endpoint),peer_ipv4:peer,allow_system_mix:consent,local_output_routed_away:routed});setStatus(r);descriptor.current=r.descriptor||null;sourceVideo.current=videoId;ending.current=false;setMessage(r.descriptor?'Phiên đã chuẩn bị. ESP32 phải nhận descriptor riêng qua self.wewin_stream.start; chưa có bằng chứng loa phát.':'Chưa tạo phiên: '+r.status);}catch{setMessage('Không tạo được phiên; không coi là đã phát.');}finally{setStarting(false);}};
 const stop=async()=>{try{setStatus(await streamRequest<StreamStatus>('stop',{}));descriptor.current=null;}catch{setMessage('Chưa xác nhận dừng; kiểm tra backend và ESP32.');}};
 const copy=async()=>{if(descriptor.current){try{await navigator.clipboard.writeText(JSON.stringify({...descriptor.current,request_id:crypto.randomUUID()}));setMessage('Đã sao chép descriptor tạm. Chỉ cấp riêng cho client kiểm thử tin cậy; không gửi vào chat hoặc log.');}catch{setMessage('Không truy cập được clipboard; dùng API với client kiểm thử riêng.');}}};
 return <section className="bg-white border border-slate-200 rounded-2xl p-4 space-y-3">
  <h2 className="font-bold text-slate-900">Wi-Fi Speaker · Live Browser Audio · thử nghiệm</h2>
  <p className="text-sm text-slate-600">Thu âm thanh thực từ đầu ra Windows, không thu microphone hoặc dùng MP3 thay thế. Phase 1 thu toàn bộ âm thanh trên endpoint đã chọn, không riêng một tab.</p>
  <p className="text-xs text-amber-800">Cần firmware live đã được duyệt/nạp riêng. Không mute trong YouTube: sẽ mất nguồn capture. Chuyển đầu ra browser sang tai nghe/endpoint im tiếng phù hợp trước khi thử. Routing chưa được tự xác minh.</p>
  <div className="flex flex-wrap gap-2"><button disabled={!authenticated} className="px-3 py-2 border rounded-xl text-blue-700 disabled:opacity-40" onClick={()=>void list()}>Liệt kê đầu ra loopback</button>
   <select aria-label="WASAPI loopback endpoint" value={endpoint} onChange={e=>setEndpoint(e.target.value)} className="border rounded-xl px-2"><option value="">Chọn đầu ra Windows</option>{devices.map(d=><option key={d.index} value={d.index}>{d.name}</option>)}</select>
   <input aria-label="IPv4 ESP32 hiện tại" value={peer} onChange={e=>setPeer(e.target.value)} maxLength={15} placeholder="IPv4 ESP32 hiện tại" className="border rounded-xl px-3 py-2"/>
  </div>
  <label className="block text-xs text-slate-600"><input type="checkbox" checked={consent} onChange={e=>setConsent(e.target.checked)}/> Tôi cho phép thu system mix của đầu ra đã chọn.</label>
  <label className="block text-xs text-slate-600"><input type="checkbox" checked={routed} onChange={e=>setRouted(e.target.checked)}/> Tôi đã chuyển đầu ra để tránh loa laptop phát song song; cần nghe xác minh khi test.</label>
  <div className="flex flex-wrap gap-2"><button disabled={!authenticated||!endpoint||!peer||!consent||!routed||starting||!!status?.state&&!['IDLE','ERROR'].includes(status.state)} onClick={()=>void start()} className="bg-blue-600 text-white px-3 py-2 rounded-xl disabled:opacity-40">Start Wi-Fi Speaker</button>
   <button disabled={!authenticated} onClick={()=>void stop()} className="border px-3 py-2 rounded-xl disabled:opacity-40">Stop Wi-Fi Speaker</button>
   {descriptor.current&&<button onClick={()=>void copy()} className="border px-3 py-2 rounded-xl text-blue-700">Sao chép descriptor riêng cho test</button>}
  </div>
  <p className="text-sm">Windows: {status?.state||'Chưa kiểm tra'} · ESP32: {status?.device_report?.state||'Chưa có ACK'} · Gói đã gửi: {status?.packets_sent||0} · Output frames: {status?.device_report?.output_frames||0}</p>
  <p className="text-xs text-slate-500">Pause/resume đồng bộ chưa hỗ trợ. Trạng thái PLAYING do firmware báo chưa thay thế việc nghe loa thật. Không tự reconnect/replay phiên cũ.</p>
  {(message||status?.error)&&<p role="status" className="text-xs text-blue-800 break-words">{message||status?.error}</p>}
 </section>;
}
