export type Robot={id:string;source?:string;kind?:string;uuid?:string|null;device_id:string;name:string;site_id:string;firmware:string|null;cloud_state:string|null;wifi_ip:string|null;last_seen:number|null;online:boolean}
export type Config={assistant_name:string;robot_name:string;ai_role:string;persona:string;system_prompt:string;greeting:string;language:string;voice:string;voice_gender:string;role_version:number;speech_rate:number;speech_style:string;ai_model:string;lesson_id:string;knowledge_pack:string;learning_path:string;media_pack:string;student_profile:string}
export type Detail={robot:Robot;version:number;config:Config;sync_state:string;updated_at:number|null;wake_word:{current:string;target:string;model:string;apply_supported:boolean};bluetooth:{state:string;scan_supported:boolean;paired_devices:string[]}}
export type Overview={robots:Robot[];drafts:number;mcp:string;tools:number;source:string;cloud_config_sync:string}
let csrf=''
export function setCsrf(value:string){csrf=value}
export async function api<T>(path:string,options:RequestInit={}):Promise<T>{
 const headers=new Headers(options.headers);if(options.body&&!(options.body instanceof FormData))headers.set('Content-Type','application/json');if(options.method&&options.method!=='GET')headers.set('X-WeWIN-CSRF',csrf)
 const response=await fetch('/api/portal'+path,{...options,headers,credentials:'same-origin',cache:'no-store'});
 const body=await response.json().catch(()=>({}));if(!response.ok){if(response.status===401)window.dispatchEvent(new Event('wewin-session-expired'));throw new Error(typeof body.detail==='string'?body.detail:body.detail&&typeof body.detail.message==='string'?body.detail.message:Array.isArray(body.detail)?body.detail.map((d:{loc:string[];msg:string})=>`${d.loc.slice(1).join('.')}: ${d.msg}`).join('; '):`HTTP ${response.status}`)}return body as T
}
export async function login(token:string){const response=await fetch('/api/portal/login',{method:'POST',headers:{Authorization:`Bearer ${token}`,Origin:location.origin},credentials:'same-origin'});const body=await response.json();if(!response.ok)throw new Error(body.detail||'Đăng nhập thất bại');setCsrf(body.csrf);return body}
export async function restore(){const body=await api<{csrf:string;role:string;user_id:string}>('/session');setCsrf(body.csrf);return body}
