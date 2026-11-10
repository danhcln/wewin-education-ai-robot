import {useCallback,useEffect,useRef,useState} from 'react'
import {api} from './api'

export function useData<T>(path:string){
 const [data,setData]=useState<T|null>(null),[error,setError]=useState(''),[loading,setLoading]=useState(true)
 const generation=useRef(0)
 const load=useCallback(async()=>{const current=++generation.current;setLoading(true);setError('');try{const result=await api<T>(path);if(generation.current===current)setData(result)}catch(e){if(generation.current===current)setError((e as Error).message)}finally{if(generation.current===current)setLoading(false)}},[path])
 useEffect(()=>{setData(null);void load();return()=>{generation.current++}},[load])
 return {data,error,loading,load}
}
export function Heading({title,description}:{title:string;description?:string}){return <div className="page-heading"><div><span className="eyebrow">WEWIN • LEARN WITH WIN</span><h1>{title}</h1><p>{description}</p></div></div>}
export function Panel({title,children}:{title:string;children:React.ReactNode}){return <section className="panel"><div className="panel-head"><h2>{title}</h2></div>{children}</section>}
export function Feedback({error,message}:{error?:string;message?:string}){return <>{error&&<div role="alert" className="error-box">{error}</div>}{message&&<div role="status" className="success-note">{message}</div>}</>}
export function Field({label,children}:{label:string;children:React.ReactNode}){return <label className="field"><span>{label}</span>{children}</label>}
export function Empty({loading=false}:{loading?:boolean}){return <div className="empty">{loading?'Đang tải…':'Chưa có dữ liệu. Hãy tạo nội dung đầu tiên.'}</div>}
export const when=(v:number|null)=>v?new Date(v*1000).toLocaleString('vi-VN'):'—'
export type RecordItem={id:string;title:string;[key:string]:unknown}
