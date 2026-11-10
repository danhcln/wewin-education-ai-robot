import {browserSession} from './browserSession.ts';
export interface VoiceMediaStatus {
 configuration:{enabled:boolean;listening:boolean;capture_name:string;default_device?:string;pending:{device_id:string;fingerprint:string}[];devices:{device_id:string;online:boolean;stream?:{state?:string}}[]};
 media:{state:string;generation?:number;title?:string;browser_state?:string;stream_state?:string;last_error?:string;hardware_audio_verified?:boolean};
}
export async function voiceMedia<T>(path:string,body?:unknown):Promise<T>{
 const headers:Record<string,string>={};
 if(body!==undefined){const session=await browserSession();headers['X-WeWIN-CSRF']=session.csrf;headers['Content-Type']='application/json';}
 const response=await fetch('/api/media/voice/'+path,{method:body===undefined?'GET':'POST',credentials:'same-origin',cache:'no-store',headers,body:body===undefined?undefined:JSON.stringify(body),signal:AbortSignal.timeout(12000)});
 if(!response.ok)throw new Error('Chưa xác nhận thao tác media; kiểm tra đăng nhập, ghép nối và cấu hình.');
 return await response.json() as T;
}
