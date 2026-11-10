export type PlayerState = 'PLAYER_DISCONNECTED'|'PLAYER_READY'|'VIDEO_SELECTED'|'BUFFERING'|'PLAYING'|'PAUSED'|'STOPPED'|'ENDED'|'AUTOPLAY_BLOCKED'|'ERROR';
export interface Command { command_id:string; seq:number; action:string; video_id:string; volume?:number; expires_at_ms:number;media_generation?:number }
export interface FramePlayer {
  cueVideoById(id:string):void; loadVideoById(id:string):void; playVideo():void; pauseVideo():void; stopVideo():void;
  setVolume(n:number):void; getVolume():number; getPlayerState():number; getVideoData():{video_id?:string}; getCurrentTime?():number; destroy():void;
}
export interface Telemetry { type:string; state?:PlayerState; video_id?:string; command_id?:string; volume?:number; error_code?:number; current_time?:number;media_generation?:number }

// Receipts never imply playback. Only IFrame getters/events generate telemetry.
export class PlayerController {
  player:FramePlayer; send:(e:Telemetry)=>void; lastSeq=0; pending:Command|null=null; lastVideo='';stopped=false;heldError=false;
  constructor(player:FramePlayer,send:(e:Telemetry)=>void) { this.player=player; this.send=send; }
  mediaGeneration=0;
  command(c:Command,now=Date.now()):boolean {
    const generation=c.media_generation??0;
    if(!Number.isInteger(generation)||generation<this.mediaGeneration||generation>2147483647)return false;
    if (!Number.isInteger(c.seq)||c.seq<=this.lastSeq||c.expires_at_ms<=now||!Number.isFinite(c.expires_at_ms)||
        !/^[A-Za-z0-9_-]{11}$/.test(c.video_id)||!['select','play','pause','resume','stop','volume'].includes(c.action)) return false;
    this.lastSeq=c.seq;this.pending=c;this.mediaGeneration=generation;
    this.heldError=false;if(['select','play','resume'].includes(c.action))this.stopped=false;
    this.send({type:'received',command_id:c.command_id});
    try {
      if(c.action==='select')this.player.cueVideoById(c.video_id);
      else if(c.action==='play'||c.action==='resume') {
        if(this.player.getVideoData().video_id===c.video_id)this.player.playVideo();else this.player.loadVideoById(c.video_id);
      } else if(c.action==='pause')this.player.pauseVideo();
      else if(c.action==='stop')this.player.stopVideo();
      else if(c.action==='volume'&&Number.isInteger(c.volume)&&c.volume!>=0&&c.volume!<=100)this.player.setVolume(c.volume!);
      else return false;
      return true;
    } catch {this.error(5);return false;}
  }
  ready(){this.send({type:'state',state:'PLAYER_READY'});}
  observe() {
    const raw=this.player.getPlayerState();const data=this.player.getVideoData();
    if(raw===1){this.heldError=false;this.stopped=false;}else if(this.heldError)return;
    const canceledBeforeLoad=this.pending?.action==='stop'&&this.mediaGeneration>0&&[-1,0,2,5].includes(raw);
    const id=canceledBeforeLoad?this.pending!.video_id:data.video_id||(this.pending?.action==='stop'?this.lastVideo:'');
    if(!id)return;
    if(this.pending&&id!==this.pending.video_id)return;
    this.lastVideo=id;
    let state:PlayerState|undefined=({1:'PLAYING',2:'PAUSED',3:'BUFFERING',5:'VIDEO_SELECTED',0:'ENDED'} as Record<number,PlayerState>)[raw];
    if((this.pending?.action==='stop'||this.stopped)&&[-1,0,2,5].includes(raw)){state='STOPPED';this.stopped=true;}
    if(!state)return;
    const c=this.pending;
    this.send({type:'state',state,video_id:id,command_id:c?.command_id,volume:this.player.getVolume(),current_time:this.player.getCurrentTime?.(),media_generation:this.mediaGeneration});
    if(c&&((c.action==='select'&&state==='VIDEO_SELECTED')||(['play','resume'].includes(c.action)&&state==='PLAYING')||
       (c.action==='pause'&&state==='PAUSED')||(c.action==='stop'&&state==='STOPPED')||
       (c.action==='volume'&&this.player.getVolume()===c.volume)))this.pending=null;
  }
  blocked(){this.heldError=true;this.send({type:'state',state:'AUTOPLAY_BLOCKED',video_id:this.player.getVideoData().video_id,command_id:this.pending?.command_id,media_generation:this.mediaGeneration});this.pending=null;}
  error(code:number){this.heldError=true;this.send({type:'state',state:'ERROR',error_code:code,video_id:this.player.getVideoData().video_id,command_id:this.pending?.command_id,media_generation:this.mediaGeneration});this.pending=null;}
}

type Options={width:string;height:string;events:Record<string,(event:{data:number})=>void>};
type YTApi={Player:new(target:HTMLIFrameElement,options:Options)=>FramePlayer};
declare global {interface Window {YT?:YTApi;onYouTubeIframeAPIReady?:()=>void}}
let apiPromise:Promise<YTApi>|null=null;
export function loadYouTubeAPI():Promise<YTApi> {
  if(window.YT?.Player)return Promise.resolve(window.YT);
  if(apiPromise)return apiPromise;
  apiPromise=new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>{apiPromise=null;reject(new Error('Không tải được YouTube IFrame API. Kiểm tra mạng và thử ghép lại.'));},12000);
    const previous=window.onYouTubeIframeAPIReady;
    window.onYouTubeIframeAPIReady=()=>{previous?.();clearTimeout(timer);if(window.YT)resolve(window.YT);};
    const script=document.createElement('script');script.src='https://www.youtube.com/iframe_api';script.async=true;
    script.onerror=()=>{clearTimeout(timer);apiPromise=null;reject(new Error('Không kết nối được YouTube Player API.'));};
    document.head.appendChild(script);
  });return apiPromise;
}

export async function mountPlayer(container:HTMLElement,send:(e:Telemetry)=>void,isActive=()=>true,initialVideoId='2_IweGD2uM4'):Promise<PlayerController> {
  const api=await loadYouTubeAPI();
  if(!container.isConnected||!isActive())throw new Error('Trang player đã đóng.');
  const frame=document.createElement('iframe');frame.title='YouTube Media Player';
  frame.id='wewin-youtube-iframe';
  frame.referrerPolicy='strict-origin-when-cross-origin';frame.allow='autoplay; encrypted-media; picture-in-picture';frame.allowFullscreen=true;
  frame.style.cssText='position:absolute;inset:0;width:100%;height:100%;min-height:200px;border:0;';
  const embedPath = initialVideoId ? `${initialVideoId}` : '';
  frame.src='https://www.youtube.com/embed/'+embedPath+'?enablejsapi=1&playsinline=1&origin='+encodeURIComponent(window.location.origin);
  container.replaceChildren(frame);
  let controller:PlayerController;
  const p=new api.Player(frame,{width:'100%',height:'100%',events:{
    onReady:()=>{
      if (initialVideoId) {
        try { p.cueVideoById(initialVideoId); } catch {}
      }
      controller.ready();
    },
    onStateChange:()=>controller.observe(),
    onError:(e)=>controller.error(e.data),
    onAutoplayBlocked:()=>controller.blocked()
  }});
  controller=new PlayerController(p,send);return controller;
}
