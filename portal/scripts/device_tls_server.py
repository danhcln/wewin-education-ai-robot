"""Direct TLS device edge, private LAN only. No proxy header trust or management.
No CA installation, firewall, global environment, backend flags or device writes.
"""
import argparse
import ipaddress
import os
from pathlib import Path
import ssl
import sys
import uvicorn

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def config(host,port,backend,certificate,key):
    ip=ipaddress.ip_address(host)
    private=any(ip in ipaddress.ip_network(n) for n in ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16','127.0.0.0/8')) if ip.version==4 else False
    if not private or port not in (8014,8015) or backend not in (8010,8011):raise ValueError('Only private staging edge8014/8015 -> loopback8010/8011')
    if os.environ.get('SSLKEYLOGFILE'):raise ValueError('TLS key logging must be disabled')
    from ai_server.edge import create_edge
    ctx=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);ctx.minimum_version=ssl.TLSVersion.TLSv1_2
    ctx.set_ciphers('ECDHE+AESGCM:ECDHE+CHACHA20');ctx.load_cert_chain(str(certificate),str(key))
    cfg=uvicorn.Config(create_edge('http://127.0.0.1:'+str(backend)),host=host,port=port,workers=1,proxy_headers=False,access_log=False,ssl_certfile=str(certificate),ssl_keyfile=str(key),ws_max_size=65536,ws_ping_interval=20,ws_ping_timeout=20)
    cfg.load();cfg.ssl=ctx
    return cfg


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--host',required=True);parser.add_argument('--port',type=int,default=8014);parser.add_argument('--backend',type=int,choices=[8010,8011],default=8010);parser.add_argument('--certificate',type=Path,required=True);parser.add_argument('--key',type=Path,required=True);args=parser.parse_args()
    uvicorn.Server(config(args.host,args.port,args.backend,args.certificate,args.key)).run()
