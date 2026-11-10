"""Management adapter boundary. MCP credentials never authorize Agent management.

No HTTP endpoints are guessed or enabled from user-supplied metadata. A provider
implementation may be added only after its supported contract, permission and
device/Agent mapping are verified. The present deployment has no such adapter.
"""
import os
import time
from fastapi import HTTPException
from .db import connection

SYNC_STATES=('draft','saved_backend_only','pending_apply','applying','applied_verified','apply_failed','unsupported','out_of_sync')


class UnsupportedCloudAdapter:
    def __init__(self,link=None):
        self.link=link

    def capabilities(self):
        return {
            'provider':self.link['provider'] if self.link else 'Chưa xác minh Cloud quản lý Agent',
            'management_api_verified':False,'read_supported':False,'apply_supported':False,
            'readback_supported':False,'robot_acknowledged':False,
            'models':[],'voices':[],'languages':[],'catalog_verified':False,
            'credential_configured':bool(self.link and os.environ.get(self.link['credential_env'])),
            'agent_reference':self.link['agent_reference'] if self.link else None,
            'connection_state':self.link['state'] if self.link else 'unconfigured',
            'reason':'Chưa có API quản lý được cấp quyền, binding Agent được xác minh và contract readback. Token MCP không phải credential quản lý Agent.',
            'sync_states':SYNC_STATES,
        }

    def read(self):
        raise HTTPException(409,{'state':'unsupported','message':self.capabilities()['reason']})

    def apply(self,payload):
        raise HTTPException(409,{'state':'unsupported','message':self.capabilities()['reason']})


def adapter_for(robot_id):
    from .self_hosted import linked_adapter
    local=linked_adapter(robot_id)
    if local:return local
    with connection() as db:
        row=db.execute('SELECT * FROM robot_cloud_links WHERE robot_id=?',(robot_id,)).fetchone()
    return UnsupportedCloudAdapter(dict(row) if row else None)


def limit_action(auth,action,maximum=20,seconds=60):
    """Atomic per-user sensitive action limit; persists across process restarts."""
    now=int(time.time())
    with connection() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT * FROM action_limits WHERE user_id=? AND action=?',(auth['user_id'],action)).fetchone()
        if row and now-row['window_start']<seconds:
            if row['count']>=maximum:
                raise HTTPException(429,'Quá nhiều thao tác. Vui lòng thử lại sau một phút.')
            db.execute('UPDATE action_limits SET count=count+1 WHERE user_id=? AND action=?',(auth['user_id'],action))
        else:
            db.execute('INSERT INTO action_limits VALUES(?,?,?,1) ON CONFLICT(user_id,action) DO UPDATE SET window_start=excluded.window_start,count=1',(auth['user_id'],action,now))
