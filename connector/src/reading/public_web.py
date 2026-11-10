"""On-demand public HTTP reader: validate DNS, pin sockets, never use proxies.

Transport and DNS injection exist for isolated tests, not as MCP parameters.
No cookies, credentials, subresources, automatic redirects, or database writes.
"""
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
import http.client
import ipaddress
import re
import socket
import ssl
import threading
import time
import zlib
from urllib.parse import parse_qsl, quote, unquote, urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

from bs4 import BeautifulSoup
from src.crawler.extractor import PageExtractor, fix_vietnamese_mojibake


class ReadError(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message
        super().__init__(message)


def public_ip(value):
    try:
        ip = ipaddress.ip_address(value)
        # Disallow IPv4 encapsulation/transition ranges as well as private IPs.
        return (ip.is_global and not ip.is_multicast and not ip.is_reserved
                and not ip.is_unspecified and not ip.is_loopback
                and not (ip.version == 6 and (ip.ipv4_mapped or ip.sixtofour or ip.teredo
                                              or ip in ipaddress.ip_network('64:ff9b::/96')
                                              or ip in ipaddress.ip_network('64:ff9b:1::/48'))))
    except ValueError:
        return False


def validate_url(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 2048:
        raise ReadError('invalid_url', 'URL không hợp lệ hoặc quá dài.')
    if re.search(r'[\s\x00-\x1f\x7f\\]', value) or re.search(r'%(?:0[0-9a-f]|1[0-9a-f]|7f|5c)', value, re.I):
        raise ReadError('invalid_url', 'URL chứa ký tự không được phép.')
    try:
        p = urlsplit(value)
        host = (p.hostname or '').rstrip('.').encode('idna').decode('ascii').lower()
        port = p.port if p.port is not None else (443 if p.scheme == 'https' else 80)
    except (ValueError, UnicodeError):
        raise ReadError('invalid_url', 'URL không hợp lệ.') from None
    if p.scheme not in ('http', 'https') or not host or p.username is not None or p.password is not None or p.fragment:
        raise ReadError('invalid_url', 'Chỉ nhận HTTP/HTTPS, không nhận tài khoản hoặc fragment trong URL.')
    if any(re.search(r'token|jwt|password|passwd|secret|api.?key|authorization|signature|session',key,re.I)
           for key,_ in parse_qsl(p.query)):
        raise ReadError('credentialed_url','Không nhận URL chứa tham số thông tin xác thực.')
    if port != (443 if p.scheme == 'https' else 80):
        raise ReadError('blocked_port', 'Chỉ cho phép cổng HTTP/HTTPS tiêu chuẩn.')
    if host == 'wewin.edu.vn' or host.endswith('.wewin.edu.vn'):
        raise ReadError('use_wewin_cache', 'URL WeWIN phải đọc từ cache đã duyệt bằng wewin_read_article.')
    if (host == 'localhost' or host.endswith(('.localhost', '.local', '.internal', '.lan', '.home', '.test', '.invalid'))
            or host == 'metadata.google.internal'):
        raise ReadError('blocked_address', 'Không đọc địa chỉ nội bộ.')
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        if '.' not in host or not re.fullmatch(r'[a-z0-9.-]+', host) or any(not x or len(x)>63 or x[0]=='-' or x[-1]=='-' for x in host.split('.')):
            raise ReadError('invalid_url', 'Tên miền không hợp lệ.') from None
    else:
        if not public_ip(str(ip)):
            raise ReadError('blocked_address', 'Không đọc địa chỉ nội bộ hoặc IP đặc biệt.')
    # Refuse alternate numeric IPv4 spellings before any resolver can reinterpret.
    if re.fullmatch(r'(?:0x[0-9a-f]+|[0-9.]+)', host):
        try:
            ipaddress.IPv4Address(host)
        except ValueError:
            raise ReadError('blocked_address', 'Không nhận cách viết IP mơ hồ.') from None
    if '%' in p.netloc:
        raise ReadError('invalid_url', 'Không nhận hostname mã hóa hoặc IPv6 zone ID.')
    decoded=unquote(p.path)
    if ('\\' in decoded or '%' in decoded or re.search(r'%2f',p.path,re.I)
            or any(part in ('.','..') for part in decoded.split('/'))):
        raise ReadError('invalid_url','Đường dẫn mơ hồ không được phép để bảo toàn quy tắc robots.txt.')
    netloc = '['+host+']' if ':' in host else host
    path = quote(p.path or '/', safe="/%:@!$&'()*+,;=-._~")
    query = quote(p.query, safe="%=&?/:@!$'()*+,;~-._")
    return urlunsplit((p.scheme, netloc, path, query, ''))


_DNS_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix='wewin-public-dns')
_DNS_SLOTS = threading.BoundedSemaphore(2)


def resolve_public(host, port, timeout):
    """Bound caller latency and outstanding resolver work; fail closed on mixed DNS."""
    if not _DNS_SLOTS.acquire(blocking=False):
        raise ReadError('busy', 'Bộ đọc DNS đang bận; vui lòng thử lại sau.')
    future = _DNS_POOL.submit(socket.getaddrinfo, host, port, 0, socket.SOCK_STREAM)
    future.add_done_callback(lambda _: _DNS_SLOTS.release())
    try:
        rows = future.result(timeout=timeout)
    except FutureTimeout:
        future.cancel()
        raise ReadError('timeout', 'Hết thời gian phân giải tên miền.') from None
    except OSError:
        raise ReadError('dns_failed', 'Không phân giải được nguồn công khai.') from None
    addresses = list(dict.fromkeys(row[4][0] for row in rows))
    if not addresses or len(addresses)>16 or not all(public_ip(ip) for ip in addresses):
        raise ReadError('blocked_address', 'DNS trả về địa chỉ nội bộ hoặc không được phép.')
    return addresses


class PinnedConnection(http.client.HTTPConnection):
    def __init__(self, host, port, ip, secure, timeout):
        super().__init__(host, port=port, timeout=timeout)
        self.ip, self.secure = ip, secure

    def connect(self):
        # A numeric sockaddr avoids a second DNS lookup / DNS rebinding window.
        family = socket.AF_INET6 if ':' in self.ip else socket.AF_INET
        sock = socket.socket(family, socket.SOCK_STREAM)
        self.sock = sock
        try:
            sock.settimeout(self.timeout)
            sock.connect((self.ip, self.port))
            peer=sock.getpeername()[0]
            if not public_ip(peer) or ipaddress.ip_address(peer)!=ipaddress.ip_address(self.ip):
                raise ReadError('blocked_address', 'Kết nối không tới địa chỉ công khai.')
            if self.secure:
                self.sock = ssl.create_default_context().wrap_socket(sock, server_hostname=self.host)
        except BaseException:
            sock.close()
            raise


def pinned_request(url, ip, deadline, limit):
    p = urlsplit(url)
    remaining = deadline-time.monotonic()
    if remaining <= 0:
        raise ReadError('timeout', 'Hết thời gian đọc trang.')
    conn = PinnedConnection(p.hostname, p.port or (443 if p.scheme=='https' else 80), ip,
                            p.scheme=='https', min(3, remaining))
    active = [None]
    def abort():
        if active[0] is not None:
            try: active[0].shutdown(socket.SHUT_RDWR)
            except OSError: pass
        conn.close()
    timer = threading.Timer(remaining, abort)
    timer.daemon = True
    timer.start()
    try:
        conn.connect()
        active[0] = conn.sock
        if time.monotonic() >= deadline:
            raise ReadError('timeout', 'Hết thời gian đọc trang.')
        path = p.path + ('?'+p.query if p.query else '')
        conn.request('GET', path, headers={'User-Agent':'WeWINVoiceReader/1.0',
                     'Accept':'text/html,text/plain;q=0.9', 'Accept-Encoding':'gzip, identity;q=0.5', 'Connection':'close'})
        response = conn.getresponse()
        headers = {k.lower():v for k,v in response.getheaders()}
        if len(response.getheaders())>40 or sum(len(k)+len(v) for k,v in response.getheaders())>16384:
            raise ReadError('too_large', 'Header phản hồi quá lớn.')
        encoding=headers.get('content-encoding','identity').lower()
        if encoding not in ('identity','','gzip'):
            raise ReadError('unsupported_encoding', 'Nguồn dùng nội dung nén chưa được bộ đọc này hỗ trợ.')
        length = headers.get('content-length')
        if length is not None and (not length.isdecimal() or int(length)>limit):
            raise ReadError('too_large', 'Phản hồi vượt giới hạn kích thước.')
        chunks, size, wire_size = [], 0, 0
        decoder=zlib.decompressobj(16+zlib.MAX_WBITS) if encoding=='gzip' else None
        # Redirect/error bodies aren't needed and are never rendered as articles.
        if response.status == 200:
            while True:
                # HTTPResponse closes its socket after Content-Length is consumed,
                # including a zero-byte robots.txt; don't settimeout on that handle.
                if response.isclosed(): break
                remaining = deadline-time.monotonic()
                if remaining<=0: raise ReadError('timeout', 'Hết thời gian đọc trang.')
                active[0].settimeout(min(3, remaining))
                chunk = response.read1(min(16384, limit-wire_size+1))
                if not chunk: break
                wire_size+=len(chunk)
                if wire_size>limit:raise ReadError('too_large','Dữ liệu truyền vượt giới hạn.')
                if decoder:
                    chunk=decoder.decompress(chunk,limit-size+1)
                    if decoder.unconsumed_tail or decoder.unused_data:
                        raise ReadError('too_large','Dữ liệu giải nén hoặc nhiều gzip member không được phép.')
                size += len(chunk)
                if size>limit: raise ReadError('too_large', 'Phản hồi vượt giới hạn kích thước.')
                chunks.append(chunk)
            if decoder and not decoder.eof:
                raise ReadError('invalid_encoding','Phản hồi gzip không hoàn chỉnh.')
        return response.status, headers, b''.join(chunks)
    except zlib.error:
        raise ReadError('invalid_encoding','Dữ liệu gzip không hợp lệ.') from None
    finally:
        timer.cancel()
        abort()


class PublicWebReader:
    """One reader per process; one fetch at a time and bounded total response bytes."""
    def __init__(self, resolver=resolve_public, transport=pinned_request, clock=time.monotonic, sleep=time.sleep):
        self.resolve, self.transport, self.clock, self.sleep = resolver, transport, clock, sleep
        self._lock = threading.Lock()
        self._last = None
        self._blocked_until = 0

    def _request(self, url, deadline, delay=2.05, limit=262144):
        url = validate_url(url)
        remaining = deadline-self.clock()
        if remaining<=0: raise ReadError('timeout', 'Hết thời gian đọc trang.')
        p = urlsplit(url)
        addresses = self.resolve(p.hostname, p.port or (443 if p.scheme=='https' else 80), min(3,remaining))
        # Validate injected resolvers too; no input can override this invariant.
        if not addresses or not all(public_ip(ip) for ip in addresses):
            raise ReadError('blocked_address', 'Không đọc địa chỉ nội bộ.')
        wait = max(0, self._blocked_until-self.clock(),
                   delay-(self.clock()-self._last) if self._last is not None else 0)
        if wait>=deadline-self.clock():
            raise ReadError('deferred', 'Nguồn yêu cầu chờ lâu hơn ngân sách đọc; thử lại sau.')
        if wait: self.sleep(wait)
        if self.clock()>=deadline: raise ReadError('timeout', 'Hết thời gian đọc trang.')
        self._last = self.clock()
        status, headers, body = self.transport(url, addresses[0], deadline, limit)
        headers = {str(k).lower():str(v) for k,v in headers.items()}
        if len(body)>limit: raise ReadError('too_large', 'Phản hồi vượt giới hạn kích thước.')
        if status in (429,503):
            from email.utils import parsedate_to_datetime
            from datetime import datetime, timezone
            retry = headers.get('retry-after','60')
            try: seconds=float(retry)
            except ValueError:
                try: seconds=(parsedate_to_datetime(retry)-datetime.now(timezone.utc)).total_seconds()
                except (ValueError,TypeError,OverflowError): seconds=60
            self._blocked_until=self.clock()+max(60,min(86400,seconds))
        return status, headers, body

    def fetch(self, url):
        if not self._lock.acquire(blocking=False):
            raise ReadError('busy', 'Đang đọc một URL bên ngoài; thử lại sau.')
        deadline=self.clock()+15
        try:
            current=validate_url(url); origins={}; total=0
            for hop in range(4):
                p=urlsplit(current);origin=p.scheme+'://'+p.netloc
                if origin not in origins:
                    status,headers,body=self._request(origin+'/robots.txt',deadline,limit=65536)
                    total+=len(body)
                    if status not in (200,404):
                        raise ReadError('robots_unavailable','Không xác minh được robots.txt; chưa đọc trang.')
                    parser=RobotFileParser();lines=body.decode('utf-8',errors='replace').splitlines() if status==200 else ['User-agent: *','Disallow:']
                    if status==200 and body.lstrip().startswith(b'<'):
                        raise ReadError('robots_unavailable','robots.txt trả HTML thay vì quy tắc truy cập; chưa đọc trang.')
                    parser.parse(lines)
                    delays=[float(m[1]) for line in lines if (m:=re.match(r'(?i)^\s*crawl-delay\s*:\s*(\d+(?:\.\d+)?)\s*(?:#.*)?$',line))]
                    rate=parser.request_rate('WeWINVoiceReader')
                    delay=max([2.05,parser.crawl_delay('WeWINVoiceReader') or 0,*delays,
                               rate.seconds/rate.requests if rate and rate.requests else 0])
                    origins[origin]=(parser,delay)
                parser,delay=origins[origin]
                if not parser.can_fetch('WeWINVoiceReader',current):
                    raise ReadError('robots_denied','robots.txt không cho phép đọc URL này.')
                status,headers,body=self._request(current,deadline,delay)
                total+=len(body)
                if total>524288: raise ReadError('too_large','Tổng phản hồi vượt giới hạn.')
                if status in (301,302,303,307,308):
                    if hop==3: raise ReadError('redirect_limit','Quá số lần chuyển hướng cho phép.')
                    location=headers.get('location')
                    if not location: raise ReadError('invalid_redirect','Chuyển hướng không có đích hợp lệ.')
                    target=validate_url(urljoin(current,location))
                    if p.scheme=='https' and urlsplit(target).scheme!='https':
                        raise ReadError('blocked_redirect','Không theo chuyển hướng hạ cấp HTTPS.')
                    current=target
                    continue
                if status!=200:
                    raise ReadError('http_'+str(status),'Nguồn trả HTTP '+str(status)+'; không vượt giới hạn truy cập.')
                content_type=headers.get('content-type','').lower()
                mime=content_type.split(';')[0].strip()
                if mime not in ('text/html','text/plain'):
                    raise ReadError('unsupported_type','Chỉ hỗ trợ nội dung HTML hoặc văn bản công khai.')
                encoding=re.search(r'charset=["\']?([a-zA-Z0-9_-]+)',content_type)
                try: text=body.decode(encoding[1] if encoding else 'utf-8',errors='strict')
                except (LookupError,UnicodeError): raise ReadError('unsupported_encoding','Không giải mã được văn bản nguồn.') from None
                if mime=='text/html':
                    soup=BeautifulSoup(text,'html.parser')
                    if (soup.find('input',attrs={'type':re.compile('password',re.I)})
                            or soup.select_one('.paywall, #paywall') or re.search(r'"isAccessibleForFree"\s*:\s*false',text,re.I)
                            or re.search(r'verify you are human|access denied|subscribe to continue|đăng nhập để|captcha',soup.get_text(' ',strip=True),re.I)):
                        raise ReadError('access_restricted','Trang yêu cầu xác minh, đăng nhập hoặc thuê bao; không vượt bảo vệ.')
                    for el in soup.find_all('iframe'):el.decompose()
                    page=PageExtractor.clean_html(str(soup),current)
                    if not page: raise ReadError('empty_content','Không tìm được nội dung văn bản hữu ích; không đọc iframe/form.')
                    title=(soup.title.get_text(' ',strip=True) if soup.title else p.hostname)[:200]
                    text=page['content']
                else:
                    title=p.hostname
                text=fix_vietnamese_mojibake(text).strip()
                if len(text)<60: raise ReadError('empty_content','Nguồn quá ngắn hoặc rỗng.')
                if len(text)>100000: raise ReadError('too_large','Văn bản vượt 100.000 ký tự; chưa hỗ trợ đọc toàn bài này.')
                if re.search(r'password|mật\s*khẩu|nội\s*bộ|internal\s+use|confidential',title+' '+text,re.I):
                    raise ReadError('publication_review','Nội dung có dấu hiệu nhạy cảm; cần kiểm tra trước khi đọc công khai.')
                if self.clock()>=deadline: raise ReadError('timeout','Hết ngân sách xử lý trang.')
                return {'url':current,'title':title,'content':text,'source_type':'external_untrusted'}
            raise ReadError('redirect_limit','Quá số lần chuyển hướng.')
        except ReadError:
            raise
        except (OSError, http.client.HTTPException, ValueError):
            raise ReadError('fetch_failed','Không đọc được nguồn công khai trong giới hạn an toàn.') from None
        finally:
            self._lock.release()
