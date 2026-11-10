/* Development-only Edge tests. No fake player code is shipped in src/dist. */
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const fs=require('node:fs');const path=require('node:path');const assert=require('node:assert/strict');
const {spawn}=require('node:child_process');
const dir=process.argv[2];const servers=JSON.parse(fs.readFileSync(path.join(dir,'browser-servers.json'),'utf8'));
const results=[];
const fakePlayer=()=>{window.YT={Player:class {
 constructor(frame,opts){this.f=frame;this.o=opts;this.id='';this.s=-1;this.v=60;window.__fakeMedia=this;setTimeout(()=>opts.events.onReady({}),20);}
 cueVideoById(id){this.id=id;this.s=5;this.o.events.onStateChange({data:5});}
 loadVideoById(id){this.id=id;this.playVideo();}
 playVideo(){this.s=1;this.o.events.onStateChange({data:1});}pauseVideo(){this.s=2;this.o.events.onStateChange({data:2});}
 stopVideo(){this.s=5;this.o.events.onStateChange({data:5});}setVolume(v){this.v=v;}getVolume(){return this.v;}
 getPlayerState(){return this.s;}getVideoData(){return {video_id:this.id};}getCurrentTime(){return 0;}destroy(){}
 }};};
async function login(page,server){
 const secret=fs.readFileSync(path.join(server.directory,'admin_fixture.key'),'utf8');
 await page.getByRole('button',{name:'Đăng nhập để ghép nối'}).click();
 await page.getByPlaceholder('Nhập ADMIN_SYNC_TOKEN...').fill(secret);
 await page.getByRole('button',{name:'Lưu & Kích hoạt'}).click();
 await page.getByRole('button',{name:'Ghép nối player',exact:true}).waitFor();
 await page.getByRole('button',{name:'Ghép nối player',exact:true}).click();
}
async function waitText(page,text,timeout=15000){await page.getByText(text,{exact:true}).first().waitFor({timeout});}
async function search(page){await page.getByRole('button',{name:'Tất cả YouTube',exact:true}).click();await page.getByLabel('Từ khóa YouTube').fill('IELTS');await page.getByRole('button',{name:'Tìm video',exact:true}).click();await page.getByRole('button',{name:'Chọn video',exact:true}).first().waitFor();}
async function run(){
 const browser=await chromium.launch({channel:'msedge',headless:true});
 fs.writeFileSync(path.join(dir,'browser-environment.json'),JSON.stringify({browser:'Microsoft Edge',version:browser.version(),headless:true,isolated_profile:true},null,2));
 try {
  const context=await browser.newContext({viewport:{width:1366,height:900}});const page=await context.newPage();
  await page.goto(servers.missing.base+'/media');await page.getByText(/Chưa cấu hình YouTube API key ở backend/).waitFor();
  await page.getByLabel('Từ khóa YouTube').fill('IELTS');await page.getByRole('button',{name:'Tìm video',exact:true}).click();
  await page.getByRole('alert').filter({hasText:/Chưa cấu hình YouTube API key/}).waitFor();
  await page.screenshot({path:path.join(dir,'media-desktop.png'),fullPage:true});
  await page.setViewportSize({width:390,height:844});
  await page.waitForFunction(()=>document.querySelector('aside').getBoundingClientRect().right<=1);
  await page.evaluate(()=>scrollTo(0,0));
  await page.screenshot({path:path.join(dir,'media-mobile.png'),fullPage:true});
  const width=await page.evaluate(()=>({scroll:document.documentElement.scrollWidth,viewport:innerWidth}));
  assert.ok(width.scroll<=width.viewport,JSON.stringify(width));results.push({case:'missing-key UI / responsive 390 & 1366',status:'PASS',real_browser:true,google_api_live:false});await context.close();
  const mock=await browser.newContext({viewport:{width:1366,height:900}});await mock.addInitScript(fakePlayer);
  await mock.route(/https:\/\/(www\.)?youtube\.com\//,r=>r.abort());
  const p=await mock.newPage();await p.goto(servers.fixture.base+'/media');await p.getByText(/MÔI TRƯỜNG KIỂM THỬ/).waitFor();
  await login(p,servers.fixture);await waitText(p,'YouTube Player sẵn sàng');await search(p);
  await p.getByRole('button',{name:'Chọn video',exact:true}).first().click();await waitText(p,'Đã chọn video — chưa phát');
  for(const [button,state] of [['Play','Đang phát'],['Pause','Đã tạm dừng'],['Resume','Đang phát'],['Stop','Đã dừng']]){
   await p.getByRole('button',{name:button,exact:true}).click();await waitText(p,state);
  }
  await p.getByRole('button',{name:'Play',exact:true}).click();await waitText(p,'Đang phát');
  await p.getByRole('button',{name:'Quyền phiên MCP',exact:true}).click();
  const cap=await p.getByLabel('Quyền điều khiển phiên').inputValue();
  const sid=(await p.getByText(/^Session: /).textContent()).replace('Session: ','').trim();
  const probeDir=path.join(dir,'bridge-browser-'+Date.now());
  const code=await new Promise(resolve=>{const child=spawn(process.env.PYTHON_BIN||'python',['-B','scripts/probe_media_loopback.py','--backend',servers.fixture.base,'--snapshot',path.join(dir,'before.db'),'--directory',probeDir],{stdio:['pipe','pipe','pipe'],windowsHide:true});let output='';child.stdout.on('data',b=>output+=b);child.stderr.on('data',b=>output+=b);child.on('close',n=>{fs.writeFileSync(path.join(dir,'bridge-browser-console.log'),output);resolve(n);});child.stdin.end(JSON.stringify({session_id:sid,control_token:cap}));});
  assert.equal(code,0,'Separate bridge/browser probe failed');await waitText(p,'Đã dừng');
  await p.getByRole('button',{name:'Quyền phiên MCP',exact:true}).click();
  results.push({case:'separate run_bridge.py / FastAPI / browser WS control',status:'PASS',player:'MOCK',cloud:'MOCK_LOOPBACK',bridge_process:true});
  await p.evaluate(()=>{window.__fakeMedia.o.events.onAutoplayBlocked({});});await waitText(p,'Trình duyệt chặn tự động phát');
  await p.getByText(/Bấm nút Play trực tiếp trong khung/).first().waitFor();
  await p.evaluate(()=>{window.__fakeMedia.o.events.onError({data:100});});await waitText(p,'Player gặp lỗi');
  await p.screenshot({path:path.join(dir,'media-mock-player.png'),fullPage:true});
  await p.getByRole('button',{name:'Ngắt ghép nối',exact:true}).click();await waitText(p,'Chưa có thiết bị phát đang kết nối');
  results.push({case:'search/select/play/pause/resume/stop/autoplay/error/disconnect',status:'PASS',real_browser:true,player:'MOCK',google_api:'MOCK'});await mock.close();
  const live=await browser.newContext({viewport:{width:1366,height:900}});const lp=await live.newPage();const issues=[];lp.on('pageerror',e=>issues.push(e.name));
  await lp.goto(servers.fixture.base+'/media');await login(lp,servers.fixture);
  try{
   await waitText(lp,'YouTube Player sẵn sàng',25000);await search(lp);
   await lp.getByRole('button',{name:'Chọn video',exact:true}).first().click();await waitText(lp,'Đã chọn video — chưa phát',25000);
   await lp.getByRole('button',{name:'Play',exact:true}).click();
   await waitText(lp,'Đang phát',20000);
   const dimensions=await lp.evaluate(()=>{const host=document.getElementById('wewin-player-host').getBoundingClientRect();const frame=document.querySelector('#wewin-player-host iframe').getBoundingClientRect();return {host_width:host.width,iframe_width:frame.width,iframe_height:frame.height};});
   assert.ok(dimensions.iframe_width>=200&&dimensions.iframe_height>=200&&Math.abs(dimensions.host_width-dimensions.iframe_width)<3,JSON.stringify(dimensions));
   await lp.evaluate(()=>scrollTo(0,0));await lp.screenshot({path:path.join(dir,'media-real-playing.png'),fullPage:true});
   for(const [button,state] of [['Pause','Đã tạm dừng'],['Resume','Đang phát'],['Stop','Đã dừng']]){
    await lp.getByRole('button',{name:button,exact:true}).click();await waitText(lp,state,15000);
   }
   results.push({case:'official live IFrame sample video',status:'PASS',player:'REAL_YOUTUBE_IFRAME',google_api:'MOCK',wewin_channel_verified:false,audio_heard:false,dimensions,page_errors:issues});
  }catch(e){results.push({case:'official live IFrame sample video',status:'NOT_CONFIRMED',player:'REAL_YOUTUBE_IFRAME',google_api:'MOCK',wewin_channel_verified:false,error_type:e.name,page_errors:issues,visible_text:(await lp.locator('main').innerText()).slice(-2000)});}
  await lp.evaluate(()=>scrollTo(0,0));await lp.screenshot({path:path.join(dir,'media-real-iframe.png'),fullPage:true});await live.close();
 }catch(e){results.push({case:'browser-run',status:'FAIL',error_type:e.name,message:String(e.message).slice(0,1000)});}
 finally{await browser.close();fs.writeFileSync(path.join(dir,'browser-results.json'),JSON.stringify(results,null,2));console.log(JSON.stringify(results.map(r=>({case:r.case,status:r.status,player:r.player}))));}
}
run().catch(e=>{console.error(e.name);process.exitCode=1;});
