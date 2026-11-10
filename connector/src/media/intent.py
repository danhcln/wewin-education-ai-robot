"""Deterministic Vietnamese media intents; Cloud chooses this tool, not raw audio STT."""
import re
import unicodedata


def normalized(text):
    text = unicodedata.normalize('NFD', text.casefold().replace('đ', 'd'))
    text = ''.join(c for c in text if not unicodedata.combining(c))
    return re.sub(r'[^a-z0-9]+', ' ', text).strip()


def intent(text, active=False):
    if not isinstance(text, str) or not 1 <= len(text) <= 200:
        return {'action': 'invalid'}
    q = normalized(text)
    if q in ('bai tiep theo', 'phat bai tiep theo', 'next', 'video tiep theo'):
        return {'action': 'next'}
    if q in ('video dang phat gi', 'dang xem video gi', 'trang thai video'):
        return {'action': 'status'}
    if q in ('tat video', 'dong video', 'dung video', 'tat', 'dung lai', 'stop video', 'dung phat', 'stop'):
        return {'action': 'stop'}
    if q in ('ngung', 'tam dung', 'dung lai mot chut', 'pause'):
        return {'action': 'pause' if active else 'no_media_context'}
    if q in ('tiep tuc', 'phat tiep', 'resume'):
        return {'action': 'resume' if active else 'no_media_context'}
    if q in ('tat tieng robot', 'tat loa robot', 'tat tieng', 'tat loa', 'im lang', 'mute robot', 'mute'):
        return {'action': 'mute_robot'}
    if q in ('bat tieng robot', 'bat loa robot', 'bat tieng', 'bat loa', 'unmute robot', 'unmute'):
        return {'action': 'unmute_robot'}
    if q in ('tang am luong', 'tang am', 'cho to len', 'to hon', 'lon hon', 'tang volume', 'volume up'):
        return {'action': 'increase_volume', 'delta': 10}
    if q in ('giam am luong', 'giam am', 'cho nho lai', 'nho hon', 'giam volume', 'volume down'):
        return {'action': 'decrease_volume', 'delta': -10}

    m_vol = re.search(r'(?:am luong|volume|dat am luong|dat volume)\s+(\d+)(?:\s*(?:phan tram|%))?', q)
    if m_vol:
        val = int(m_vol.group(1))
        return {'action': 'set_volume', 'value': max(0, min(100, val))}
    m_vol2 = re.search(r'(\d+)\s*(?:phan tram|%)\s*(?:am luong|volume)', q)
    if m_vol2:
        val = int(m_vol2.group(1))
        return {'action': 'set_volume', 'value': max(0, min(100, val))}

    patterns = (
        ('replace', r'^(?:chuyen sang(?: video)?|mo video khac)\s+'),
        ('play', r'^(?:cho toi xem video|cho xem video|bat video|phat video|mo video|mo bai hoc ve|phat bai hoc ve|bat bai|phat bai|mo bai)\s+')
    )
    for action, pattern in patterns:
        m = re.match(pattern, q)
        if m:
            matched_prefix = q[:m.end()]
            query = re.sub(r'\s+(?:cua wewin(?: education)?|thay video nay)$', '', q[m.end():]).strip()
            if 'bai hoc ve' in matched_prefix and not query.startswith('bai hoc ve'):
                query = 'bai hoc ve ' + query
            return {'action': action, 'query': query} if query else {'action': 'invalid'}
    return {'action': 'unrecognized'}
