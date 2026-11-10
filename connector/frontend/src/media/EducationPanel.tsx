import {useState} from 'react';
import {browserSession} from '../services/browserSession';

type Asset={asset_id:string;youtube_video_id:string|null;revision:number;rights_status:string};
type Lesson={video_id:string;title:string;playable_on_robot:boolean;source_reason?:string};
async function education<T>(path:string,body?:unknown):Promise<T>{
 const headers:Record<string,string>={};
 if(body!==undefined){headers['Content-Type']='application/json';headers['X-WeWIN-CSRF']=(await browserSession()).csrf;}
 const response=await fetch('/api/education/'+path,{method:body===undefined?'GET':'POST',credentials:'same-origin',headers,body:body===undefined?undefined:JSON.stringify(body)});
 if(!response.ok)throw new Error('Chưa thực hiện được yêu cầu. Kiểm tra kết nối robot và nguồn bài học.');
 return response.json() as Promise<T>;
}
export function EducationPanel({authenticated}:{authenticated:boolean}){
 const [query,setQuery]=useState(''),[items,setItems]=useState<Lesson[]>([]),[message,setMessage]=useState('');
 const [state,setState]=useState('Chưa kiểm tra');
 const [assets,setAssets]=useState<Asset[]>([]),[assetId,setAssetId]=useState(''),[videoId,setVideoId]=useState(''),[confirmed,setConfirmed]=useState(false);
 const run=async(action:()=>Promise<void>)=>{try{await action();}catch(error){setMessage(error instanceof Error?error.message:'Yêu cầu chưa thành công.');}};
 const action=async(name:string,video_id?:string)=>{
  const result=await education<{status:string}>('playback/actions',{action:name,video_id,request_id:crypto.randomUUID()});
  setMessage(result.status==='intent_accepted'?'Đã nhận lệnh. Bấm kiểm tra trạng thái để xem kết quả.':result.status);
 };
 return <section className="bg-white border rounded-2xl p-4 space-y-3">
  <h2 className="font-bold">Bài học WeWIN Education · Audio gốc</h2>
  <p className="text-sm">Bài có nguồn audio được duyệt có thể phát trực tiếp trên robot.</p>
  <input aria-label="Tìm bài học WeWIN" value={query} onChange={e=>setQuery(e.target.value)} className="border rounded p-2"/>
  <button disabled={!authenticated} onClick={()=>void run(async()=>setItems((await education<{videos:Lesson[]}>('lessons?query='+encodeURIComponent(query))).videos))} className="border rounded p-2">{query?'Tìm bài học':'Bài mới nhất'}</button>
  <ul>{items.map(v=><li key={v.video_id} className="py-2 flex gap-2 items-center"><span>{v.title}</span><button className="border rounded p-2" disabled={!v.playable_on_robot} onClick={()=>void run(async()=>{await education('queues',{video_ids:items.map(i=>i.video_id)});await action('play',v.video_id);})}>{v.playable_on_robot?'Phát trên robot':'Chưa có audio được duyệt'}</button></li>)}</ul>
  <div className="flex gap-2">{['pause','resume','next','stop'].map((name,i)=><button disabled={!authenticated} className="border rounded p-2" key={name} onClick={()=>void run(()=>action(name))}>{['Tạm dừng','Tiếp tục','Bài tiếp','Dừng'][i]}</button>)}
  <button className="border rounded p-2" disabled={!authenticated} onClick={()=>void run(async()=>{const s=await education<{state:string;title?:string}>('playback/status');setState((s.title||'')+' · '+s.state);})}>Kiểm tra trạng thái</button></div>
  <details><summary>Quản lý mapping audio gốc</summary>
   <button disabled={!authenticated} onClick={()=>void run(async()=>setAssets((await education<{assets:Asset[]}>('assets')).assets))}>Tải danh sách asset đã import</button>
   <select aria-label="Audio asset" value={assetId} onChange={e=>{setAssetId(e.target.value);setConfirmed(false);}}><option value="">Chọn asset</option>{assets.map(a=><option key={a.asset_id} value={a.asset_id}>{a.asset_id} · {a.rights_status} · {a.youtube_video_id||'chưa gán video'}</option>)}</select>
   <input aria-label="YouTube Video ID để mapping" value={videoId} onChange={e=>{setVideoId(e.target.value.trim());setConfirmed(false);}} maxLength={11}/>
   <label><input type="checkbox" checked={confirmed} onChange={e=>setConfirmed(e.target.checked)}/>Tôi đã đối chiếu đúng nội dung audio/video và quyền phát của bài này.</label>
   {['Gán mapping','Thu hồi quyền phát'].map((label,index)=><button key={label} disabled={!authenticated||!confirmed||!assetId||(index===0&&!/^[A-Za-z0-9_-]{11}$/.test(videoId))} onClick={()=>void run(async()=>{const asset=assets.find(a=>a.asset_id===assetId);if(!asset)return;await education('assets/'+encodeURIComponent(assetId)+'/mapping',{video_id:index===0?videoId:null,expected_revision:asset.revision,content_and_rights_confirmed:confirmed,revoke:index===1});setConfirmed(false);setAssets((await education<{assets:Asset[]}>('assets')).assets);setMessage('Đã cập nhật mapping. Nội dung thật vẫn cần kiểm tra khi phát.');})}>{label}</button>)}
  </details>
  <p role="status">{state} {message}</p>
 </section>;
}
