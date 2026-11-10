/* Genuine browser policy check: authenticated test session, zero trusted gestures. */
const fs=require('node:fs'),path=require('node:path');
module.exports=async function autoplayProbe(browser,base,serverDir,dir){
 const context=await browser.newContext({viewport:{width:1366,height:900}});
 const admin=fs.readFileSync(path.join(serverDir,'admin_fixture.key'),'utf8');
 await context.addInitScript(value=>sessionStorage.setItem('wewin_admin_token',value),admin);
 const page=await context.newPage(),cdp=await context.newCDPSession(page);
 const evaluate=async expression=>(await cdp.send('Runtime.evaluate',{expression,userGesture:false,returnByValue:true})).result.value;
 const click=name=>evaluate(`Array.from(document.querySelectorAll('button')).find(button=>button.textContent.trim()===${JSON.stringify(name)}).click()`);
 const wait=async value=>{for(let i=0;i<150;i++){
  if(await evaluate(`document.body.textContent.includes(${JSON.stringify(value)})`))return;
  await new Promise(resolve=>setTimeout(resolve,200));
 }throw new Error('SETUP_TIMEOUT');};
 try{
  await page.goto(base+'/media');
  await wait('Ghép nối player');await click('Ghép nối player');
  await wait('YouTube Player sẵn sàng');
  await click('Xem video WeWIN mới nhất →');await wait('Chọn video');
  await click('Chọn video');await wait('Đã chọn video — chưa phát');
  const activation=await evaluate('navigator.userActivation.hasBeenActive');
  if(activation)throw new Error('Test unexpectedly received a trusted gesture');
  await click('Play');
  let outcome='';for(let i=0;i<100;i++){
   outcome=await evaluate(`document.body.textContent.includes('Trình duyệt chặn tự động phát')?'blocked':document.body.textContent.includes('Đang phát')?'playing':''`);
   if(outcome)break;await new Promise(resolve=>setTimeout(resolve,200));
  }
  if(!outcome)throw new Error('SETUP_TIMEOUT');
  const blocked=outcome==='blocked';
  await page.screenshot({path:path.join(dir,'live-autoplay-no-gesture.png'),fullPage:true});
  return {case:'real IFrame play without trusted browser gesture',status:blocked?'PASS':'NOT_OBSERVED',autoplay_blocked:blocked,trusted_gesture:activation,policy_overrides:false,player:'REAL_IFRAME'};
 }catch(error){return {case:'real IFrame play without trusted browser gesture',status:'FAIL',error_type:error.name,reason:error.message==='Test unexpectedly received a trusted gesture'?'HARNESS_INJECTED_ACTIVATION':'SETUP_TIMEOUT_OR_ERROR',setup_completed:false};}
 finally{await context.close();}
};
