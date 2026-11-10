"""Legacy host denylist for the new runtime, never a vendor API adapter."""
from urllib.parse import urlsplit

LEGACY=('xiaozhi.me','tenclass.net','xiaozhi-api.tandev282.workers.dev')


def reject_legacy(url):
    host=(urlsplit(url).hostname or '').lower().rstrip('.')
    if any(host==domain or host.endswith('.'+domain) for domain in LEGACY):raise ValueError('Legacy XiaoZhi/TanDev endpoints are forbidden in the independent runtime')
