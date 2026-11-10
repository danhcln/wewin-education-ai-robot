"""Read-only local evidence for Cloud onboarding, never proof of API authorization."""
import sqlite3
import time
from urllib.parse import urlsplit
from .db import connection
from .integrations import SOURCE_DB, settings, read_status


def source_cloud_evidence(robot_id):
    # Explicit projection: no credential reference, key, cookie, token or payload.
    try:
        with connection(SOURCE_DB, readonly=True) as db:
            row = db.execute('''SELECT r.name,r.site_id,r.wire_id,r.external_device_id,
                r.external_mapping_source,r.external_verified_at,
                i.provider,i.agent_reference,i.endpoint_origin,i.enabled,
                i.authorization_state,i.authorization_observed_at,i.revoked_at,
                i.site_id AS integration_site_id,
                o.observed_at,o.evidence_source,o.firmware_version
                FROM robots r LEFT JOIN integrations i ON i.id=r.integration_id
                LEFT JOIN robot_observations o ON o.robot_id=r.id
                WHERE r.id=? AND r.pairing_state='active' ''', (robot_id,)).fetchone()
        if row is None:
            return {}
        result = dict(row)
        origin = result.pop('endpoint_origin', None)
        # Even malformed/legacy registry URLs cannot send query secrets to the UI.
        result['endpoint_host'] = urlsplit(origin).hostname if origin else None
        return result
    except (sqlite3.Error, OSError, ValueError):
        return {'unavailable': True}


def cloud_readiness(robot_id, profile, capabilities):
    evidence = source_cloud_evidence(robot_id)
    same_site = bool(evidence.get('site_id') and evidence.get('site_id') == evidence.get('integration_site_id'))
    integration_active = bool(same_site and evidence.get('enabled') and not evidence.get('revoked_at'))
    # Registry/operator claims and environment presence are evidence to review;
    # neither is a remote permission, tenant match, or a device acknowledgment.
    mapping_recorded = bool(integration_active and evidence.get('agent_reference') and evidence.get('external_device_id'))
    requested_agent = profile['agent_reference'] if profile else None
    mismatch = bool(requested_agent and evidence.get('agent_reference') and requested_agent != evidence['agent_reference'])
    checks = [
        {'code': 'provider_binding', 'title': 'Cloud đang điều khiển robot',
         'status': 'metadata_only' if integration_active else 'missing',
         'detail': 'Registry có thông tin nhà cung cấp; cần đối chiếu bằng API được cấp quyền.' if integration_active else 'Registry chưa có tích hợp Cloud hợp lệ cùng site. URL Console và MCP hostname chưa xác nhận provider của robot.'},
        {'code': 'agent_mapping', 'title': 'Monster Desk → đúng Agent',
         'status': 'conflict' if mismatch else 'metadata_only' if mapping_recorded else 'missing',
         'detail': 'Agent trong hồ sơ Portal khác Agent trong Registry. Chưa được phép Apply.' if mismatch else 'Cần đối chiếu Device ID/MAC/serial, Agent ID và owner/tenant bằng nguồn được nhà cung cấp xác nhận. Tên robot không đủ để xác định thiết bị.'},
        {'code': 'management_authorization', 'title': 'Quyền Developer/API', 'status': 'unverified',
         'detail': 'Cần credential quản lý được nhà cung cấp cấp cho tài khoản/tenant và quyền đọc/sửa đúng Agent. Đăng nhập Portal hoặc token MCP không chứng minh quyền này.'},
        {'code': 'server_credential', 'title': 'Credential quản lý trên server',
         'status': 'present_unverified' if capabilities['credential_configured'] else 'missing',
         'detail': 'Đã có giá trị tại biến môi trường được chỉ định; chưa xác minh tính hợp lệ/quyền.' if capabilities['credential_configured'] else 'Chưa có credential tại biến môi trường của hồ sơ Portal. Không nhập key/token/cookie vào chat hoặc form.'},
        {'code': 'provider_contract', 'title': 'API/SDK và khả năng thực tế',
         'status': 'metadata_only' if profile else 'missing',
         'detail': 'Cần tài liệu được cấp quyền cho read/update, model/voice catalog, field mapping và chống ghi đè. Hồ sơ kết nối không phải contract đã xác minh.'},
        {'code': 'cloud_readback', 'title': 'Đọc lại và so sánh cấu hình', 'status': 'unsupported',
         'detail': 'Chưa có provider HTTP adapter được phép chạy. Chưa kiểm thử timeout, lỗi quyền hoặc readback với Cloud thật.'},
        {'code': 'robot_verification', 'title': 'Vai trò trong cuộc trò chuyện tiếp theo', 'status': 'unverified',
         'detail': 'Chưa có bằng chứng robot nhận cấu hình. Readback Agent riêng lẻ không chứng minh hành vi hoặc acknowledgment của thiết bị.'},
    ]
    return {
        'checked_at': int(time.time()), 'evidence_scope': 'local_read_only',
        'ready': False, 'cloud_requests_sent': False, 'apply_supported': False,
        'console_url': 'https://xiaozhi.me/console/agents',
        'registry': evidence,
        'requested_agent': requested_agent,
        'mcp': {'endpoint_host': urlsplit(settings.XIAOZHI_MCP_ENDPOINT).hostname,
                'heartbeat': read_status(), 'proves_agent_management': False},
        'checks': checks,
        'next_action': 'Xin quyền Developer/API và contract từ đơn vị quản lý Console/TanDev; cung cấp tài liệu, Agent ID và nguồn credential trên server để triển khai adapter. Không có thao tác đổi cờ để mở Apply.',
    }
