"""Shared conservative publication policy. Never deletes the original cache."""
import hashlib
import re
import unicodedata
from urllib.parse import unquote, urlsplit


def text_hash(text):
    normalized = " ".join(unicodedata.normalize("NFC", text or "").strip().split())
    return hashlib.sha256(normalized.encode()).hexdigest() if normalized else ""


def policy_review(url):
    path = unquote(urlsplit(url).path).lower()
    if any(s in path for s in ("sales-playbook", "thong-tin-nhan-vien", "thong-tin-giao-vien-nuoc-ngoai",
                              "quiz4corporateculture", "thong-tin-thuc-tap-sinh")):
        return "staff_or_internal_source_requires_publication_review"
    return ""


def classify(url, title, content, protected_hashes=()):
    """Privacy decision, independent of URL spelling, search terms and page ID.

    Length/duplicate/shrink admission is handled by result_record. Existing short
    legacy records are explicitly held for review by the migration, not deleted.
    """
    if not all(isinstance(value, str) for value in (url, title, content)) or not content.strip():
        return "review", "empty_or_invalid_content"
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.hostname != 'wewin.edu.vn' or parsed.username or parsed.password:
        return "review", "unapproved_public_source"
    if policy_review(url) or re.search(r"sales\s*playbook", title, re.I) or text_hash(content) in protected_hashes:
        return "internal", "staff_or_internal_source"
    if re.search(r"confidential|internal\s+use|nội\s*bộ", title + " " + content, re.I):
        return "internal", "explicit_internal_publication_marker"
    if re.search(r"mật\s*khẩu|password|nội\s*bộ|internal\s+use|confidential|bảo\s*mật", title + " " + content, re.I):
        return "review", "credentials_or_internal_language_requires_review"
    folded = unicodedata.normalize('NFKC', content).casefold().strip()
    if len(content) < 600 and folded.startswith('wewin education') and 'hotline' in folded and content.count('https://') >= 2:
        return "review", "branding_footer_without_lesson_body"
    return "public", "public_content_policy_v1"


def result_record(result, old, hashes):
    """Conservative admission; rejected responses never modify any old column."""
    if result.get("status") != "success" or not result.get("data"):
        return None, {k: v for k, v in result.items() if k != "data"}
    page = dict(result["data"])
    for key in ("title", "category", "content", "url", "retrieved_at"):
        if not isinstance(page.get(key), str) or not page[key].strip():
            return None, {"status": "review", "reason": "invalid_metadata_or_content"}
        page[key] = unicodedata.normalize("NFC", page[key])
    scope, privacy_reason = classify(page["url"], page["title"], page["content"])
    if scope != "public":
        return None, {"status": "review", "reason": privacy_reason}
    content = page["content"].strip()
    reason = ""
    if len(content) < 120:
        reason = "short_body_under_120_requires_review"
    elif re.search(r"<(?:iframe|script|form|html)\b", content, re.I):
        reason = "unextracted_html_requires_review"
    elif any(marker in content for marker in ("\ufffd", "á»", "áº", "Ä‘")):
        reason = "unicode_or_mojibake_requires_review"
    elif re.search(r"mật\s*khẩu|password|nội\s*bộ|internal\s+use|confidential|bảo\s*mật", content, re.I):
        reason = "credentials_or_internal_language_requires_review"
    elif re.search(r"lorem ipsum|page not found|error 404|access denied|verify you are human", content, re.I):
        reason = "placeholder_or_access_error_requires_review"
    elif old and old.get("source_type") == "seed":
        reason = "curated_seed_preserved_proposed_update_requires_review"
    elif old and len(old.get("content", "")) >= 300 and len(content) < len(old["content"]) * 0.5:
        reason = "large_content_shrink_requires_review"
    page["content_hash"] = text_hash(content)
    duplicates = [url for url in hashes.get(page["content_hash"], []) if url != page["url"]]
    if not reason and duplicates:
        reason = "duplicate_content_different_url_requires_review"
    if reason:
        return None, {"status": "review", "reason": reason, "content_chars": len(content), "duplicate_of": duplicates}
    page["content"] = content
    page.update(source_type="scraped", http_status=200)
    changed = not old or any(old.get(k) != page[k] for k in ("title", "category", "content", "content_hash", "source_type"))
    page["last_modified"] = page["retrieved_at"] if changed else old["last_modified"]
    outcome = {"status": "added" if not old else "updated" if changed else "unchanged",
               "title": page["title"], "category": page["category"], "content_chars": len(content),
               "hash": page["content_hash"]}
    if content.count("https://") > 3:
        outcome["quality_note"] = "link_collection_body_review_if_deep_knowledge_required"
    return page, outcome

