import {useState} from 'react';
import {browserSession} from '../services/browserSession';
type Candidate={wire_id:string;fingerprint:string};
type Challenge={challenge_id:string;display_code:string;instructions:string};
async function devices<T>(path:string,body?:unknown):Promise<T>{
 const headers:Record<string,string>={};
 if(body!==undefined){headers['Content-Type']='application/json';headers['X-WeWIN-CSRF']=(await browserSession()).csrf;}
 const response=await fetch('/api/devices/'+path,{method:body===undefined?'GET':'POST',credentials:'same-origin',headers,body:body===undefined?undefined:JSON.stringify(body)});
 if(!response.ok)throw new Error('Enrollment chưa thành công. Kiểm tra đăng nhập, challenge và proof từ đúng robot.');
 return response.json() as Promise<T>;
}
export function PhysicalEnrollmentPanel(){
 const [pending,setPending]=useState<Candidate[]>([]),[challenge,setChallenge]=useState<Challenge|null>(null),[signature,setSignature]=useState(''),[message,setMessage]=useState('');
 const run=async(fn:()=>Promise<void>)=>{try{await fn();}catch(e){setMessage(e instanceof Error?e.message:'Không thực hiện được enrollment.');}};
 return <section className="bg-white border rounded-2xl p-4 space-y-3">
  <h2 className="font-bold">Ghép robot bằng xác nhận vật lý</h2>
  <p>Đối chiếu fingerprint với đúng robot trước. Bấm BOOT ba lần khi Idle để mở cửa sổ ký một proof trong 120 giây.</p>
  <button className="border rounded p-2" onClick={()=>void run(async()=>setPending((await devices<{candidates:Candidate[]}>('discovery')).candidates))}>Tìm thiết bị chờ</button>
  {pending.map(p=><div className="break-all" key={p.wire_id}><p>{p.wire_id} · {p.fingerprint}</p><button onClick={()=>void run(async()=>{const r=await devices<{challenge:Challenge}>('enrollments',{candidate_wire_id:p.wire_id});setChallenge(r.challenge);setSignature('');})}>Tạo challenge cho thiết bị này</button></div>)}
  {challenge&&<div><p>Gọi native tool self.wewin_media.enrollment_proof trên đúng robot với tham số:</p><pre className="whitespace-pre-wrap">{JSON.stringify({challenge_id:challenge.challenge_id,display_code:challenge.display_code},null,2)}</pre><input className="border rounded p-2 w-full" aria-label="Chữ ký proof từ robot" value={signature} maxLength={128} onChange={e=>setSignature(e.target.value.trim())}/><button disabled={!/^[a-f0-9]{128}$/.test(signature)} onClick={()=>void run(async()=>{await devices('enrollments/'+challenge.challenge_id+'/confirm',{code:challenge.display_code,device_signature:signature});setChallenge(null);setSignature('');setMessage('Enrollment đã commit. Chờ authenticated presence để xác nhận robot online.');})}>Xác nhận proof</button></div>}
  <p role="status">{message}</p>
 </section>;
}
