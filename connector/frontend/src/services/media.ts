import {getAdminToken,UNAUTHORIZED_EVENT} from './api';
export interface Video {video_id:string;title:string;channel_id:string;channel_title:string;thumbnail:string;published_at?:string;url:string;is_wewin:boolean;embeddable:boolean;availability:string}
export interface Pair {session_id:string;player_token:string;control_token:string}
export interface Channel {verified:boolean;channel_id:string;uploads_playlist_id:string;handle:string}
export interface MediaConfig {api_key_configured:boolean;handle:string;channel:Channel|null;mcp_status:string;test_fixture?:boolean}
export interface Status {status:string;state:string;connected:boolean;selected_video?:Video;observed_video_id?:string;pending_command?:{action:string;command_status:string};message?:string}
export async function mediaRequest<T>(path:string,body?:unknown,admin=false):Promise<T> {
  const headers:Record<string,string>={'Content-Type':'application/json'};
  if(admin)headers.Authorization='Bearer '+getAdminToken();
  const r=await fetch('/api/media/'+path,{method:body===undefined?'GET':'POST',headers,cache:'no-store',signal:AbortSignal.timeout(25000),body:body===undefined?undefined:JSON.stringify(body)});
  const data=await r.json();
  if(admin&&r.status===401)window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
  if(!r.ok||data.status&& !['ok','command_queued','command_received','command_confirmed','revoked'].includes(data.status))
    throw new Error(data.message||(r.status===401?'Cần đăng nhập quản trị để ghép nối.':'Yêu cầu media bị từ chối.'));
  return data as T;
}
export function mediaTool<T>(tool:string,args:Record<string,unknown>){return mediaRequest<T>('tool',{tool,arguments:args});}
