import {useCallback,useEffect,useRef,useState} from 'react';
import {autoMedia,AutoMediaError} from '../services/autoMedia';
import {browserSession,BrowserSessionError} from '../services/browserSession';
import {mountPlayer} from './player';
import type {PlayerController,Telemetry,Command} from './player';
import {reconnectDelay,MAX_RECONNECT_ATTEMPTS} from './reconnect';
import type {Status} from '../services/media';

const DEVICE_KEY='wewin_media_device_id',DISABLED_KEY='wewin_media_disabled';
export interface Device {device:string;name:string;is_default:number}
export function useAutoPlayer(authenticated:boolean){
 const host=useRef<HTMLDivElement>(null);
 const [deviceId,setDeviceId]=useState(()=>localStorage.getItem(DEVICE_KEY)||'');
 const [disabled,setDisabled]=useState(()=>localStorage.getItem(DISABLED_KEY)==='true');
 const [attempt,setAttempt]=useState(0),[phase,setPhase]=useState('disconnected'),[message,setMessage]=useState('');
 const [status,setStatus]=useState<Status|null>(null),[devices,setDevices]=useState<Device[]>([]);
 const runVersion=useRef(0);
 useEffect(()=>{const changed=(event:StorageEvent)=>{
  if(event.key===DISABLED_KEY)setDisabled(event.newValue==='true');
  if(event.key===DEVICE_KEY)setDeviceId(event.newValue||'');
 };window.addEventListener('storage',changed);return()=>window.removeEventListener('storage',changed);},[]);
 const refresh=useCallback(async()=>{
  if(!authenticated||!deviceId)return;
  const version=runVersion.current;
  const result=await autoMedia<Status>('status?device_id='+encodeURIComponent(deviceId));
  if(version!==runVersion.current)return;
  setStatus(result);
  const list=await autoMedia<{devices:Device[]}>('devices');if(version===runVersion.current)setDevices(list.devices);
 },[authenticated,deviceId]);
 useEffect(()=>{
  if(!authenticated||disabled)return;
  let active=true,registering=false,serial=0,retries=0,ws:WebSocket|null=null,owned:PlayerController|null=null;
  let retry:ReturnType<typeof setTimeout>|undefined,heartbeat:ReturnType<typeof setInterval>|undefined,sampling:ReturnType<typeof setInterval>|undefined,readyTimer:ReturnType<typeof setTimeout>|undefined;
  ++runVersion.current;
  const stopFrame=()=>{clearInterval(heartbeat);clearInterval(sampling);clearTimeout(readyTimer);try{owned?.player.stopVideo();owned?.player.destroy();}catch{/* Closed frame. */}owned=null;};
  const schedule=(conflict=false)=>{
   if(!active)return;
   if(retries>=MAX_RECONNECT_ATTEMPTS){setPhase('disconnected');setMessage('Đã thử kết nối nhiều lần. Kiểm tra backend rồi bấm Kết nối lại.');return;}
   clearTimeout(retry);const delay=reconnectDelay(retries++);retry=setTimeout(()=>void connect(),conflict?Math.max(1000,delay):delay);
  };
  const connect=async()=>{
   if(!active||registering||ws?.readyState===WebSocket.CONNECTING||ws?.readyState===WebSocket.OPEN)return;
   registering=true;++runVersion.current;setPhase('connecting');setMessage('Đang tự kết nối player…');
   let id=localStorage.getItem(DEVICE_KEY);
   if(!id){id=crypto.randomUUID();localStorage.setItem(DEVICE_KEY,id);}
   setDeviceId(id);
   try{
    const session=await browserSession();if(!active)return;
    await autoMedia('register',{device_id:id,name:'WeWIN Windows Player'});if(!active)return;
    const current=++serial,tab=crypto.randomUUID();let seq=0,ready=false;
    ws=new WebSocket(`${location.protocol==='https:'?'wss':'ws'}://${location.host}/api/media/auto/player`);
    const socket=ws;
    const valid=()=>active&&current===serial&&socket===ws;
    const send=(event:Telemetry)=>{
     if(!valid()||socket.readyState!==WebSocket.OPEN)return;
     socket.send(JSON.stringify({...event,event_seq:++seq}));
     if(event.state==='PLAYER_READY'){ready=true;clearTimeout(readyTimer);retries=0;setPhase('ready');setMessage('');}
    };
    socket.onopen=()=>{if(valid())socket.send(JSON.stringify({type:'authenticate',csrf:session.csrf,device_id:id,tab_id:tab}));};
    socket.onmessage=async event=>{
     if(!valid())return;
     try{
      const value=JSON.parse(event.data);
      if(value.type==='authenticated'){
       setPhase('waiting_player');setMessage('Đã kết nối backend, đang chờ YouTube Player…');
       heartbeat=setInterval(()=>{if(valid()&&socket.readyState===WebSocket.OPEN)socket.send(JSON.stringify({type:'heartbeat'}));},5000);
       readyTimer=setTimeout(()=>{if(valid()&&!ready){setMessage('YouTube Player chưa sẵn sàng. Kiểm tra mạng hoặc nội dung bị chặn.');socket.close();}},20000);
       if(host.current){const controller=await mountPlayer(host.current,send,valid);if(valid()){owned=controller;sampling=setInterval(()=>{try{owned?.observe();}catch{/* Wait for actual readiness. */}},750);}else controller.player.destroy();}
      }else if(value.type==='command'){if(!owned?.command(value as Command))setMessage('Player chưa nhận được lệnh hợp lệ; chưa có xác nhận phát.');}
      else if(value.type==='connection_error')setMessage(value.code==='player_in_use'?'Player đang mở ở tab khác. Tab đó nhận lệnh.':'Phiên player bị gián đoạn; đang kiểm tra lại quyền.');
     }catch{if(valid())setMessage('Chưa tải được YouTube Player; sẽ thử lại.');}
    };
    socket.onclose=event=>{
     if(!valid())return;stopFrame();setStatus(null);
     if(event.code===4401){setPhase('auth_required');setMessage('Phiên đăng nhập đã hết hạn. Hãy đăng nhập lại.');return;}
     const conflict=event.code===4409;setPhase(conflict?'conflict':'disconnected');
     setMessage(conflict?'Player đang hoạt động ở tab khác; không gửi lệnh tới hai tab.':'Player mất kết nối. Đang tự nối lại; video sẽ không tự phát lại.');schedule(conflict);
    };
    socket.onerror=()=>{if(valid())setMessage('Kết nối player bị gián đoạn; đang thử lại.');};
   }catch(error){
    if(!active)return;
    if((error instanceof AutoMediaError||error instanceof BrowserSessionError)&&[401,403].includes(error.status)){setPhase('auth_required');setMessage('Cần đăng nhập lại để khôi phục player.');return;}
    setPhase('disconnected');setMessage('Backend chưa phản hồi; đang tự thử lại.');schedule();
   }finally{registering=false;}
  };
  const awaken=()=>{if(document.visibilityState==='visible'&&active){
   if(ws?.readyState===WebSocket.OPEN){ws.send(JSON.stringify({type:'heartbeat'}));return;}
   retries=0;clearTimeout(retry);if(ws?.readyState!==WebSocket.CONNECTING)void connect();
  }};
  void connect();window.addEventListener('online',awaken);window.addEventListener('focus',awaken);document.addEventListener('visibilitychange',awaken);
  return()=>{active=false;++runVersion.current;++serial;clearTimeout(retry);stopFrame();if(ws){ws.onclose=null;ws.close();}window.removeEventListener('online',awaken);window.removeEventListener('focus',awaken);document.removeEventListener('visibilitychange',awaken);};
 },[authenticated,disabled,attempt]);
 useEffect(()=>{if(!authenticated||!deviceId)return;const timer=setInterval(()=>void refresh().catch(()=>{}),1000);return()=>clearInterval(timer);},[authenticated,deviceId,refresh]);
 const start=()=>{localStorage.setItem(DISABLED_KEY,'false');setDisabled(false);setAttempt(n=>n+1);};
 const disconnect=async(forget=false)=>{
  await autoMedia(forget?'forget':'disconnect',{device_id:deviceId});localStorage.setItem(DISABLED_KEY,'true');setDisabled(true);setStatus(null);
  if(forget){localStorage.removeItem(DEVICE_KEY);setDeviceId('');}setPhase('disabled');setMessage(forget?'Đã quên thiết bị. Bấm Kết nối để đăng ký lại.':'Đã ngắt theo yêu cầu; tự kết nối đang tắt cho thiết bị này.');
 };
 return {host,deviceId,phase:disabled?'disabled':phase,message,status,devices,refresh,start,disconnect,disabled};
}
