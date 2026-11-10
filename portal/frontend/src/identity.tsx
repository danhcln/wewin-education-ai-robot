import {createContext,useContext} from 'react'
export type Identity={role:string;user_id:string}
export const SessionContext=createContext<Identity>({role:'',user_id:''})
export function useIdentity(){const identity=useContext(SessionContext);return {...identity,staff:identity.role==='admin'||identity.role==='teacher',owns:(owner:unknown)=>identity.role==='admin'||owner===identity.user_id}}
