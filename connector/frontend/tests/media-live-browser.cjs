/* Explicit live YouTube test. Use only a copied DB and temporary admin credential. */
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {spawn}=require('node:child_process');
const dir=process.argv[2],base=process.argv[3],serverDir=process.argv[4]||path.join(dir,'live-server');
const results=[];
async function text(page,value,timeout=30000){await page.getByText(value,{exact:true}).first().waitFor({timeout});}
async function main(){
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const context=await browser.newContext({viewport:{width:1366,height:900}});
 const page=await context.newPage(),issues=[];page.on('pageerror',e=>issues.push(e.name));
 fs.writeFileSync(path.join(dir,'live-browser-environment.json'),JSON.stringify({browser:'Microsoft Edge',version:browser.version(),headless:true,profile:'isolated',autoplay_bypass:false},null,2));
 try{
  await page.goto(base+'/media');
  const admin=fs.readFileSync(path.join(serverDir,'admin_fixture.key'),'utf8');
  await page.getByRole('button',{name:'Đăng nhập để ghép nối'}).click();
  await page.getByPlaceholder('Nhập ADMIN_SYNC_TOKEN...').fill(admin);
  await page.getByRole('button',{name:'Lưu & Kích hoạt'}).click();
  await page.getByRole('button',{name:'Ghép nối player',exact:true}).click();
  await text(page,'YouTube Player sẵn sàng');
  await page.getByRole('button',{name:'Xem video WeWIN mới nhất →'}).click();
  await page.getByRole('button',{name:'Chọn video',exact:true}).first().waitFor();
  const count=await page.getByRole('button',{name:'Chọn video',exact:true}).count();assert.ok(count>=2);
  await page.getByText('Channel ID đã xác minh qua API',{exact:true}).waitFor();
  results.push({case:'UI live verified WeWIN uploads list',status:'PASS',videos:count});
  await page.getByRole('button',{name:'Chọn video',exact:true}).first().click();
  await text(page,'Đã chọn video — chưa phát');
  await page.getByRole('button',{name:'Play',exact:true}).click();
  try{await text(page,'Đang phát',20000);}
  catch(error){
   const blocked=await page.getByText('Trình duyệt chặn tự động phát',{exact:true}).isVisible();
   if(!blocked)throw error;
   results.push({case:'native browser autoplay blocked callback',status:'PASS'});
   await page.frameLocator('#wewin-player-host iframe').locator('button.ytp-large-play-button').click();
   await text(page,'Đang phát',20000);
  }
  const position=await page.evaluate(()=>new Promise(resolve=>{
   const frame=document.querySelector('#wewin-player-host iframe');
   const timer=setTimeout(()=>{window.removeEventListener('message',handler);resolve({observed:false});},5000);
   function handler(event){if(event.source!==frame.contentWindow)return;let data;try{data=typeof event.data==='string'?JSON.parse(event.data):event.data;}catch{return;}
    if(data?.event==='infoDelivery'&&data.info?.videoData?.video_id){clearTimeout(timer);window.removeEventListener('message',handler);resolve({observed:true,video_id:data.info.videoData.video_id});}}
   window.addEventListener('message',handler);
  }));
  await page.waitForTimeout(3000);
  const dimensions=await page.frameLocator('#wewin-player-host iframe').locator('body').evaluate(body=>{
   const box=body.querySelector('.html5-video-player')?.getBoundingClientRect();
   const video=body.querySelector('video');return {viewport_width:innerWidth,viewport_height:innerHeight,player_width:box?.width,player_height:box?.height,current_time:video?.currentTime,video_width:video?.getBoundingClientRect().width};
  });
  assert.ok(dimensions.viewport_width>=200&&dimensions.player_width>=200,JSON.stringify(dimensions));
  await page.screenshot({path:path.join(dir,'live-wewin-playing.png'),fullPage:true});
  for(const [button,state] of [['Pause','Đã tạm dừng'],['Resume','Đang phát'],['Stop','Đã dừng']]){
   await page.getByRole('button',{name:button,exact:true}).click();await text(page,state);await page.waitForTimeout(1100);
  }
  results.push({case:'WeWIN real IFrame select/play/pause/resume/stop',status:'PASS',iframe:position,dimensions,physical_audio_heard:false});
  await page.getByRole('button',{name:'Chọn video',exact:true}).nth(1).click();await text(page,'Đã chọn video — chưa phát');
  await page.getByRole('button',{name:'Play',exact:true}).click();await text(page,'Đang phát',20000);
  results.push({case:'change to second real WeWIN video',status:'PASS'});
  await page.getByRole('button',{name:'Quyền phiên MCP',exact:true}).click();
  const cap=await page.getByLabel('Quyền điều khiển phiên').inputValue();
  const sid=(await page.getByText(/^Session: /).textContent()).replace('Session: ','').trim();
  await page.getByRole('button',{name:'Quyền phiên MCP',exact:true}).click();
  await page.waitForTimeout(3000);
  const probeDir=path.join(dir,'live-bridge-'+Date.now());
  const exit=await new Promise(resolve=>{
   const child=spawn(process.env.PYTHON_BIN||'python',['-B','scripts/probe_media_loopback.py','--backend',base,'--snapshot',path.join(dir,'before.db'),'--directory',probeDir,'--verify-youtube-tools'],{stdio:['pipe','pipe','pipe'],windowsHide:true});
   let output='';child.stdout.on('data',b=>output+=b);child.stderr.on('data',b=>output+=b);
   child.on('close',code=>{fs.writeFileSync(path.join(dir,'live-bridge-console.log'),output);resolve(code);});
   child.stdin.end(JSON.stringify({session_id:sid,control_token:cap}));
  });
  assert.equal(exit,0,'Separate bridge live verification failed');
  results.push({case:'all four MCP tools / separate run_bridge / actual WeWIN IFrame',status:'PASS',cloud:'MOCK_LOOPBACK',youtube_api:'LIVE',player:'REAL_IFRAME'});
  await page.close();
  let disconnected=false;
  for(let i=0;i<50;i++){
   const response=await context.request.post(base+'/api/media/tool',{data:{tool:'youtube_get_status',arguments:{session_id:sid,control_token:cap}}});
   if((await response.json()).state==='PLAYER_DISCONNECTED'){disconnected=true;break;}await new Promise(r=>setTimeout(r,100));
  }
  assert.ok(disconnected);results.push({case:'tab close disconnects paired player',status:'PASS'});
  results.push(await require('./media-autoplay-live.cjs')(browser,base,serverDir,dir));
  if(!results.some(x=>x.case==='native browser autoplay blocked callback'))results.push({case:'native browser autoplay blocked callback',status:'NOT_OBSERVED',mock_regression:'covered separately'});
 }catch(error){
  results.push({case:'live-browser-run',status:'FAIL',error_type:error.name,message:String(error.message).slice(0,400)});
  if(!page.isClosed())await page.screenshot({path:path.join(dir,'live-browser-failure.png'),fullPage:true});
 }finally{
  await browser.close();fs.writeFileSync(path.join(dir,'live-browser-results.json'),JSON.stringify({results,page_errors:issues},null,2));
  console.log(JSON.stringify(results));
  if(results.some(result=>result.status==='FAIL'))process.exitCode=1;
 }
}
main().catch(e=>{console.error(e.name);process.exitCode=1;});
