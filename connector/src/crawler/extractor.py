"""
HTML Parser and Content Extractor for WeWIN Webpages.
Cleans noise, scripts, navigation boilerplate, fixes UTF-8 encoding/mojibake,
and extracts structured educational content.
"""
import re
import hashlib
import unicodedata
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Set
from bs4 import BeautifulSoup

def fix_vietnamese_mojibake(text: str) -> str:
    """
    Detects and repairs classic Latin-1 / Windows-1252 mojibake of UTF-8 Vietnamese.
    Example: 'Trang chá»§' -> 'Trang chủ'
    """
    if not text:
        return ""
    # Check for characteristic mojibake sequences
    if any(marker in text for marker in ["chá»§", "Ã¡", "Ã ", "á»", "áº", "Ä‘", "Ä"]):
        try:
            fixed = text.encode("latin1").decode("utf-8")
            return unicodedata.normalize("NFC", fixed)
        except Exception:
            pass
    return unicodedata.normalize("NFC", text)

class PageExtractor:
    # Tags to completely remove
    DROP_TAGS = [
        "script", "style", "noscript", "svg", "canvas",
        "header", "nav", "footer", "form", "select", "button"
    ]

    # Exact class or id tokens representing global boilerplate, navigation, or popups
    EXACT_DROP_CLASSES: Set[str] = {
        "site-header", "site-footer", "header-wrapper", "footer-wrapper",
        "top-bar", "header-nav", "nav-menu", "nav-dropdown", "mobile-nav",
        "main-navigation", "sidebar", "widget-area", "comments-area",
        "comment-respond", "cookie-notice", "cookie-law-info-bar", "social-icons",
        "share-box", "post-share", "share-icons", "breadcrumbs", "woocommerce-breadcrumb"
    }

    @classmethod
    def clean_html(cls, html_content: str, url: str) -> Optional[Dict[str, Any]]:
        """Parses HTML and extracts a structured clean content dictionary."""
        if not html_content or not html_content.strip():
            return None

        # Ensure input is normalized and free from mojibake
        html_content = fix_vietnamese_mojibake(html_content)
        soup = BeautifulSoup(html_content, "html.parser")

        # Extract title
        title = ""
        if soup.title and soup.title.string:
            title = soup.title.string.strip()
        elif soup.find("h1"):
            title = soup.find("h1").get_text(strip=True)

        # Fix any mojibake in title and clean standard WordPress suffixes
        title = fix_vietnamese_mojibake(title)
        title = re.sub(r"\s*[-|–]\s*(wewinedu|WeWIN.*)$", "", title, flags=re.IGNORECASE).strip()

        # Extract meta description
        meta_desc = ""
        desc_tag = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
        if desc_tag and desc_tag.get("content"):
            meta_desc = fix_vietnamese_mojibake(desc_tag["content"].strip())

        # Inspect iframes before dropping: preserve reference if it points to useful material (e.g. Google Forms, documents)
        iframe_notes = []
        for iframe in soup.find_all("iframe"):
            src = iframe.get("src", "")
            if src and any(k in src.lower() for k in ["forms.gle", "docs.google.com", "flipbuilder", "wewin/files"]):
                iframe_notes.append(f"[Tài liệu hoặc biểu mẫu đính kèm: {src}]")
            iframe.decompose()

        # Remove drop tags
        for tag_name in cls.DROP_TAGS:
            for el in soup.find_all(tag_name):
                el.decompose()

        # Remove elements with exact noise classes
        for el in list(soup.find_all(attrs={"class": True})):
            if not el or getattr(el, "attrs", None) is None:
                continue
            classes = el.attrs.get("class", [])
            if isinstance(classes, list):
                class_set = {str(c).lower() for c in classes}
            else:
                class_set = {str(classes).lower()}
            if class_set.intersection(cls.EXACT_DROP_CLASSES):
                el.decompose()

        for el in list(soup.find_all(attrs={"id": True})):
            if not el or getattr(el, "attrs", None) is None:
                continue
            id_val = str(el.attrs.get("id", "")).lower()
            if id_val in cls.EXACT_DROP_CLASSES:
                el.decompose()

        # Try to locate the main content wrapper (Flatsome and WordPress standard hierarchy)
        main_content_el = (
            soup.find("div", class_="entry-content") or
            soup.find("div", class_="post-content") or
            soup.find("article") or
            soup.find("div", id="content") or
            soup.find("main") or
            soup.find("body")
        )

        if not main_content_el:
            return None

        raw_text = main_content_el.get_text(separator="\n", strip=True)

        # Normalize whitespace, lines, and Unicode
        lines = []
        for line in raw_text.splitlines():
            line_str = re.sub(r"[ \t]+", " ", line).strip()
            line_str = fix_vietnamese_mojibake(line_str)
            # Filter out single character junk lines or common navigation artifacts
            if line_str and len(line_str) > 2:
                lines.append(line_str)

        # Remove consecutive duplicate lines
        dedup_lines = []
        for line in lines:
            if not dedup_lines or dedup_lines[-1] != line:
                dedup_lines.append(line)

        cleaned_text = "\n".join(dedup_lines)
        cleaned_text = unicodedata.normalize("NFC", cleaned_text)

        # Require real body text BEFORE supplementing it with attachment URLs.
        # An embedded form/document link alone is not searchable knowledge.
        if len(cleaned_text) < 60:
            return None

        if iframe_notes:
            cleaned_text = "\n".join([cleaned_text, *dict.fromkeys(iframe_notes)])

        # Determine category from URL or content
        category = cls._infer_category(url, cleaned_text)

        # Calculate stable SHA-256 of normalized text for change detection
        normalized = " ".join(cleaned_text.strip().split())
        content_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()

        return {
            "title": title or "WeWIN Education",
            "url": url,
            "category": category,
            "meta_description": meta_desc,
            "content": cleaned_text,
            "content_hash": content_hash,
            "source_type": "scraped",
            "retrieved_at": datetime.now(timezone.utc).isoformat()
        }

    @staticmethod
    def _infer_category(url: str, text: str) -> str:
        u = url.lower()
        t = text.lower()
        # Overview / Homepage
        if u.rstrip("/") in ("https://wewin.edu.vn", "http://wewin.edu.vn"):
            return "overview"
        # Recruitment / Careers
        # Teacher resources and "describe your dream job" are educational pages.
        # A teacher/job word alone is not evidence of a recruitment announcement.
        if any(k in u for k in ["tuyen-dung", "can-tuyen", "recruitment", "hiring", "thuc-tap-sinh", "nhan-vien"]):
            return "careers"
        # Materials & Curriculum
        if any(k in u for k in ["tai-lieu", "giao-an", "sach", "book", "grammar-friends", "family-and-friends", "lesson-plan", "learning-resources"]):
            return "materials"
        # IELTS
        if "ielts" in u or "ielts" in t:
            return "ielts"
        # Cambridge
        # Match exam names as slug tokens; Vietnamese "ket-hop" means combine,
        # not the Cambridge KET exam. Substring matching mislabels programmes.
        if re.search(r"(?:^|[-/_.])(?:cambridge|starters|movers|flyers|pet|ket(?!-hop(?:[-/]|$)))(?=[-/_.]|$)", u):
            return "cambridge"
        # Kids & Preschool
        if any(k in u for k in ["kids", "mam-non", "mamnon", "preschool"]):
            return "kids"
        # About
        if any(k in u for k in ["about", "gioi-thieu", "ve-chung-toi"]):
            return "about"
        # Contact
        if any(k in u for k in ["contact", "lien-he", "dia-chi", "hotline"]):
            return "contact"
        return "general"
