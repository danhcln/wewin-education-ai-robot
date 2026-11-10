"""Device-only LAN/TLS edge. Management API is never proxied.

TLS terminates at an approved reverse proxy. Direct HTTP is staging/simulator
only; the backend refuses physical bootstrap unless its origin is HTTPS/WSS.
"""
import asyncio
import os
from urllib.parse import urlsplit
import httpx
import websockets
from fastapi import FastAPI,Request,WebSocket,HTTPException
from fastapi.responses import JSONResponse
from .device_management import BootstrapLogRedaction,PREFIX


def create_edge(backend=None):
    backend=(backend or os.environ.get('WEWIN_EDGE_BACKEND','http://127.0.0.1:8010')).rstrip('/')
    url=urlsplit(backend)
    if url.scheme!='http' or url.hostname!='127.0.0.1' or url.port not in (8010,8011) or url.path or url.query or url.username or url.password or url.fragment:raise ValueError('Device edge backend must be private loopback AI 8010/8011')
    app=FastAPI(title='WeWIN device-only edge',docs_url=None,redoc_url=None,openapi_url=None)
    app.add_middleware(BootstrapLogRedaction)
    allowed=('authorization','device-id','client-id','protocol-version','activation-version','content-type','user-agent')

    @app.get('/health')
    async def health():return {'service':'wewin-device-edge','management_routes_exposed':False,'firmware_delivery':False,'physical_acceptance':False}

    async def proxy(request,path):
        if request.url.query or request.headers.get('origin'):raise HTTPException(400,'Native device request required; no query credentials')
        body=bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body)>16384:raise HTTPException(413,'Device request too large')
        try:
            headers={name:request.headers[name] for name in allowed if name in request.headers}
            headers['X-WeWIN-Edge-TLS']='1' if request.url.scheme=='https' else '0'
            async with httpx.AsyncClient(timeout=12,trust_env=False,follow_redirects=False) as client:
                response=await client.post(backend+path,content=bytes(body),headers=headers)
            value=response.json()
            if path.startswith(PREFIX) and response.status_code==200:
                if 'mqtt' in value:
                    endpoint=value['mqtt'].get('endpoint','')
                    expected_host=request.url.hostname
                    # Stock Wi-Fi MQTT wrapper uses TLS only on port 8883.
                    if request.url.scheme!='https' or endpoint!=f'{expected_host}:8883':
                        return JSONResponse({'detail':'MQTT TLS origin mismatch; credential response withheld'},status_code=502)
                    return JSONResponse(value,status_code=200,headers={'Cache-Control':'no-store','Referrer-Policy':'no-referrer'})
                target=urlsplit(value.get('websocket',{}).get('url',''))
                if request.url.scheme=='https' and (target.scheme!='wss' or target.netloc!=request.url.netloc):
                    return JSONResponse({'detail':'TLS device origin mismatch; credential response withheld'},status_code=502)
                if request.url.scheme!='https' and target.scheme=='wss':
                    return JSONResponse({'detail':'Use the issued HTTPS bootstrap URL'},status_code=426)
            return JSONResponse(value,status_code=response.status_code,headers={'Cache-Control':'no-store','Referrer-Policy':'no-referrer'})
        except (httpx.HTTPError,ValueError):return JSONResponse({'detail':'WeWIN backend unavailable; no legacy Cloud fallback'},status_code=503)

    @app.post(PREFIX+'{secret}')
    @app.post(PREFIX+'{secret}/',include_in_schema=False)
    async def bootstrap(secret:str,request:Request):return await proxy(request,PREFIX+secret)

    @app.post('/xiaozhi/ota/')
    async def legacy_simulator_discovery(request:Request):return await proxy(request,'/xiaozhi/ota/')

    @app.websocket('/xiaozhi/v1/')
    async def socket(ws:WebSocket):
        if ws.url.query or ws.headers.get('origin'):await ws.close(code=1008);return
        headers={name:ws.headers[name] for name in allowed if name in ws.headers}
        headers['X-WeWIN-Edge-TLS']='1' if ws.url.scheme=='wss' else '0'
        try:
            async with websockets.connect(backend.replace('http://','ws://')+'/xiaozhi/v1/',additional_headers=headers,proxy=None,open_timeout=5,max_size=65536,max_queue=16) as upstream:
                await ws.accept()
                async def uplink():
                    while True:
                        item=await ws.receive()
                        if item['type']=='websocket.disconnect':return
                        content=item.get('bytes') if item.get('bytes') is not None else item.get('text','')
                        if len(content)>65536:return
                        await upstream.send(content)
                async def downlink():
                    async for item in upstream:
                        if isinstance(item,bytes):await ws.send_bytes(item)
                        else:await ws.send_text(item)
                tasks=[asyncio.create_task(uplink()),asyncio.create_task(downlink())]
                try:
                    await asyncio.wait(tasks,return_when=asyncio.FIRST_COMPLETED)
                finally:
                    for task in tasks:task.cancel()
                    await asyncio.gather(*tasks,return_exceptions=True)
        except (websockets.exceptions.WebSocketException,OSError,RuntimeError):pass
        finally:
            try:await ws.close(code=1001)
            except RuntimeError:pass
    return app


app=create_edge()
