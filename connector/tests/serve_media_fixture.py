"""Explicit isolated browser-test server. Never use as a production launcher."""
import argparse
import os
from pathlib import Path
import secrets
import sys
import json
ROOT=Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--snapshot',type=Path,required=True)
    parser.add_argument('--directory',type=Path,required=True);parser.add_argument('--port',type=int,required=True);parser.add_argument('--mock-api',action='store_true')
    parser.add_argument('--live-api',action='store_true',help='Explicitly use the private backend YouTube key, with an isolated DB.')
    parser.add_argument('--reconnect-probe',action='store_true',help='Mock-only browser fixture with socket-loss controls; never production.')
    parser.add_argument('--static-dist',type=Path,help='Use a staged frontend build for isolated validation.')
    parser.add_argument('--resume-fixture',action='store_true',help='Restart only a marked private fixture, preserving its test login.')
    args=parser.parse_args();folder=args.directory.resolve()
    if args.live_api and args.mock_api:raise SystemExit('Choose live API or mock API, never both')
    if args.reconnect_probe and not args.mock_api:raise SystemExit('Reconnect probe requires --mock-api')
    if folder.is_relative_to(ROOT/'data') or folder.is_relative_to(ROOT/'frontend'):raise SystemExit('Use a private evidence directory')
    from scripts.rotate_admin_token import restrict_directory
    from scripts.server_ops import backup
    if args.resume_fixture:
        if not folder.is_relative_to(ROOT/'.maintenance') or not (folder/'isolated-fixture.json').is_file():raise SystemExit('Not a marked fixture')
        if json.loads((folder/'isolated-fixture.json').read_text())!={'purpose':'isolated-media-fixture'}:raise SystemExit('Invalid fixture marker')
        admin=(folder/'admin_fixture.key').read_text().strip()
    else:
        if folder.exists():raise SystemExit('Use a new private evidence directory')
        restrict_directory(folder);backup(args.snapshot,folder/'knowledge-copy.db')
        admin=secrets.token_urlsafe(32);(folder/'admin_fixture.key').write_text(admin,encoding='utf-8')
        (folder/'isolated-fixture.json').write_text(json.dumps({'purpose':'isolated-media-fixture'}))
    os.environ.update({'DATABASE_PATH':str(folder/'knowledge-copy.db'),'KNOWLEDGE_JSON_PATH':str(folder/'unused.json'),
        'ADMIN_SYNC_TOKEN':admin,'ADMIN_SYNC_TOKEN_FILE':'','XIAOZHI_MCP_ENDPOINT':'','XIAOZHI_MCP_TOKEN':'',
        'XIAOZHI_MCP_ENDPOINT_FILE':'','XIAOZHI_MCP_TOKEN_FILE':'','BRIDGE_STATUS_PATH':str(folder/'no-production-heartbeat.json'),
        'AUTO_SYNC_ENABLED':'false','SYNC_SCHEDULE_ARMED':'false','SYNC_SCHEDULER_OWNER':'external','DEBUG':'false',
        'YOUTUBE_API_KEY':'','YOUTUBE_API_KEY_FILE':str(ROOT/'.secrets/youtube/api_key' if args.live_api else folder/'not-configured'), 'YOUTUBE_CHANNEL_FILE':str(folder/'channel.json'),
        'BROWSER_SESSION_STORE':str(folder/'.secrets/browser.sqlite3'),'MEDIA_BRIDGE_KEY_FILE':str(folder/'.secrets/bridge.key'),
        'MEDIA_BACKEND_URL':f'http://127.0.0.1:{args.port}'})
    os.chdir(folder)
    from src.api.app import create_app
    app=create_app(static_dir=args.static_dist)
    if args.mock_api:
        from tests.test_youtube_media import FakeAPI,OTHER,CID
        from src.media.youtube import YouTubeClient
        import src.media.routes as media_routes
        fake=FakeAPI();fake.video_channel=CID if args.reconnect_probe else OTHER
        client=YouTubeClient(lambda:'fixture-key-not-production',fake,channel_file=folder/'channel.json')
        client.is_fixture=True;media_routes.youtube=client
    if args.reconnect_probe:
        from fastapi.responses import HTMLResponse
        probe_script='''<script>
window.__connectionProbe={created:0,play:0,sockets:[]};
const RealSocket=window.WebSocket;
window.WebSocket=class extends RealSocket{constructor(...args){super(...args);window.__connectionProbe.sockets.push(this);}};
window.YT={Player:class{
 constructor(frame,options){this.o=options;this.id='';this.state=-1;this.volume=60;frame.src='about:blank';window.__connectionProbe.created++;document.documentElement.dataset.probeFrames=String(window.__connectionProbe.created);setTimeout(()=>this.o.events.onReady({}),20);}
 cueVideoById(id){this.id=id;this.state=5;this.o.events.onStateChange({data:5});}
 loadVideoById(id){this.id=id;this.playVideo();}
 playVideo(){window.__connectionProbe.play++;document.documentElement.dataset.probePlays=String(window.__connectionProbe.play);this.state=1;this.o.events.onStateChange({data:1});}
 pauseVideo(){this.state=2;this.o.events.onStateChange({data:2});}
 stopVideo(){this.state=5;this.o.events.onStateChange({data:5});}
 getPlayerState(){return this.state;}getVideoData(){return {video_id:this.id};}
 setVolume(n){this.volume=n;}getVolume(){return this.volume;}getCurrentTime(){return 0;}destroy(){}
}};
document.addEventListener('DOMContentLoaded',()=>{const button=document.createElement('button');
 button.textContent='TEST: disconnect socket';button.style.cssText='position:fixed;bottom:5px;right:5px;z-index:99999;background:#fff;padding:10px;border:2px solid red';
 button.onclick=()=>window.__connectionProbe.sockets.forEach(ws=>{if(ws.url.includes('/api/media/')&&ws.url.endsWith('/player'))ws.close();});document.body.appendChild(button);});
</script>'''
        @app.middleware('http')
        async def reconnect_probe_page(request,call_next):
            if request.url.path=='/media':
                html=((args.static_dist or ROOT/'frontend/dist')/'index.html').read_text(encoding='utf-8')
                return HTMLResponse(html.replace('<head>','<head>'+probe_script))
            return await call_next(request)
    import uvicorn
    uvicorn.run(app,host='127.0.0.1',port=args.port,access_log=False,loop='asyncio',http='h11')
