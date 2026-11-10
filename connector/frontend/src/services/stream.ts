import {browserSession} from './browserSession.ts';
export interface StreamStatus {
  status: string;
  state?: string;
  session_id?: string;
  generation?: number;
  packets_sent?: number;
  packets_dropped?: number;
  capture_frames?: number;
  error?: string | null;
  device_report?: {
    state?: string;
    output_frames?: number;
    packets_received?: number;
    buffer_depth?: number;
  };
  device?: {
    device_id: string;
    ip?: string;
    online: boolean;
  };
  loopback?: {
    index: number;
    name: string;
    clean_name: string;
  };
  hello?: boolean;
  hardware_audio_verified?: boolean;
  robot_volume?: number;
  robot_muted?: boolean;
  descriptor?: Record<string, unknown>;
  transport_active?: boolean;
}
export interface LoopbackDevice {
  index: number;
  name: string;
  clean_name?: string;
  is_default?: boolean;
  sample_rate: number;
  channels: number;
}
export async function streamRequest<T>(path:string,body?:unknown):Promise<T>{
 const headers:Record<string,string>={};
 if(body!==undefined){const session=await browserSession();headers['X-WeWIN-CSRF']=session.csrf;headers['Content-Type']='application/json';}
 const response=await fetch('/api/stream/'+path,{method:body===undefined?'GET':'POST',credentials:'same-origin',cache:'no-store',headers,signal:AbortSignal.timeout(12000),body:body===undefined?undefined:JSON.stringify(body)});
 if(!response.ok)throw new Error('Cần phiên quản trị hợp lệ để dùng Wi-Fi Speaker.');
 return await response.json() as T;
}
