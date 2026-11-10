import test from 'node:test';
import assert from 'node:assert/strict';
import {PlayerController} from '../src/media/player.ts';
import type {Telemetry,Command} from '../src/media/player.ts';
import {reconnectDelay,MAX_RECONNECT_ATTEMPTS} from '../src/media/reconnect.ts';
class FakeFrame {
  state=-1;id='';volume=60;calls:string[]=[];
  cueVideoById(id:string){this.id=id;this.calls.push('cue');}
  loadVideoById(id:string){this.id=id;this.calls.push('load');}
  playVideo(){this.calls.push('play');}pauseVideo(){this.calls.push('pause');}stopVideo(){this.calls.push('stop');}
  setVolume(n:number){this.volume=n;}getVolume(){return this.volume;}getPlayerState(){return this.state;}
  getVideoData(){return {video_id:this.id};}destroy(){}
}
function setup(){const f=new FakeFrame();const events:Telemetry[]=[];const c=new PlayerController(f,e=>events.push(e));return {f,c,events};}
function cmd(action:string,seq=1):Command{return {command_id:'command-'+seq,seq,action,video_id:'M7lc1UVf-VE',expires_at_ms:Date.now()+10000};}
test('select cues without claiming playing',()=>{const {c,f,events}=setup();c.command(cmd('select'));assert.deepEqual(f.calls,['cue']);assert.equal(events.length,1);assert.equal(events[0].type,'received');f.state=5;c.observe();assert.equal(events.at(-1)?.state,'VIDEO_SELECTED');});
test('play only confirmed after IFrame state 1',()=>{const {c,f,events}=setup();f.id='M7lc1UVf-VE';c.command(cmd('play'));assert.equal(events[0].type,'received');f.state=1;c.observe();assert.equal(events.at(-1)?.state,'PLAYING');});
test('pause and resume use official methods and real state',()=>{const {c,f,events}=setup();f.id='M7lc1UVf-VE';c.command(cmd('pause'));f.state=2;c.observe();assert.equal(events.at(-1)?.state,'PAUSED');c.command(cmd('resume',2));assert.deepEqual(f.calls,['pause','play']);f.state=1;c.observe();assert.equal(events.at(-1)?.state,'PLAYING');});
test('stop state persists across subsequent samples',()=>{const {c,f,events}=setup();f.id='M7lc1UVf-VE';f.state=1;c.observe();c.command(cmd('stop'));f.state=5;c.observe();c.observe();assert.equal(events.at(-1)?.state,'STOPPED');});
test('autoplay blocked does not disappear on a cue sample',()=>{const {c,f,events}=setup();f.id='M7lc1UVf-VE';c.command(cmd('play'));c.blocked();f.state=5;c.observe();assert.equal(events.at(-1)?.state,'AUTOPLAY_BLOCKED');f.state=1;c.observe();assert.equal(events.at(-1)?.state,'PLAYING');});
test('video unavailable remains error',()=>{const {c,f,events}=setup();f.id='M7lc1UVf-VE';c.command(cmd('select'));c.error(100);f.state=5;c.observe();assert.equal(events.at(-1)?.state,'ERROR');assert.equal(events.at(-1)?.error_code,100);});
test('duplicate sequence never replays',()=>{const {c,f}=setup();assert.equal(c.command(cmd('select')),true);assert.equal(c.command(cmd('play')),false);assert.deepEqual(f.calls,['cue']);});
test('expired request never executes',()=>{const {c,f}=setup();const x=cmd('play');x.expires_at_ms=1;assert.equal(c.command(x),false);assert.deepEqual(f.calls,[]);});
test('URL or shell command cannot be used as Video ID',()=>{const {c,f}=setup();const x=cmd('select');x.video_id='https://example.org';assert.equal(c.command(x),false);assert.deepEqual(f.calls,[]);});
test('old video telemetry cannot confirm new selection',()=>{const {c,f,events}=setup();c.command(cmd('select'));f.id='aaaaaaaaaaa';f.state=1;c.observe();assert.equal(events.length,1);});
test('volume confirmed from actual getter',()=>{const {c,f,events}=setup();f.id='M7lc1UVf-VE';f.state=2;c.command({...cmd('volume'),volume:35});c.observe();assert.equal(events.at(-1)?.volume,35);});
test('reconnect uses capped exponential backoff',()=>{assert.deepEqual([0,1,2,3,4,9].map(reconnectDelay),[1000,2000,4000,8000,15000,15000]);});
test('reconnect budget is finite and negative attempts are bounded',()=>{assert.equal(MAX_RECONNECT_ATTEMPTS,12);assert.equal(reconnectDelay(-100),1000);});
