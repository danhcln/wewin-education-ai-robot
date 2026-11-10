"""
Sitemap crawler for https://wewin.edu.vn/
Polite, rate-limited, resilient crawler that respects robots.txt and sitemaps.
Supports URL normalization, comprehensive candidate discovery, and batch rotation.
"""
import json
import time
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Dict, Any, Set, Tuple, Optional
import requests
import re
import hashlib
from bs4 import BeautifulSoup
from .http_client import PoliteHttpClient, CrawlPolicyError, CrawlCancelled


class DiscoveryError(RuntimeError):
    pass

from src.config import settings
from src.utils.logger import logger
from .extractor import PageExtractor
from .curated_seeds import get_curated_seeds

def normalize_url(url: str) -> str:
    """
    Normalizes URLs for robust deduplication and comparison.
    1. Trims whitespace.
    2. Lowercases scheme and netloc.
    3. Normalizes path with trailing slash (except for files).
    4. Strips tracking query parameters (utm_*, fbclid, etc.).
    5. Strips anchors/fragments unless #ctrinhhoc.
    """
    if not url:
        return ""
    url = url.strip()
    # Preserve key internal anchor for course recommendation
    has_ctrinhhoc = "#ctrinhhoc" in url

    parsed = urllib.parse.urlparse(url)
    scheme = parsed.scheme.lower() or "https"
    netloc = parsed.netloc.lower() or "wewin.edu.vn"
    path = parsed.path

    if not path:
        path = "/"
    elif not path.endswith("/") and not any(path.endswith(ext) for ext in [".html", ".htm", ".pdf", ".xml", ".jpg", ".png"]):
        path += "/"

    # Strip marketing and tracking queries
    filtered_queries = [
        (k, v) for k, v in urllib.parse.parse_qsl(parsed.query)
        if not k.startswith("utm_") and k not in ("fbclid", "gclid", "ref", "source")
    ]
    new_query = urllib.parse.urlencode(filtered_queries)
    fragment = "ctrinhhoc" if has_ctrinhhoc else ""

    return urllib.parse.urlunparse((scheme, netloc, path, "", new_query, fragment))


def transport_equivalent_url(left: str, right: str) -> bool:
    """Percent-escape hex case is equivalent; path case and escaping stay intact.

    Requests uppercases escapes in response.url. Do not migrate cache keys or
    decode reserved separators to accommodate that transport normalization.
    """
    def key(value):
        return re.sub(r"%[0-9a-fA-F]{2}", lambda match: match.group(0).upper(), normalize_url(value))
    return key(left) == key(right)

class WeWinCrawler:
    # URL substrings representing utilities, carts, user accounts, game frames, and internal apps
    EXCLUDE_PATTERNS = [
        "/cart", "/checkout", "/my-account", "/shop", "/profile", "/leave-request",
        "/wewinmanager", "/wewinhr", "/internalapp", "/test-quiz-builder",
        "/randomgame", "/games-hub", "/game-tieng-anh-toan-khoa", "/game_2",
        "/game-store", "/family-english-game", "/baobaiedux", "/baobaiwewin",
        "/279-2", "/prompt-tpack"
    ]

    # Priority core URLs always evaluated first
    CORE_PRIORITY_URLS = [
        "https://wewin.edu.vn/",
        "https://wewin.edu.vn/about/",
        "https://wewin.edu.vn/cambridge-placement-test/",
        "https://wewin.edu.vn/ielts-placement-test/",
        "https://wewin.edu.vn/dang-ky-tai-khoan-sach-online-free/"
    ]

    def __init__(self, http=None):
        self.http = http or PoliteHttpClient()
        self.session = self.http.session
        self.discovery_stats = {}
        self.manifest_urls = None

    def fetch_sitemap_urls(self, sitemap_url):
        response = self.http.get(sitemap_url)
        if response.status_code != 200:
            raise DiscoveryError(f"Required sitemap failed with HTTP {response.status_code}")
        try:
            root = ET.fromstring(response.content)
        except ET.ParseError as error:
            raise DiscoveryError("Invalid sitemap XML; discovery was not accepted.") from error
        urls = [element.text.strip() for element in root.iter("{http://www.sitemaps.org/schemas/sitemap/0.9}loc") if element.text]
        if len(urls) > 5000:
            raise DiscoveryError("Sitemap exceeds planning limit; review required.")
        return urls

    def exclusion_reason(self, url):
        try:
            self.http.validate_url(url)
            parsed = urllib.parse.urlsplit(url)
            if parsed.query: return "query_url_requires_review"
            if any(parsed.path.lower().endswith(ext) for ext in (".pdf", ".zip", ".jpg", ".png", ".mp4", ".xml")):
                return "non_html_requires_review"
            patterns = self.EXCLUDE_PATTERNS + ["/wp-admin", "/wp-json", "/wp-login", "/wewin-sales-playbook", "/thong-tin-thuc-tap-sinh"]
            matched = next((pattern for pattern in patterns if pattern in parsed.path.lower()), None)
            if matched: return "excluded:" + matched
            if not self.http.allowed(url): return "robots_disallow"
        except CrawlPolicyError:
            return "origin_or_robots_policy"
        return ""

    def discover_all_urls(self):
        # Only index metadata is fetched here; no page bodies or linked documents.
        index = self.http.get(settings.WEBSITE_BASE_URL + "/sitemap_index.xml")
        if index.status_code == 404:
            sitemaps = [settings.WEBSITE_BASE_URL + "/page-sitemap.xml", settings.WEBSITE_BASE_URL + "/post-sitemap.xml"]
        elif index.status_code == 200:
            try: tree = ET.fromstring(index.content)
            except ET.ParseError as error: raise DiscoveryError("Invalid sitemap index") from error
            sitemaps = [node.text.strip() for node in tree.iter("{http://www.sitemaps.org/schemas/sitemap/0.9}loc")
                        if node.text and re.search(r"/(page|post)-sitemap(?:\d+)?\.xml$", node.text.strip())]
            sitemaps = list(dict.fromkeys(sitemaps))
            if not sitemaps: raise DiscoveryError("No page/post sitemaps discovered")
        else:
            raise DiscoveryError(f"Sitemap index HTTP {index.status_code}; refusing partial discovery")
        if len(sitemaps) > 10: raise DiscoveryError("Too many sitemap files; review required")
        def sitemap_order(url):
            match = re.search(r"/(page|post)-sitemap(\d*)\.xml$", url)
            return (0 if match.group(1) == "page" else 1, int(match.group(2) or "1"))
        sitemaps.sort(key=sitemap_order)  # Preserve the original page-before-post order.
        raw = []
        for sitemap in sitemaps:
            self.http.validate_url(sitemap)
            raw.extend(self.fetch_sitemap_urls(sitemap))
        if not raw or len(raw) > 10000:
            raise DiscoveryError("Empty or oversized combined sitemap pool; review required")
        valid, skipped, seen, duplicates = [], [], set(), 0
        raw_canonical = []
        for value in raw:
            try: raw_canonical.append(normalize_url(value))
            except ValueError: pass
        raw_duplicates = len(raw_canonical) - len(set(raw_canonical))
        for value in self.CORE_PRIORITY_URLS + raw:
            try: url = normalize_url(value)
            except ValueError:
                skipped.append((value, "invalid_url")); continue
            if url in seen:
                duplicates += 1
                continue
            seen.add(url)
            reason = self.exclusion_reason(url)
            if reason: skipped.append((url, reason))
            else: valid.append(url)
        self.discovery_stats = {"raw_urls": len(raw), "valid_urls": len(valid), "excluded_urls": len(skipped),
                                "duplicates": raw_duplicates, "deduplicated_entries_including_priority": duplicates,
                                "sitemaps": sitemaps, "skipped": skipped,
                                "http_requests": self.http.request_count, "http_retries": self.http.retry_count}
        if not valid: raise DiscoveryError("No permitted URLs; no cursor advancement allowed")
        self.manifest_urls = valid
        self.discovery_stats["manifest_sha256"] = hashlib.sha256(json.dumps(valid,separators=(",", ":")).encode()).hexdigest()
        return valid, skipped, len(raw)

    def get_candidate_urls(self, max_urls=None):
        valid, _, _ = self.discover_all_urls()
        return valid[:max_urls or settings.MAX_PAGES_TO_CRAWL]

    def get_batch_urls(self, batch_size=25, cursor=0, crawl_all=False):
        if batch_size < 1: raise ValueError("Batch size must be positive")
        valid, _, raw = self.discover_all_urls()
        if crawl_all: return valid, 0, raw, len(valid)
        selected, next_cursor = self.select_batch_urls(valid, batch_size, cursor)
        return selected, next_cursor, raw, len(valid)

    def select_batch_urls(self, valid, batch_size, cursor, remaining=None):
        core = [normalize_url(u) for u in self.CORE_PRIORITY_URLS if normalize_url(u) in valid]
        rotating = [u for u in valid if u not in core]
        if not rotating: return core[:batch_size], 0
        # Keep the existing cursor's meaning: an offset in the non-core pool.
        selected_core = core if batch_size > len(core) else []
        rotating_count = min(batch_size - len(selected_core), len(rotating), remaining if remaining is not None else len(rotating))
        current = cursor % len(rotating)
        selected = [rotating[(current+i) % len(rotating)] for i in range(rotating_count)]
        return selected_core + selected, (current+rotating_count) % len(rotating)

    def crawl_url_detailed(self, url):
        try:
            reason = self.exclusion_reason(url)
            if reason: return {"status": "skipped", "reason": reason, "data": None, "http_status": None}
            response = self.http.get(url)
            if response.status_code != 200:
                return {"status": "failed", "reason": f"HTTP {response.status_code}", "data": None, "http_status": response.status_code}
            final_url = normalize_url(response.url or url)
            content_type = response.headers.get("Content-Type", "text/html").lower()
            if "html" not in content_type:
                return {"status": "skipped", "reason": "non_html_requires_review", "data": None, "http_status": 200}
            html = response.content.decode("utf-8", errors="replace")
            canonical_tag = BeautifulSoup(html, "html.parser").find("link", rel="canonical")
            canonical = normalize_url(urllib.parse.urljoin(final_url, canonical_tag.get("href", ""))) if canonical_tag else final_url
            if not transport_equivalent_url(final_url, url) or not transport_equivalent_url(canonical, url):
                self.http.validate_url(canonical)
                return {"status": "skipped", "reason": "redirect_or_canonical_alias_requires_review", "canonical_url": canonical, "data": None, "http_status": 200}
            extracted = PageExtractor.clean_html(html, normalize_url(url))
            if not extracted or len(extracted.get("content", "").strip()) < 60:
                return {"status": "skipped", "reason": "empty_short_iframe_or_javascript_requires_review", "data": None, "http_status": 200}
            return {"status": "success", "data": extracted, "reason": "", "http_status": 200}
        except CrawlCancelled:
            return {"status": "cancelled", "data": None, "reason": "stop_requested"}
        except (requests.RequestException, CrawlPolicyError, DiscoveryError) as error:
            return {"status": "failed", "data": None, "reason": str(error), "http_status": None}

    def crawl_url(self, url: str) -> Optional[Dict[str, Any]]:
        """
        Fetches a single page with timeout and rate limiting, decodes UTF-8 explicitly,
        and extracts high-quality structured content. Backward compatible with earlier tests.
        """
        res = self.crawl_url_detailed(url)
        return res.get("data")

    def run(self, output_path: Optional[Path] = None) -> List[Dict[str, Any]]:
        """Executes full crawl process, merges with curated seeds, and saves to JSON."""
        out_file = output_path or settings.KNOWLEDGE_JSON_PATH
        out_file.parent.mkdir(parents=True, exist_ok=True)

        logger.info("=== Starting WeWIN Data Extraction Phase ===")
        knowledge_base = list(get_curated_seeds())
        crawled_urls = {normalize_url(item["url"]) for item in knowledge_base}

        targets = self.get_candidate_urls()
        success_count = 0

        for idx, url in enumerate(targets, start=1):
            logger.info(f"[{idx}/{len(targets)}] Processing: {url}")
            result = self.crawl_url(url)
            if result:
                norm_u = normalize_url(url)
                if norm_u not in crawled_urls:
                    knowledge_base.append(result)
                    crawled_urls.add(norm_u)
                    success_count += 1
                else:
                    logger.info(f"URL {url} already covered by curated seeds, skipping duplicate.")

        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(knowledge_base, f, ensure_ascii=False, indent=2)

        logger.info(f"=== Extraction Completed! Total articles: {len(knowledge_base)} ({success_count} newly crawled) ===")
        return knowledge_base
