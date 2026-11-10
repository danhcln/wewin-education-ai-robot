import test from 'node:test';
import assert from 'node:assert/strict';
import {voiceMedia} from '../src/services/voiceMedia.ts';
import {PlayerController} from '../src/media/player.ts';
async function mock(run:(calls:{url:string;options?:RequestInit}[])=>Promise<void>,auth=true,code=200){
 const saved=globalThis.fetch;const calls:{url:string;options?:RequestInit}[]=[];
 globalThis.fetch=async(url,options)=>{calls.push({url:String(url),options});return new Response(JSON.stringify(String(url)==='/api/browser/session'?{authenticated:auth,role:'admin',csrf:'a'.repeat(64)}:{status:'intent_accepted',playback_confirmed:false}),{status:code});};
 try{await run(calls);}finally{globalThis.fetch=saved;}
}
test('voice status never starts a session',()=>mock(async calls=>{await voiceMedia('status');assert.deepEqual(calls.map(c=>c.url),['/api/media/voice/status']);assert.equal(calls[0].options?.method,'GET');}));
test('voice commands require validated browser cookie CSRF',()=>mock(async calls=>{await voiceMedia('action',{action:'pause',request_id:'test-request'});assert.equal(calls.length,2);assert.equal((calls[1].options?.headers as Record<string,string>)['X-WeWIN-CSRF'],'a'.repeat(64));assert.equal(calls[1].options?.credentials,'same-origin');}));
test('failed login cannot send a voice command',()=>mock(async calls=>{await assert.rejects(voiceMedia('action',{}));assert.equal(calls.length,1);},false));
test('HTTP failure never claims playing',()=>mock(async()=>{await assert.rejects(voiceMedia('action',{}));},true,403));
test('queued intent is not browser or physical output ACK',()=>mock(async()=>{const r=await voiceMedia<{playback_confirmed:boolean}>('action',{});assert.equal(r.playback_confirmed,false);}));
test('voice setup does not transport descriptors or tokens in URL',()=>mock(async calls=>{await voiceMedia('approve',{device_id:'a'.repeat(32),fingerprint:'b'.repeat(64)});for(const c of calls){assert.equal(c.url.includes('?'),false);assert.equal((c.options?.headers as Record<string,string>|undefined)?.Authorization,undefined);}}));
function player(){const events:Record<string,unknown>[]=[];let state=-1,id='';const frame={cueVideoById(v:string){id=v;state=5;},loadVideoById(v:string){id=v;state=1;},playVideo(){state=1;},pauseVideo(){state=2;},stopVideo(){state=-1;id='';},setVolume(){},getVolume(){return 60;},getPlayerState(){return state;},getVideoData(){return {video_id:id};},destroy(){}};return {controller:new PlayerController(frame,e=>events.push({...e})),events};}
test('browser rejects obsolete media generation even with a newer transport sequence',()=>{const {controller}=player();const command={command_id:'a',seq:1,action:'select',video_id:'2_IweGD2uM4',expires_at_ms:Date.now()+10000,media_generation:4};assert.equal(controller.command(command),true);assert.equal(controller.command({...command,seq:2,media_generation:3}),false);});
test('browser state ACK carries media generation',()=>{const {controller,events}=player();controller.command({command_id:'a',seq:1,action:'select',video_id:'2_IweGD2uM4',expires_at_ms:Date.now()+10000,media_generation:4});controller.observe();assert.equal(events.at(-1)?.media_generation,4);assert.equal(events.at(-1)?.state,'VIDEO_SELECTED');});
test('stop after cancellation before load can ACK an actually unstarted frame',()=>{const {controller,events}=player();controller.command({command_id:'a',seq:1,action:'stop',video_id:'2_IweGD2uM4',expires_at_ms:Date.now()+10000,media_generation:5});controller.observe();assert.equal(events.at(-1)?.state,'STOPPED');assert.equal(events.at(-1)?.media_generation,5);});
