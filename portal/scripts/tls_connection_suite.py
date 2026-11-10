"""Real private-CA HTTPS/WSS + owned simulator on disposable AI8011 only.
No credentials are printed, written to results or included in URL exceptions.
"""
import asyncio
import argparse
import json
from pathlib import Path
import socket
import ssl
import sys
from uuid import uuid4
import httpx
import numpy as np
import soundfile as sf
import websockets

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.staging_connection_suite import initialize
from ai_server.audio import encode_audio,opus_library
from ai_server.models import AgentProfile

OUT=ROOT/'artifacts/real-connection-gate';CERT=OUT/'tls-private';HOST='192.168.2.10';ORIGIN='https://'+HOST+':8014'


def tls_probe():
    checks=[];ctx=ssl.create_default_context(cafile=str(CERT/'ca.pem'))
    def handshake(context,hostname=HOST,port=8014):
        with socket.create_connection((HOST,port),timeout=4) as plain:
            with context.wrap_socket(plain,server_hostname=hostname) as secure:return {'version':secure.version(),'cipher':secure.cipher()[0]}
    negotiated=handshake(ctx);checks.append('trusted_chain_and_ip_san')
    for context,hostname,port,label in [(ssl.create_default_context(),HOST,8014,'untrusted_ca_rejected'),(ctx,'wrong-host.invalid',8014,'hostname_mismatch_rejected'),(ctx,HOST,8015,'expired_certificate_rejected')]:
        try:handshake(context,hostname,port);raise AssertionError(label+' FAILED')
        except ssl.SSLCertVerificationError:checks.append(label)
    tls12=ssl.create_default_context(cafile=str(CERT/'ca.pem'));tls12.minimum_version=tls12.maximum_version=ssl.TLSVersion.TLSv1_2
    assert handshake(tls12)['version']=='TLSv1.2';checks.append('tls12_supported')
    old=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT);old.check_hostname=False;old.verify_mode=ssl.CERT_NONE
    old.minimum_version=old.maximum_version=ssl.TLSVersion.TLSv1_1;old.set_ciphers('ALL:@SECLEVEL=0')
    try:handshake(old);raise AssertionError('TLS1.1 admitted')
    except ssl.SSLError:checks.append('tls11_rejected')
    return checks,negotiated


async def main(args):
    checks,negotiated=await asyncio.to_thread(tls_probe)
    ctx=ssl.create_default_context(cafile=str(CERT/'ca.pem'))
    key=(ROOT/'.secrets/ai_admin_key' if args.backend==8010 else OUT/'qa/admin-key').read_text().strip();scoped={'Authorization':'Bearer '+key,'X-WeWIN-Owner':'tls-gate','X-WeWIN-Tenant':'wewin-staging'}
    suffix=uuid4().hex;agent='tls_'+suffix;device='sim-tls-'+suffix;client_id='client-'+suffix
    async with httpx.AsyncClient(base_url='http://127.0.0.1:'+str(args.backend),headers=scoped,timeout=150,trust_env=False) as admin,httpx.AsyncClient(verify=ctx,trust_env=False,timeout=15) as native:
        health=(await admin.get('/health')).json();assert not health['real_device_enrollment_enabled']
        profile=AgentProfile(ai_model='qwen3:4b',language='en-US',greeting='Hello. Win is ready.').model_dump()
        applied=await admin.put('/v1/agents/'+agent,json={'config':profile,'expected_revision':0,'operation_id':'tls-'+suffix});applied.raise_for_status()
        enrolled=await admin.post('/v1/device-provisions',json={'device_id':device,'client_id':client_id,'agent_id':agent,'kind':'simulator','ownership_attested':True,'ownership_evidence':'TLS gate simulator owned by WeWIN test operator','confirmed':True,'ttl_seconds':3600});enrolled.raise_for_status();url=enrolled.json()['bootstrap_url'];assert url.startswith(ORIGIN+'/')
        headers={'Device-Id':device,'Client-Id':client_id,'Activation-Version':'2'}
        async def boot(target):
            response=await native.post(target,headers=headers,json={'application':{'version':'tls-explicit-simulator'},'capabilities':{'websocket':True,'mcp':True,'sample_rate':16000,'frame_duration':60}})
            return response
        async def diagnostic():return (await admin.get('/v1/devices/'+device+'/diagnostics')).json()
        try:
            assert (await native.get(ORIGIN+'/v1/agents')).status_code==404
            assert (await native.get(ORIGIN+'/docs')).status_code==404
            assert (await native.post(url,headers={**headers,'Client-Id':'wrong-client'},json={})).status_code==403
            other=await admin.get('/v1/devices/'+device+'/diagnostics',headers={**scoped,'X-WeWIN-Owner':'other-owner'});assert other.status_code==403
            checks+=['management_not_exposed','wrong_client_rejected','owner_tenant_enforced']
            response=await boot(url);assert response.status_code==200,'Bootstrap failed; credential URL suppressed';value=response.json()
            assert 'firmware' not in value and 'activation' not in value and value['websocket']['url']==ORIGIN.replace('https://','wss://')+'/xiaozhi/v1/'
            checks+=['ota_no_firmware_no_activation','https_bootstrap_to_same_authority_wss']
            wsheaders={**headers,'Protocol-Version':'1','Authorization':'Bearer '+value['websocket']['token']};socket_url=value['websocket']['url']
            async with websockets.connect(socket_url,additional_headers=wsheaders,ssl=ctx,proxy=None) as ws:
                try:await asyncio.wait_for(ws.recv(),14);raise AssertionError('Missing HELLO accepted')
                except websockets.exceptions.ConnectionClosed:checks.append('missing_hello_timeout')
            async with websockets.connect(socket_url,additional_headers=wsheaders,ssl=ctx,proxy=None) as ws:
                assert not (await diagnostic())['online'];session=await initialize(ws);assert (await diagnostic())['online']
                await ws.send(json.dumps({'type':'listen','state':'detect','text':'Hi Lily'}));frames=[]
                while True:
                    item=await asyncio.wait_for(ws.recv(),90)
                    if isinstance(item,bytes):frames.append(item);continue
                    event=json.loads(item)
                    if event['type']=='error':raise AssertionError('Greeting provider error')
                    if event.get('type')=='tts' and event.get('state')=='stop':break
                assert frames;decoder=opus_library().Decoder(24000,1);pcm=np.frombuffer(b''.join(decoder.decode(f,1440,False) for f in frames),dtype='<i2')
                sf.write(OUT/'tls-greeting.wav',pcm,24000,subtype='PCM_16')
                await ws.send(json.dumps({'type':'listen','state':'start','mode':'manual'}))
                for frame in encode_audio(pcm.astype(np.float32)/32768,24000,16000):await ws.send(frame)
                await ws.send(json.dumps({'type':'abort'}));assert json.loads(await ws.recv())['state']=='stop'
                checks+=['wss_authenticated_hello_mcp_ping','live_socket_diagnostics','tts_opus24k_downlink_decode','opus16k_uplink_decoder_and_abort']
            async with websockets.connect(socket_url,additional_headers=wsheaders,ssl=ctx,proxy=None) as ws:
                assert await initialize(ws)!=session;checks.append('wss_reconnect_new_session')
                rotated=await admin.post('/v1/devices/'+device+'/credentials/rotate',json={'confirmed':True,'expected_binding_version':1});rotated.raise_for_status()
                try:await ws.recv();raise AssertionError('Rotation did not close socket')
                except websockets.exceptions.ConnectionClosed:pass
            assert (await boot(url)).status_code==403
            fresh=await boot(rotated.json()['bootstrap_url']);assert fresh.status_code==200,'Rotated bootstrap failed; URL suppressed'
            wsheaders['Authorization']='Bearer '+fresh.json()['websocket']['token'];checks.append('rotation_invalidates_bootstrap_and_closes_socket')
            async with websockets.connect(socket_url,additional_headers=wsheaders,ssl=ctx,proxy=None) as ws:
                await initialize(ws);assert (await admin.post('/v1/devices/'+device+'/revoke',json={'confirmed':True})).status_code==200
                try:await ws.recv();raise AssertionError('Revoke did not close socket')
                except websockets.exceptions.ConnectionClosed:pass
            try:
                async with websockets.connect(socket_url,additional_headers=wsheaders,ssl=ctx,proxy=None):raise AssertionError('Revoked bearer admitted')
            except websockets.exceptions.InvalidStatus:pass
            checks.append('revocation_denies_wss_reconnect')
            result={'checks':checks,'total':len(checks),'negotiated':negotiated,'origin':ORIGIN,'backend':args.backend,'new_owned_simulator_only':True,'build':health['build'],'opus_frames':len(frames),'physical_verified':False,'robot_network_reachability':'NOT_TESTED','robot_certificate_trust':'NOT_TESTED','ca_installed':False}
            (OUT/('tls-results-'+str(args.backend)+'.json')).write_text(json.dumps(result,indent=2));print(json.dumps(result))
        finally:await admin.post('/v1/devices/'+device+'/revoke',json={'confirmed':True})


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--backend',type=int,choices=[8010,8011],default=8011);asyncio.run(main(parser.parse_args()))
