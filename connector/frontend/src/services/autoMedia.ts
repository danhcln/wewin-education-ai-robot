import {browserSession,getBrowserCsrf} from './browserSession';
import {UNAUTHORIZED_EVENT} from './api';
export class AutoMediaError extends Error {status:number;constructor(status:number,message:string){super(message);this.status=status;}}
export async function autoMedia<T>(path:string,body?:unknown):Promise<T>{
 if(body!==undefined&&!getBrowserCsrf())await browserSession();
 const response=await fetch('/api/media/auto/'+path,{method:body===undefined?'GET':'POST',credentials:'same-origin',headers:{'Content-Type':'application/json',...(body===undefined?{}:{'X-WeWIN-CSRF':getBrowserCsrf()})},cache:'no-store',body:body===undefined?undefined:JSON.stringify(body),signal:AbortSignal.timeout(30000)});
 const value=await response.json();
 if(response.status===401)window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
 if(!response.ok)throw new AutoMediaError(response.status,typeof value.detail==='string'?value.detail:'Không xử lý được yêu cầu player.');
 return value as T;
}
