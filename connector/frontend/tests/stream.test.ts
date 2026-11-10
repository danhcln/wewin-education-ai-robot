import test from 'node:test';
import assert from 'node:assert/strict';
import {streamRequest} from '../src/services/stream.ts';

async function mock(run:(calls:{url:string;options?:RequestInit}[])=>Promise<void>,auth=true,code=200){
 const saved=globalThis.fetch;const calls:{url:string;options?:RequestInit}[]=[];
 globalThis.fetch=async(url,options)=>{calls.push({url:String(url),options});return new Response(JSON.stringify(String(url)==='/api/browser/session'?{authenticated:auth,role:'admin',csrf:'a'.repeat(64)}:{status:'ok',state:'CONNECTING',hardware_audio_verified:false}),{status:code});};
 try{await run(calls);}finally{globalThis.fetch=saved;}
}
test('stream status reads never start capture',()=>mock(async calls=>{await streamRequest('status');assert.deepEqual(calls.map(c=>c.url),['/api/stream/status']);assert.equal(calls[0].options?.method,'GET');}));
test('capture start requires validated cookie session and CSRF',()=>mock(async calls=>{await streamRequest('start',{endpoint:3,peer_ipv4:'10.0.0.2'});assert.deepEqual(calls.map(c=>c.url),['/api/browser/session','/api/stream/start']);assert.equal((calls[1].options?.headers as Record<string,string>)['X-WeWIN-CSRF'],'a'.repeat(64));assert.equal(calls[1].options?.credentials,'same-origin');assert.equal(calls[1].options?.cache,'no-store');}));
test('false authentication prevents capture POST',()=>mock(async calls=>{await assert.rejects(streamRequest('start',{}));assert.equal(calls.length,1);},false));
test('HTTP denial cannot be reported as successful stop',()=>mock(async()=>{await assert.rejects(streamRequest('stop',{}));},true,403));
test('accepted connection is never converted into hardware playing',()=>mock(async()=>{const r=await streamRequest<{state:string;hardware_audio_verified:boolean}>('start',{});assert.equal(r.state,'CONNECTING');assert.equal(r.hardware_audio_verified,false);}));
test('stream control never puts credentials in a URL or admin header',()=>mock(async calls=>{await streamRequest('heartbeat',{});for(const call of calls){assert.equal(call.url.includes('?'),false);assert.equal((call.options?.headers as Record<string,string>|undefined)?.Authorization,undefined);}}));
