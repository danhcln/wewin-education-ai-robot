"""Bounded real metadata-only probe. Max 3 HTTP dispatches, no database access."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
import requests
from src.config import settings
from src.crawler.http_client import PoliteHttpClient


def run(output):
    allowed={settings.WEBSITE_BASE_URL+p for p in ('/robots.txt','/page-sitemap.xml','/post-sitemap.xml')}
    class BoundedSession:
        def __init__(self):
            self.transport=requests.Session()
            self.transport.trust_env=False
            self.headers=self.transport.headers
            self.count=0
        def get(self,url,**kwargs):
            if url not in allowed or self.count>=3:
                raise RuntimeError('Probe budget/origin exceeded; no further request permitted')
            self.count+=1
            return self.transport.get(url,**kwargs)
    settings.CRAWLER_RETRY_ATTEMPTS=1
    http=PoliteHttpClient(session=BoundedSession())
    results=[]
    try:
        # get() retrieves robots once before the first sitemap, then reuses policy.
        for path in ('/page-sitemap.xml','/post-sitemap.xml'):
            response=http.get(settings.WEBSITE_BASE_URL+path)
            results.append({'url':response.url,'status':response.status_code,'bytes':len(response.content),
                            'sha256':hashlib.sha256(response.content).hexdigest()})
            if response.status_code!=200:
                raise RuntimeError('Unexpected metadata response; stop probe')
        gaps=[b['monotonic']-a['monotonic'] for a,b in zip(http.dispatches,http.dispatches[1:])]
        utc=[(datetime.fromisoformat(b['utc'])-datetime.fromisoformat(a['utc'])).total_seconds() for a,b in zip(http.dispatches,http.dispatches[1:])]
        result={'status':'PASS' if len(gaps)==2 and min(gaps)>=2.05 and min(utc)>=2 else 'FAIL',
                'request_count':http.request_count,'dispatches':http.dispatches,'monotonic_gaps':gaps,
                'utc_gaps':utc,'responses':results,'page_body_requests':0,'database_opened':False}
    except Exception as error:
        result={'status':'FAIL','error_type':type(error).__name__,'request_count':http.request_count,
                'dispatches':http.dispatches,'responses':results,'page_body_requests':0,'database_opened':False}
    Path(output).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result))
    return result['status']=='PASS'


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    if args.output.exists():raise SystemExit('Use a new evidence path; do not overwrite a real probe')
    raise SystemExit(0 if run(args.output) else 1)
