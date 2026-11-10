"""Metadata-only resolver. No media downloads, arbitrary fallback, or single-video mapping."""
from difflib import SequenceMatcher
import re
from .intent import normalized, intent


def title_parts(title):
    # Bilingual titles expose both languages as aliases; branding is not a match.
    return [normalized(x) for x in re.split(r'\|| — | – ', title)
            if normalized(x) and normalized(x) not in ('wewin storyland', 'wewin education')]


def clean_media_query(q_str: str) -> str:
    parsed = intent(q_str)
    if parsed.get('action') in ('play', 'replace') and parsed.get('query'):
        return normalized(parsed['query'])
    n = normalized(q_str)
    n = re.sub(r'^(?:cho toi xem(?: video)?|cho xem(?: video)?|bat video|phat video|mo video|bat bai|phat bai|mo bai|xem video|video|bat|mo|phat)\s+', '', n)
    n = re.sub(r'\s+(?:cua wewin(?: education)?|wewin(?: education)?|thay video nay)$', '', n)
    return n.strip()


class MediaResolver:
    def __init__(self, youtube):
        self.youtube = youtube

    def resolve(self, query, preferred_channel='wewin', current_context=None):
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 160:
            return {'status': 'invalid_query'}
        raw_q = normalized(query)
        q = clean_media_query(query) or raw_q
        search_term = q if q else query.strip()
        result = self.youtube.search(search_term, 'wewin' if preferred_channel == 'wewin' else 'all', 10)
        candidates = []
        for video in result.get('videos', []):
            if preferred_channel == 'wewin' and not video.get('is_wewin'):
                continue
            if not video.get('embeddable'):
                continue
            title = normalized(video['title'])
            aliases = title_parts(video['title'])
            if q == title or raw_q == title:
                score, kind = 1.0, 'exact'
            elif q in aliases or raw_q in aliases:
                score, kind = 1.0, 'alias'
            else:
                score_q = max([SequenceMatcher(None, q, a).ratio() for a in aliases] + [0])
                score_raw = max([SequenceMatcher(None, raw_q, a).ratio() for a in aliases] + [0])
                score = max(score_q, score_raw)
                kind = 'fuzzy'
            candidates.append((score, kind, video))
        candidates.sort(key=lambda x: x[0], reverse=True)
        if not candidates or candidates[0][0] < .80 or (len(candidates) > 1 and candidates[0][0] - candidates[1][0] < .08):
            return {'status': 'ambiguous', 'candidates': [
                {'title': v['title'], 'video_id': v['video_id'], 'confidence': round(s, 3)}
                for s, _, v in candidates[:3]]}
        score, kind, video = candidates[0]
        return {'status': 'resolved', 'media_id': 'youtube:' + video['video_id'],
                'title': video['title'], 'canonical_title': title_parts(video['title'])[0],
                'youtube_video_id': video['video_id'], 'url': video['url'],
                'channel': video.get('channel_title'), 'confidence': round(score, 3), 'match_type': kind}
