"""Bounded same-origin HTTP, robots policy, rate limiting and retries."""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import threading
import time
from urllib.parse import urljoin, urlsplit, unquote
from urllib.robotparser import RobotFileParser
import requests

from src.config import settings


class CrawlPolicyError(RuntimeError): pass
class CrawlCancelled(RuntimeError): pass


class PoliteHttpClient:
    def __init__(self, session=None, sleep=None, clock=None):
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": settings.CRAWLER_USER_AGENT})
        self.sleep = sleep or time.sleep
        self.clock = clock or time.monotonic
        self._last_request = None
        self._robots = None
        self._robots_at = 0
        self.delay = max(2.05, settings.CRAWLER_DELAY_SECONDS)
        self.cancel_event = threading.Event()
        self.request_count = 0
        self.retry_count = 0
        self.dispatches = []
        self._dispatch_lock = threading.Lock()
        self._last_dispatch = None
        self._pressure_streak = 0

    def validate_url(self, url):
        parsed = urlsplit(url)
        base = urlsplit(settings.WEBSITE_BASE_URL)
        if parsed.scheme != base.scheme or parsed.hostname != base.hostname or parsed.port not in (None, 443) or parsed.username or parsed.password:
            raise CrawlPolicyError("Cross-origin, credentialed or downgraded URL refused.")
        decoded_path = unquote(parsed.path)
        if "\\" in decoded_path or any(part in (".", "..") for part in decoded_path.split("/")):
            raise CrawlPolicyError("Ambiguous path normalization refused before robots evaluation.")
        return url

    def wait(self, seconds):
        if self.cancel_event.is_set(): raise CrawlCancelled("Stop requested")
        if seconds > 0:
            if self.sleep == time.sleep:
                if self.cancel_event.wait(seconds): raise CrawlCancelled("Stop requested")
            else:
                self.sleep(seconds)
        if self.cancel_event.is_set(): raise CrawlCancelled("Stop requested")

    def _rate_limit(self):
        if self._last_request is not None:
            self.wait(max(0, self.delay - (self.clock() - self._last_request)))
        self._last_request = self.clock()

    def _retry_delay(self, response, attempt):
        seconds = settings.CRAWLER_RETRY_BACKOFF_SECONDS * (2 ** attempt)
        if response is not None:
            value = response.headers.get("Retry-After", "")
            try:
                seconds = max(seconds, float(value))
            except ValueError:
                try:
                    seconds = max(seconds, (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds())
                except (ValueError, TypeError): pass
        if seconds > settings.CRAWLER_MAX_RETRY_WAIT_SECONDS:
            raise CrawlPolicyError("Retry-After requires longer deferral; no early retry allowed.")
        return max(0, seconds)

    def _one_url(self, url):
        if self._pressure_streak >= 3:
            raise CrawlPolicyError("Server pressure circuit remains open; no further HTTP in this job.")
        for attempt in range(settings.CRAWLER_RETRY_ATTEMPTS):
            self.wait(0)
            self._rate_limit()
            response = None
            try:
                self.request_count += 1
                with self._dispatch_lock:
                    if self._last_dispatch is not None:
                        remaining = max(2.05, self.delay) - (self.clock() - self._last_dispatch)
                        while remaining > 0:
                            self.wait(remaining)
                            remaining = max(2.05, self.delay) - (self.clock() - self._last_dispatch)
                    self.wait(0)
                    self._last_dispatch = self.clock()
                    self.dispatches.append({"url": url, "monotonic": self._last_dispatch,
                                            "utc": datetime.now(timezone.utc).isoformat()})
                    response = self.session.get(url, timeout=settings.CRAWLER_TIMEOUT_SECONDS, allow_redirects=False, stream=True)
                self._pressure_streak = self._pressure_streak + 1 if response.status_code == 429 or response.status_code >= 500 else 0
                if self._pressure_streak >= 3:
                    raise CrawlPolicyError("Three consecutive 429/5xx responses; stop and defer this job.")
                if response.status_code not in (408, 429, 500, 502, 503, 504) or attempt + 1 == settings.CRAWLER_RETRY_ATTEMPTS:
                    chunks, size = [], 0
                    for chunk in response.iter_content(65536):
                        self.wait(0)
                        size += len(chunk)
                        if size > settings.CRAWLER_MAX_RESPONSE_BYTES:
                            raise CrawlPolicyError("Response body exceeds configured size limit.")
                        chunks.append(chunk)
                    response._content = b"".join(chunks)
                    response._content_consumed = True
                    response.close()
                    return response
            except (requests.ConnectionError, requests.Timeout):
                if attempt + 1 == settings.CRAWLER_RETRY_ATTEMPTS: raise
            finally:
                if response is not None: response.close()
            self.retry_count += 1
            self.wait(self._retry_delay(response, attempt))
        raise RuntimeError("Retry limit reached")

    def _load_robots(self):
        if self._robots is not None and self.clock() - self._robots_at < 3600: return
        response = self.get(settings.WEBSITE_BASE_URL + "/robots.txt", check_robots=False)
        parser = RobotFileParser()
        parser.set_url(settings.WEBSITE_BASE_URL + "/robots.txt")
        if response.status_code == 404:
            parser.parse(["User-agent: *", "Disallow:"])
        elif response.status_code in (401, 403):
            parser.parse(["User-agent: *", "Disallow: /"])
        elif response.status_code == 200:
            parser.parse(response.content.decode("utf-8", errors="replace").splitlines())
        else:
            raise CrawlPolicyError("robots.txt unavailable; refusing to crawl.")
        self._robots, self._robots_at = parser, self.clock()
        self.delay = max(2.05, settings.CRAWLER_DELAY_SECONDS, parser.crawl_delay(settings.CRAWLER_USER_AGENT) or 0)
        rate = parser.request_rate(settings.CRAWLER_USER_AGENT)
        if rate and rate.requests: self.delay = max(self.delay, rate.seconds / rate.requests)
        if self.delay > settings.CRAWLER_MAX_RETRY_WAIT_SECONDS:
            raise CrawlPolicyError("robots policy requires longer spacing; defer for manual review.")

    def allowed(self, url):
        self.validate_url(url)
        self._load_robots()
        return self._robots.can_fetch(settings.CRAWLER_USER_AGENT, url)

    def get(self, url, check_robots=True):
        for _ in range(6):
            self.validate_url(url)
            if check_robots and not self.allowed(url):
                raise CrawlPolicyError("robots.txt disallows this URL.")
            response = self._one_url(url)
            if response.status_code not in (301, 302, 303, 307, 308):
                return response
            location = response.headers.get("Location")
            if not location: raise CrawlPolicyError("Redirect has no Location.")
            url = urljoin(url, location)
        raise CrawlPolicyError("Redirect limit exceeded.")
