import React,{createContext,useContext,useState,useEffect,useRef} from 'react';
import {getAdminToken,clearAdminToken,UNAUTHORIZED_EVENT} from '../services/api';
import {browserSession,browserLogin,browserLogout,renewBrowserSession,clearBrowserSession,BrowserSessionError} from '../services/browserSession';
interface AuthContextType {token:string;isAuthenticated:boolean;isValidating:boolean;saveToken:(token:string)=>Promise<boolean>;logout:()=>Promise<void>;isAuthModalOpen:boolean;openAuthModal:()=>void;closeAuthModal:()=>void;requireAdmin:(action:()=>void)=>void}
const AuthContext=createContext<AuthContextType|null>(null);
export const AuthProvider:React.FC<{children:React.ReactNode}>=({children})=>{
 const [isAuthenticated,setAuthenticated]=useState(false),[isValidating,setValidating]=useState(true),[isAuthModalOpen,setModal]=useState(false);
 const attempt=useRef(0),busy=useRef(false);
 useEffect(()=>{
  let active=true;
  const restore=async()=>{
   if(busy.current)return;const version=++attempt.current;
   try{
    let session;
    try{session=await browserSession();}
    catch(error){const legacy=getAdminToken();if(!legacy)throw error;session=await browserLogin(legacy);clearAdminToken();}
    if(active&&version===attempt.current)setAuthenticated(session.authenticated&&session.role==='admin');
   }catch(error){if(active&&version===attempt.current&&error instanceof BrowserSessionError&&error.status===401)setAuthenticated(false);}
   finally{if(active&&version===attempt.current)setValidating(false);}
  };
  void restore();const poll=setInterval(restore,15000);window.addEventListener('online',restore);
  const renew=setInterval(()=>{if(!busy.current)void renewBrowserSession().catch(()=>void restore());},1800000);
  const invalidate=()=>{attempt.current++;clearAdminToken();clearBrowserSession();setAuthenticated(false);setValidating(false);};
  window.addEventListener(UNAUTHORIZED_EVENT,invalidate);
  return()=>{active=false;attempt.current++;clearInterval(poll);clearInterval(renew);window.removeEventListener('online',restore);window.removeEventListener(UNAUTHORIZED_EVENT,invalidate);};
 },[]);
 const saveToken=async(value:string)=>{
  busy.current=true;const version=++attempt.current;setValidating(true);setAuthenticated(false);
  try{const session=await browserLogin(value.trim());if(version!==attempt.current)return false;clearAdminToken();setAuthenticated(session.authenticated&&session.role==='admin');setModal(false);return session.authenticated&&session.role==='admin';}
  catch{clearAdminToken();if(version===attempt.current)setAuthenticated(false);return false;}
  finally{busy.current=false;if(version===attempt.current)setValidating(false);}
 };
 const logout=async()=>{busy.current=true;attempt.current++;try{await browserLogout();clearAdminToken();setAuthenticated(false);setModal(false);}finally{busy.current=false;}};
 const requireAdmin=(action:()=>void)=>{if(!isValidating&&isAuthenticated)action();else setModal(true);};
 return <AuthContext.Provider value={{token:'',isAuthenticated,isValidating,saveToken,logout,isAuthModalOpen,openAuthModal:()=>setModal(true),closeAuthModal:()=>setModal(false),requireAdmin}}>{children}</AuthContext.Provider>;
};
export const useAuth=()=>{const value=useContext(AuthContext);if(!value)throw new Error('useAuth requires AuthProvider');return value;};
