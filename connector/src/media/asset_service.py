"""Explicit, immutable imports of owner-approved original audio. No YouTube extraction."""
import hashlib
import json
import os
from pathlib import Path
import re
import threading

from .youtube import MediaError, video_id


_locks = {}
_locks_guard = threading.Lock()


class AssetService:
    def __init__(self, root):
        self.root = Path(root).resolve()
        with _locks_guard:
            self.lock = _locks.setdefault(str(self.root), threading.RLock())

    def import_manifest(self, record, allowed_root):
        """Operator-only import. Callers cannot turn a URL into an audio source."""
        if record.get('user_authorized') is not True or record.get('youtube_source') is not False:
            raise ValueError('original_audio_authorization_required')
        asset = record.get('asset_id', '')
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', asset):
            raise ValueError('invalid_asset_id')
        source = Path(record['output_path']).resolve(strict=True)
        if not source.is_relative_to(Path(allowed_root).resolve(strict=True)):
            raise ValueError('asset_outside_approved_root')
        if not source.is_file() or not 0 < source.stat().st_size <= 64 * 1024 * 1024:
            raise ValueError('asset_size_limit')
        data = source.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if not data.startswith(b'OggS') or b'OpusHead' not in data[:64] or digest != record.get('output_sha256', '').lower():
            raise ValueError('asset_integrity_failed')
        vid = record.get('youtube_video_id')
        if vid is not None:
            video_id(vid)
            if record.get('mapping_verified') is not True:
                raise ValueError('mapping_verification_required')
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Exclusive files and no replacement: existing approved versions survive retries.
        target = self.root / (asset + '-' + digest + '.ogg')
        metadata = self.root / (asset + '.json')
        with self.lock:
            if metadata.exists():
                raise ValueError('asset_already_imported')
            if not target.exists():
                with target.open('xb') as out:
                    out.write(data)
            entry = {'schema_version': 1, 'revision': 1, 'asset_id': asset, 'sha256': digest, 'file': target.name,
                     'youtube_video_id': vid, 'rights_status': 'approved',
                     'mapping_verified': bool(vid), 'duration_ms': int(record.get('clip_seconds', 0) * 1000)}
            with metadata.open('x', encoding='utf-8') as out:
                json.dump(entry, out)
        return self.public(entry)

    def get(self, asset):
        if not isinstance(asset, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', asset):
            raise MediaError('invalid_asset', 'Asset không hợp lệ.')
        try:
            record = json.loads((self.root / (asset + '.json')).read_text(encoding='utf-8'))
            path = (self.root / record['file']).resolve(strict=True)
            if not path.is_relative_to(self.root) or record['rights_status'] != 'approved':
                raise ValueError()
            if hashlib.sha256(path.read_bytes()).hexdigest() != record['sha256']:
                raise ValueError()
            return record, path
        except (OSError, ValueError, KeyError):
            raise MediaError('audio_source_unavailable', 'Chưa có audio gốc được duyệt.') from None

    def inventory(self):
        rows=[]
        if self.root.exists():
            for path in self.root.glob('*.json'):
                try:
                    row=json.loads(path.read_text(encoding='utf-8'))
                    rows.append({**self.public(row),'revision':row.get('revision',1),
                                 'mapping_verified':row.get('mapping_verified',False)})
                except (OSError,ValueError,KeyError):continue
        return rows

    def set_mapping(self, asset, vid, revision, confirmed=False, revoke=False):
        if not confirmed:raise MediaError('mapping_confirmation_required','Xác nhận đúng nội dung và quyền phát.')
        if vid is not None:video_id(vid)
        with self.lock:
            record,_=self.get(asset)
            if record.get('revision',1)!=revision:raise MediaError('stale_asset_revision','Asset đã thay đổi; tải lại.')
            if vid and any(r['asset_id']!=asset and r['rights_status']=='approved' and r.get('mapping_verified') and r['youtube_video_id']==vid for r in self.inventory()):
                raise MediaError('mapping_conflict','Video đã có một asset được duyệt.')
            record.update(youtube_video_id=vid,mapping_verified=bool(vid),revision=revision+1)
            if revoke:record.update(rights_status='revoked',mapping_verified=False)
            from uuid import uuid4
            temporary=self.root/(asset+'-'+uuid4().hex+'.tmp')
            try:
                with temporary.open('x',encoding='utf-8') as out:
                    json.dump(record,out);out.flush();os.fsync(out.fileno())
                os.replace(temporary,self.root/(asset+'.json'))
            finally:
                temporary.unlink(missing_ok=True)
            return {**self.public(record),'revision':record['revision']}

    def for_video(self, vid):
        video_id(vid)
        matches=[]
        with self.lock:
            for row in self.inventory():
                if row.get('mapping_verified') and row.get('youtube_video_id')==vid and row['rights_status']=='approved':
                    matches.append(self.get(row['asset_id']))
        if len(matches)==1:return matches[0]
        if len(matches)>1:raise MediaError('mapping_conflict','Mapping bị trùng; cần operator kiểm tra.')
        raise MediaError('audio_source_unavailable', 'Video chưa có mapping audio gốc được duyệt.')

    @staticmethod
    def public(record):
        return {k: record[k] for k in ('asset_id', 'sha256', 'youtube_video_id', 'rights_status', 'duration_ms')}


def get_assets():
    return AssetService(os.getenv('WEWIN_ASSET_ROOT', str(Path(__file__).resolve().parents[2] / '.maintenance/media-assets')))
