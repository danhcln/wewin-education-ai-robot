export interface BrowserSession {authenticated:boolean;role:string;csrf:string}
let csrf='';
export class BrowserSessionError extends Error {status:number;constructor(status:number,message:string){super(message);this.status=status;}}
export function getBrowserCsrf(){return csrf;}
export function clearBrowserSession(){csrf='';}
function validated(value:BrowserSession){
 if(value.authenticated!==true||value.role!=='admin'||typeof value.csrf!=='string'||! /^[a-f0-9]{64}$/.test(value.csrf))throw new BrowserSessionError(401,'Phản hồi xác thực không hợp lệ.');
 csrf=value.csrf;return value;
}
export async function browserSession():Promise<BrowserSession>{
  const response=await fetch('/api/browser/session',{credentials:'same-origin',cache:'no-store',signal:AbortSignal.timeout(8000)});
  if(!response.ok){if(response.status===401)csrf='';throw new BrowserSessionError(response.status,'Cần đăng nhập quản trị.');}
  return validated(await response.json() as BrowserSession);
}
export async function browserLogin(token:string):Promise<BrowserSession>{
  const response=await fetch('/api/browser/login',{method:'POST',credentials:'same-origin',headers:{Authorization:'Bearer '+token,'Content-Type':'application/json'},body:'{}',signal:AbortSignal.timeout(8000)});
  if(!response.ok)throw new Error('Không xác thực được mã quản trị.');
  return validated(await response.json() as BrowserSession);
}
export async function browserLogout(){
  const response=await fetch('/api/browser/logout',{method:'POST',credentials:'same-origin',headers:{'X-WeWIN-CSRF':csrf,'Content-Type':'application/json'},body:'{}',signal:AbortSignal.timeout(8000)});
  if(!response.ok)throw new Error('Chưa đăng xuất được phiên trên backend.');csrf='';
}
export async function renewBrowserSession(){
  const response=await fetch('/api/browser/renew',{method:'POST',credentials:'same-origin',headers:{'X-WeWIN-CSRF':csrf,'Content-Type':'application/json'},body:'{}',signal:AbortSignal.timeout(8000)});
  if(!response.ok)throw new Error('Phiên đăng nhập đã hết hạn.');validated(await response.json() as BrowserSession);
}
