"""Store a user-supplied YouTube API key privately without echoing it.
Does not create Google credentials, change .env, or touch XiaoZhi/admin keys.
"""
import argparse
import getpass
import os
from pathlib import Path
import re
import sys
import tempfile
ROOT=Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))

def parse_key_file(path):
    """Accept one bare key or one KEY=VALUE assignment; never echo input."""
    path=Path(path)
    if path.is_symlink() or path.stat().st_size>4096:
        raise ValueError('Invalid credential file.')
    text=path.read_text(encoding='utf-8-sig').strip()
    if '=' in text:
        label,text=text.split('=',1)
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',label.strip()):
            raise ValueError('Invalid credential assignment.')
        text=text.strip()
        if len(text)>=2 and text[0]==text[-1] and text[0] in ('"',"'"):
            text=text[1:-1]
    if not re.fullmatch(r'[A-Za-z0-9_-]{20,256}',text):
        raise ValueError('Invalid credential format.')
    return text


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--replace',action='store_true')
    parser.add_argument('--source-file',type=Path,help='Import an ignored local file, then remove its verified duplicate.')
    args=parser.parse_args()
    from scripts.rotate_admin_token import restrict_directory
    folder=ROOT/'.secrets/youtube';target=folder/'api_key'
    if target.exists() and not args.replace:raise SystemExit('Key file already exists; use --replace only for an intentional YouTube key rotation.')
    source=None
    if args.source_file:
        source=args.source_file.absolute()
        if source.is_symlink() or source.parent!=ROOT or source.name not in ('API_KEY_YOUTUBE','API_KEY_YOUTUBE.txt'):
            raise SystemExit('Use the explicitly supplied repository-root import file.')
        ignored=(ROOT/'.gitignore').read_text().splitlines()
        if not all(rule in ignored for rule in ('/API_KEY_YOUTUBE','/API_KEY_YOUTUBE.*','.secrets/')):
            raise SystemExit('Add credential exclusions to .gitignore before importing.')
        try:key=parse_key_file(source)
        except (OSError,UnicodeError,ValueError):raise SystemExit('Invalid source credential file; no secret displayed.') from None
    else:key=getpass.getpass('YouTube API key (hidden, never paste into chat): ').strip()
    if not re.fullmatch(r'[A-Za-z0-9_-]{20,256}',key):raise SystemExit('Invalid key format; no file changed.')
    restrict_directory(folder)
    fd,name=tempfile.mkstemp(prefix='youtube-',dir=folder)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:f.write(key+'\n');f.flush();os.fsync(f.fileno())
        os.chmod(name,0o600)
        if args.replace:os.replace(name,target)
        else:os.link(name,target);os.unlink(name)
    finally:
        if Path(name).exists():Path(name).unlink()
    if source:
        if parse_key_file(source)!=key or target.read_text(encoding='utf-8').strip()!=key:
            raise SystemExit('Import verification failed; original file preserved.')
        source.unlink()
    print('YouTube key stored privately. Restart FastAPI to use configuration. No secret was printed.')
if __name__=='__main__':main()
