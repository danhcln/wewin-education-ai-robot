"""Ephemeral Chrome + LAN simulator proof. QA 8002/8011 only, no hardware.

Bootstrap capability stays in memory; never printed, logged or screenshotted.
"""
import asyncio
import json
from pathlib import Path
import sys
from uuid import uuid4
import httpx
import websockets
from playwright.sync_api import sync_playwright,expect

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.staging_connection_suite import initialize,receive_turn
from ai_server.audio import encode_audio
from ai_server.providers import Providers
from ai_server.settings import Settings

OUT=ROOT/'artifacts/independent-migration/end-to-end'
PORTAL='http://127.0.0.1:8002';EDGE='http://192.168.2.10:8013'


def browser_flow():
    suffix=uuid4().hex[:12];device='sim-independent-'+suffix;client_id='client-'+suffix;errors=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='chrome',headless=True)
        try:
            context=browser.new_context(viewport={'width':1440,'height':1100});page=context.new_page()
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto(PORTAL+'/robots');page.get_by_label('Tên đăng nhập',exact=True).fill('qa-admin');page.get_by_label('Mật khẩu',exact=True).fill('WeWIN-QA-only-2026!');page.get_by_role('button',name='Đăng nhập',exact=True).click()
            page.get_by_role('button',name='+ Add Robot WeWIN',exact=True).click();dialog=page.get_by_role('dialog')
            dialog.get_by_label('Tên Robot WeWIN',exact=True).fill('WeWIN independent QA '+suffix)
            dialog.get_by_label('Device-ID dự kiến',exact=True).fill(device);dialog.get_by_label('Client-ID dự kiến',exact=True).fill(client_id)
            dialog.get_by_label('Bằng chứng quyền quản lý',exact=True).fill('QA operator owns this simulator only; no physical device enrollment')
            dialog.get_by_role('checkbox').check()
            with page.expect_response(lambda r:r.url.endswith('/managed-robots') and r.request.method=='POST') as created:
                dialog.get_by_role('button',name='Xác nhận tạo đăng ký WeWIN',exact=True).click()
            assert created.value.ok;rid=created.value.json()['id']
            expect(page.get_by_label('Chọn Robot cần quản lý')).to_have_value(rid)
            expect(page.get_by_role('heading',name='WeWIN Device Gateway',exact=True)).to_be_visible()
            page.screenshot(path=str(OUT/'registration.png'),full_page=True)
            page.get_by_role('link',name='Vai trò trợ lý AI',exact=True).click()
            page.locator('article.role-card').filter(has=page.get_by_role('heading',name='WeWIN English Teacher',exact=True)).get_by_role('button',name='Xem vai trò',exact=True).click()
            page.get_by_label('Robot nhận vai trò').select_option(rid)
            page.get_by_role('button',name='Áp dụng cho Robot — xem candidate',exact=True).click();dialog=page.get_by_role('dialog')
            expect(dialog).to_contain_text('Agent staging:');page.screenshot(path=str(OUT/'review-role.png'),full_page=True)
            with page.expect_response(lambda r:'/config/apply' in r.url and r.request.method=='POST',timeout=180000) as applied:
                dialog.get_by_role('button',name='Áp dụng WeWIN AI Server',exact=True).click()
            assert applied.value.ok and applied.value.json()['sync_state']=='server_applied_verified'
            page.goto(PORTAL+'/robots/'+rid);page.get_by_role('button',name='Cấp bootstrap WeWIN',exact=True).click()
            dialog=page.get_by_role('dialog');expect(dialog).to_contain_text('hiển thị một lần')
            with page.expect_response(lambda r:r.url.endswith('/device-gateway/provision') and r.request.method=='POST') as issued:
                dialog.get_by_role('button',name='Xác nhận thao tác Gateway',exact=True).click()
            assert issued.value.ok;receipt=issued.value.json()
            expect(page.get_by_label('Bootstrap URL bí mật')).to_be_visible()
            page.get_by_role('button',name='Đã lưu an toàn · đóng',exact=True).click()
            expect(page.get_by_label('Bootstrap URL bí mật')).to_have_count(0)
            page.get_by_role('tab',name='Cloud / MCP',exact=True).click()
            expect(page.get_by_role('heading',name='WeWIN Agent Runtime / Readback',exact=True)).to_be_visible()
            expect(page.get_by_role('button',name='Chọn WeWIN AI staging',exact=True)).to_have_count(0)
            page.screenshot(path=str(OUT/'wewin-owned-gateway.png'),full_page=True)
            assert not errors,errors
            csrf=context.request.get(PORTAL+'/api/portal/session').json()['csrf']
            context.request.post(PORTAL+'/api/portal/logout',headers={'Origin':PORTAL,'X-WeWIN-CSRF':csrf})
            context.close()
        finally:browser.close()
    return rid,device,client_id,receipt


async def transport(rid,device,client_id,receipt):
    checks=['chrome_add_robot','chrome_review_confirm_role_apply','chrome_one_time_bootstrap','chrome_first_party_target_no_legacy_cloud']
    key=(ROOT/'artifacts/independent-migration/qa/admin-key').read_text().strip()
    owner={'Authorization':'Bearer '+key,'X-WeWIN-Owner':'qa-admin','X-WeWIN-Tenant':'wewin-local'}
    async with httpx.AsyncClient(base_url=PORTAL+'/api/portal',timeout=150,trust_env=False) as portal,httpx.AsyncClient(base_url='http://127.0.0.1:8011',headers=owner,timeout=150,trust_env=False) as admin,httpx.AsyncClient(trust_env=False,timeout=15) as network:
        login=await portal.post('/auth/login',headers={'Origin':PORTAL},json={'username':'qa-admin','password':'WeWIN-QA-only-2026!'});login.raise_for_status()
        portal.headers.update({'Origin':PORTAL,'X-WeWIN-CSRF':login.json()['csrf']})
        async def status():
            r=await portal.get(f'/robots/{rid}/device-gateway');r.raise_for_status();return r.json()
        async def apply_role(target,role_id):
            current=(await portal.get(f'/robots/{target}/config')).json();role=(await portal.get('/roles/'+role_id)).json()
            candidate=await portal.post(f'/robots/{target}/roles/{role_id}/candidate',json={'version':current['version'],'role_version':role['version']});candidate.raise_for_status()
            result=await portal.post(f'/robots/{target}/config/apply',json={'candidate_id':candidate.json()['id'],'confirmed':True});result.raise_for_status()
            assert result.json()['sync_state']=='server_applied_verified' and not result.json()['robot_applied']
            return (await admin.get('/v1/agents/'+candidate.json()['capabilities']['agent_reference'])).json()
        native={'Device-Id':device,'Client-Id':client_id,'Activation-Version':'2'}
        async def bootstrap(url):return await network.post(url,headers=native,json={'application':{'version':'wewin-explicit-simulator'},'capabilities':{'mcp':True,'websocket':True,'audio_format':'opus','sample_rate':16000,'channels':1,'frame_duration':60}})
        try:
            assert (await network.get(EDGE+'/v1/agents')).status_code==404
            assert (await network.get(EDGE+'/docs')).status_code==404
            assert (await network.post(receipt['bootstrap_url'],headers={**native,'Client-Id':'wrong-client'},json={})).status_code==403
            boot=await bootstrap(receipt['bootstrap_url']);assert boot.status_code==200,'Bootstrap rejected (credential URL suppressed)';data=boot.json()
            assert 'firmware' not in data and 'activation' not in data and data['websocket']['url']==EDGE.replace('http://','ws://')+'/xiaozhi/v1/'
            checks+=['lan_authenticated_ota_no_firmware','lan_management_routes_absent','wrong_client_rejected']
            headers={'Authorization':'Bearer '+data['websocket']['token'],**native,'Protocol-Version':'1'};url=data['websocket']['url']
            snapshot=(await admin.get('/v1/agents/'+receipt['agent_id'])).json()
            engines=Providers(Settings())
            try:
                async with websockets.connect(url,additional_headers=headers,proxy=None) as ws:
                    assert not (await status())['device']['online']
                    session=await initialize(ws);assert (await status())['device']['online'];checks+=['online_only_after_authenticated_hello','wsv1_mcp_discovery_and_ping']
                    await engines.load();wave,rate=await engines.synthesize('What is the English word for a book?',{'voice':'M1','language':'en-US','speech_rate':1})
                    await ws.send(json.dumps({'type':'listen','state':'start','mode':'manual','session_id':session}))
                    for frame in encode_audio(wave,rate,16000):await ws.send(frame);await asyncio.sleep(.06)
                    await ws.send(json.dumps({'type':'listen','state':'stop','session_id':session}))
                    await receive_turn(ws,OUT/'teacher-audio',snapshot);checks+=['real_local_asr_llm_tts_opus_over_lan_simulator']
                    snapshot=await apply_role(rid,'builtin-consultant')
                    await ws.send(json.dumps({'type':'listen','state':'detect','text':'WeWIN có những khóa học nào?'}))
                    result=await receive_turn(ws,OUT/'consultant',snapshot);assert 'wewin_get_programs' in result['metadata']['tools'];checks+=['portal_role_switch_next_turn_readback','public_wewin_mcp']
                    await apply_role(rid,'builtin-english-teacher');checks+=['controlled_role_restore_new_revision']
                assert not (await status())['device']['online']
                async with websockets.connect(url,additional_headers=headers,proxy=None) as ws:
                    assert await initialize(ws)!=session;checks+=['reconnect_new_authenticated_session']
                second=await portal.post('/managed-robots',json={'name':'Independent binding target','device_id':'sim-binding-'+uuid4().hex,'client_id':'client-'+uuid4().hex,'kind':'simulator','ownership_evidence':'Owned disposable simulator binding test','ownership_attested':True,'confirmed':True});second.raise_for_status()
                target=await apply_role(second.json()['id'],'builtin-english-teacher')
                bound=await portal.post(f'/robots/{rid}/device-gateway/binding',json={'confirmed':True,'agent_id':target['agent_id'],'expected_binding_version':1});bound.raise_for_status()
                state=await status();assert state['device']['agent_id']==target['agent_id'] and state['device']['binding_version']==2 and not state['error']
                async def rejected(old_headers):
                    try:
                        async with websockets.connect(url,additional_headers=old_headers,proxy=None):raise AssertionError('Stale/revoked credential admitted')
                    except websockets.exceptions.InvalidStatus:pass
                await rejected(headers);checks+=['binding_cas_portal_and_gateway_readback','old_ws_credential_rejected_after_binding']
                rotated=await portal.post(f'/robots/{rid}/device-gateway/rotate',json={'confirmed':True,'expected_binding_version':2,'agent_id':''});rotated.raise_for_status()
                assert (await bootstrap(receipt['bootstrap_url'])).status_code==403
                fresh=await bootstrap(rotated.json()['bootstrap_url']);assert fresh.status_code==200,'Rotated bootstrap rejected (credential URL suppressed)';headers['Authorization']='Bearer '+fresh.json()['websocket']['token']
                async with websockets.connect(url,additional_headers=headers,proxy=None) as ws:
                    await initialize(ws)
                    revoked=await portal.post(f'/robots/{rid}/device-gateway/revoke',json={'confirmed':True});revoked.raise_for_status()
                    try:await ws.recv();raise AssertionError('Revoke did not close live socket')
                    except websockets.exceptions.ConnectionClosed:pass
                await rejected(headers);assert (await bootstrap(rotated.json()['bootstrap_url'])).status_code==403
                checks+=['rotation_invalidates_old_bootstrap','revocation_closes_socket_and_blocks_reconnect']
            finally:engines.cpu.shutdown(wait=True,cancel_futures=True)
            result={'checks':checks,'check_count':len(checks),'portal':PORTAL,'ai':'http://127.0.0.1:8011','device_edge':EDGE,'evidence':'HOST_LAN_SIMULATOR_REAL_ENGINES','physical_device_verified':False,'physical_audio_verified':False,'physical_role_switch_verified':False,'bootstrap_secret_persisted':False,'device':device,'robot_record':rid,'build':(await admin.get('/health')).json()['build']}
            (OUT/'results.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps({'checks_passed':len(checks),'evidence':result['evidence'],'physical_verified':False}))
        finally:
            await portal.post(f'/robots/{rid}/device-gateway/revoke',json={'confirmed':True})
            await portal.post('/logout')


if __name__=='__main__':
    OUT.mkdir(parents=True,exist_ok=True)
    asyncio.run(transport(*browser_flow()))
