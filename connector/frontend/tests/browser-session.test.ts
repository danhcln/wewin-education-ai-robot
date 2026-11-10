import test from 'node:test';
import assert from 'node:assert/strict';
import {browserLogin,browserSession,clearBrowserSession,getBrowserCsrf,BrowserSessionError} from '../src/services/browserSession.ts';
async function withResponse(value:unknown,status:number,action:()=>Promise<void>){const original=globalThis.fetch;globalThis.fetch=async()=>new Response(JSON.stringify(value),{status});try{clearBrowserSession();await action();}finally{globalThis.fetch=original;clearBrowserSession();}}
test('cookie session login requires authenticated true',()=>withResponse({authenticated:false,role:'admin',csrf:'a'.repeat(64)},200,async()=>{await assert.rejects(browserLogin('synthetic-token'),BrowserSessionError);assert.equal(getBrowserCsrf(),'');}));
test('cookie session login rejects guest role',()=>withResponse({authenticated:true,role:'guest',csrf:'a'.repeat(64)},200,async()=>{await assert.rejects(browserLogin('synthetic-token'),BrowserSessionError);}));
test('cookie session refuses malformed CSRF response',()=>withResponse({authenticated:true,role:'admin',csrf:'bad'},200,async()=>{await assert.rejects(browserLogin('synthetic-token'),BrowserSessionError);}));
test('valid cookie response only keeps CSRF in module memory',()=>withResponse({authenticated:true,role:'admin',csrf:'a'.repeat(64)},200,async()=>{assert.equal((await browserLogin('synthetic-token')).authenticated,true);assert.equal(getBrowserCsrf(),'a'.repeat(64));}));
test('expired cookie does not authenticate',()=>withResponse({detail:'expired'},401,async()=>{await assert.rejects(browserSession(),BrowserSessionError);assert.equal(getBrowserCsrf(),'');}));
