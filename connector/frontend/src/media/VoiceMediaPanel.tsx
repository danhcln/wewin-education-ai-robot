import {useEffect,useState} from 'react';
import {voiceMedia} from '../services/voiceMedia';
import type {VoiceMediaStatus} from '../services/voiceMedia';
import {streamRequest} from '../services/stream';
import type {LoopbackDevice} from '../services/stream';
export function VoiceMediaPanel({authenticated,onEnabled}:{authenticated:boolean;onEnabled:(enabled:boolean)=>void}){
 const [value,setValue]=useState<VoiceMediaStatus|null>(null),[message,setMessage]=useState('');
 const [devices,setDevices]=useState<LoopbackDevice[]>([]),[capture,setCapture]=useState('');
 const [consent,setConsent]=useState(false),[routed,setRouted]=useState(false);
 useEffect(()=>{if(!authenticated){onEnabled(false);return;}let alive=true;const poll=()=>void voiceMedia<VoiceMediaStatus>('status').then(r=>{if(alive){setValue(r);onEnabled(r.configuration.enabled);}}).catch(()=>{if(alive)setMessage('Chưa đọc được trạng thái điều phối.');});poll();const t=setInterval(poll,1500);return()=>{alive=false;clearInterval(t);};},[authenticated,onEnabled]);
 const configure=async(enabled:boolean)=>{try{await voiceMedia('configure',{enabled,capture_name:capture||value?.configuration.capture_name||'',system_mix_consent:consent,local_route_confirmed:routed});setMessage(enabled?'Đã yêu cầu bật LAN control; cần ghép đúng ESP32 và kiểm tra routing.':'Đã yêu cầu dừng; xem trạng thái thiết bị để xác nhận nhả loa.');}catch(e){setMessage(e instanceof Error?e.message:'Chưa cấu hình được.');}};
 const stop=async()=>{try{await voiceMedia('action',{action:'stop',request_id:crypto.randomUUID()});setMessage('Đã nhận ý định dừng; chưa coi là IDLE đến khi có ACK.');}catch{setMessage('Chưa gửi được yêu cầu dừng.');}};
 const device=value?.configuration.devices.find(d=>d.device_id===value.configuration.default_device);
 return <section className="bg-white border border-slate-200 rounded-2xl p-4 space-y-3">
  <h2 className="font-bold text-slate-900">WeWIN Wi-Fi Speaker · Điều khiển giọng nói</h2>
  <p className="text-sm text-slate-700">Video: {value?.media.title||'Chưa chọn'} · Media: {value?.media.state||'Chưa kiểm tra'}</p>
  <p className="text-xs text-slate-600">Browser: {value?.media.browser_state||'Chưa có ACK'} · ESP32: {device?.online?'Đã xác thực':'Chưa kết nối'} · Wi-Fi Speaker: {value?.media.stream_state||device?.stream?.state||'IDLE'}</p>
  <p className="text-xs text-slate-500">Thu system loopback Windows. PLAYING/ACK không thay thế việc nghe loa thực tế. Không tải hoặc tách audio YouTube.</p>
  <button disabled={!authenticated||!value?.configuration.enabled} onClick={()=>void stop()} className="border rounded-xl px-3 py-2 text-blue-700 disabled:opacity-40">Stop Wi-Fi Speaker / Video</button>
  <details className="text-sm border-t pt-2"><summary className="cursor-pointer text-blue-700">Thiết lập LAN, ghép nối và đường âm thanh</summary>
   <p className="text-xs text-amber-800 mt-3">Cần firmware Phase 2 đã được duyệt/nạp. Không tự mở firewall. Không mute YouTube; chuyển browser tới endpoint riêng để tránh loa laptop phát song song. Routing chưa được hệ thống đo tự động.</p>
   <button disabled={!authenticated} className="border rounded-xl px-3 py-2 mt-2" onClick={()=>void streamRequest<{devices:LoopbackDevice[]}>('devices').then(r=>setDevices(r.devices)).catch(()=>setMessage('Không liệt kê được loopback.'))}>Liệt kê loopback Windows</button>
   <select aria-label="Đầu ra browser cho media" value={capture} onChange={e=>setCapture(e.target.value)} className="border rounded-xl p-2 ml-2 max-w-full"><option value="">{value?.configuration.capture_name||'Chọn loopback'}</option>{devices.map(d=><option key={d.index} value={d.name}>{d.name}</option>)}</select>
   <label className="block text-xs mt-2"><input type="checkbox" checked={consent} onChange={e=>setConsent(e.target.checked)}/> Cho phép thu system mix của endpoint đã chọn.</label>
   <label className="block text-xs mt-2"><input type="checkbox" checked={routed} onChange={e=>setRouted(e.target.checked)}/> Đã chuẩn bị đầu ra để tránh double-audio; sẽ nghe xác minh.</label>
   <div className="flex gap-2 mt-2"><button disabled={!authenticated||!consent||!routed||!(capture||value?.configuration.capture_name)} onClick={()=>void configure(true)} className="bg-blue-600 text-white rounded-xl px-3 py-2 disabled:opacity-40">Bật điều phối LAN</button><button disabled={!authenticated} onClick={()=>void configure(false)} className="border rounded-xl px-3 py-2">Tắt điều phối</button></div>
   <p className="text-xs text-slate-600 mt-3">Ghép nối lần đầu tại <a href="/robots" className="text-blue-700 underline">Quản lý robot</a>: đối chiếu fingerprint qua MCP của đúng robot, tạo challenge và xác nhận bằng nút BOOT trên robot. Cần chữ ký một lần trong 120 giây. Identity được lưu trong NVS; không cần ghép lại sau mỗi reboot. Không nhập khóa bí mật vào giao diện.</p>
   {value?.configuration.pending.map(p=><div key={p.device_id} className="border rounded-xl p-2 mt-2 text-xs break-all"><p>Thiết bị chờ: {p.device_id}</p><p>Fingerprint: {p.fingerprint}</p><p>Chưa được cấp quyền phát; hoàn tất ghép nối vật lý tại Quản lý robot.</p></div>)}
  </details>
  {(message||value?.media.last_error)&&<p role="status" className="text-xs text-blue-800 break-words">{message||value?.media.last_error}</p>}
 </section>;
}
