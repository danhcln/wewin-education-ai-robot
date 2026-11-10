"""Windows workstation startup; no secrets, crawler or process termination."""
import argparse
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DEFAULT_CONFIG = ROOT / '.maintenance/control-center/startup-config.json'


def load_config(path=DEFAULT_CONFIG):
    value = json.loads(Path(path).read_text(encoding='utf-8'))
    if set(value) != {'python', 'database', 'bridge_status', 'directory'}:
        raise ValueError('Unexpected startup config keys')
    for name in value:
        value[name] = Path(value[name]).resolve(strict=True) if name in ('python', 'database') else Path(value[name]).resolve()
    private = (ROOT / '.maintenance').resolve()
    for name in ('database', 'bridge_status', 'directory'):
        if not value[name].is_relative_to(private):
            raise ValueError('Startup state must remain private')
    if value['python'].name.lower() != 'python.exe' or value['directory'] != (ROOT / '.maintenance/control-center').resolve():
        raise ValueError('Unexpected executable or operational directory')
    return value


def service_environment(config):
    return {**os.environ, 'PYTHONPATH': str(ROOT), 'DATABASE_PATH': str(config['database']),
            'BRIDGE_STATUS_PATH': str(config['bridge_status']), 'AUTO_SYNC_ENABLED': 'false',
            'SYNC_SCHEDULE_ARMED': 'false', 'DEBUG': 'false', 'MEDIA_BACKEND_URL': 'http://127.0.0.1:8000'}


class WindowsSystem:
    def inventory(self):
        import psutil
        result = {'backend': [], 'bridge': [], 'foreign_bridges': [], 'listeners': []}
        for process in psutil.process_iter(['name', 'cmdline']):
            try:
                if not (process.info['name'] or '').lower().startswith('python'):
                    continue
                argv = process.info['cmdline'] or []
                if 'src.api.app:app' in argv and 'uvicorn' in argv:
                    role = 'backend' if Path(process.cwd()).resolve().is_relative_to(ROOT) else 'foreign_bridges'
                elif any(Path(arg).name in ('run_bridge.py', 'observe_bridge.py') for arg in argv):
                    scripts = [arg for arg in argv if Path(arg).name == 'run_bridge.py']
                    owned = scripts and (Path(process.cwd()) / scripts[0]).resolve() == ROOT / 'run_bridge.py'
                    role = 'bridge' if owned else 'foreign_bridges'
                else:
                    continue
                env = process.environ()
                database = Path(env.get('DATABASE_PATH') or ROOT / 'data/wewin_fts.db')
                if not database.is_absolute():
                    database = ROOT / database
                status = Path(env.get('BRIDGE_STATUS_PATH') or database.parent / 'bridge-status.json')
                result[role].append({'pid': process.pid, 'created': process.create_time(),
                                     'database': str(database.resolve()), 'status_path': str(status.resolve())})
            except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                # Unreadable process identity is a reason to refuse a new connection.
                try:
                    if process.is_running():
                        result['foreign_bridges'].append({'pid': process.pid, 'identity_unknown': True})
                except psutil.NoSuchProcess:
                    pass
        result['listeners'] = [{'ip': item.laddr.ip, 'pid': item.pid}
                               for item in psutil.net_connections('tcp')
                               if item.status == 'LISTEN' and item.laddr.port == 8000]
        return result

    def health(self):
        import httpx
        try:
            with httpx.Client(timeout=2, trust_env=False) as client:
                response = client.get('http://127.0.0.1:8000/health')
                value = response.json()
                return (response.status_code == 200 and value.get('service') == 'WeWIN AI Website Connector'
                        and value.get('status') == 'healthy' and value.get('database_ok') is True)
        except (httpx.HTTPError, ValueError):
            return False

    def tools(self):
        import httpx
        try:
            with httpx.Client(timeout=2, trust_env=False) as client:
                value = client.get('http://127.0.0.1:8000/api/mcp/tools').json()
                return {tool['name'] for tool in value.get('tools', [])}
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            return set()

    def spawn(self, role, config):
        if role == 'backend':
            argv = [str(config['python']), '-B', '-m', 'uvicorn', 'src.api.app:app', '--host',
                    '127.0.0.1', '--port', '8000', '--workers', '1', '--loop', 'asyncio',
                    '--http', 'h11', '--no-access-log']
        else:
            argv = [str(config['python']), '-B', str(ROOT / 'run_bridge.py')]
        log_path = config['directory'] / (role + '.log')
        if log_path.exists() and log_path.stat().st_size > 5 * 1024 * 1024:
            for number in range(3, 0, -1):
                old = log_path.with_suffix('.log.' + str(number))
                if number == 3:
                    old.unlink(missing_ok=True)
                elif old.exists():
                    old.replace(log_path.with_suffix('.log.' + str(number + 1)))
            log_path.replace(log_path.with_suffix('.log.1'))
        with log_path.open('ab') as log:
            process = subprocess.Popen(argv, cwd=config['directory'], env=service_environment(config),
                                       stdout=log, stderr=subprocess.STDOUT,
                                       creationflags=subprocess.CREATE_NO_WINDOW)
        return process.pid

    @staticmethod
    def sleep(seconds):
        time.sleep(seconds)


def bridge_state(record, now=None):
    now = time.time() if now is None else now
    try:
        path = Path(record['status_path'])
        if path.stat().st_size > 2048:
            return 'UNKNOWN'
        value = json.loads(path.read_text(encoding='utf-8'))
        updated = float(value['updated_at'])
        if value['pid'] != record['pid'] or updated < record['created'] - 1 or not 0 <= now - updated <= 45:
            return 'UNKNOWN'
        return 'CONNECTED' if value['state'] == 'connected' else 'DISCONNECTED'
    except (OSError, ValueError, KeyError, TypeError):
        return 'UNKNOWN'


def check_services(config, system=None):
    system = system or WindowsSystem()
    inventory = system.inventory()
    backend_ok = system.health()
    backend, bridges, listeners = inventory['backend'], inventory['bridge'], inventory['listeners']
    correct_owner = (len(backend) == 1 and len(listeners) == 1 and listeners[0]['ip'] == '127.0.0.1'
                     and listeners[0]['pid'] == backend[0]['pid'])
    state = bridge_state(bridges[0]) if len(bridges) == 1 else 'DISCONNECTED'
    profile = all(Path(record['database']).resolve() == config['database'] for record in [*backend, *bridges])
    names = system.tools() if backend_ok else set()
    return {'Backend': 'HEALTHY' if backend_ok and correct_owner else 'DOWN', 'Bridge': state,
            'BridgeCount': len(bridges), 'BackendCount': len(backend), 'XiaoZhi': 'UNKNOWN',
            'ConnectorDynamicToolLoaded': 'wewin_prepare_audio' in names, 'ConnectorToolCount': len(names),
            'ConfiguredProfileMatches': profile, 'ForeignBridgeCandidates': len(inventory['foreign_bridges']),
            'BackendPids': [p['pid'] for p in backend], 'BridgePids': [p['pid'] for p in bridges]}


def ensure_services(config, system=None, emit=None, health_attempts=60, bridge_attempts=30):
    """Caller owns launcher OS lock. Never kill or restart an existing process."""
    system = system or WindowsSystem()
    emit = emit or (lambda *args: None)
    state = system.inventory()
    if len(state['backend']) > 1 or len(state['bridge']) > 1 or state['foreign_bridges']:
        raise RuntimeError('Ambiguous process inventory')
    if state['listeners'] and not state['backend']:
        raise RuntimeError('Port 8000 has an unidentified owner')
    if state['backend'] and (len(state['listeners']) != 1 or state['listeners'][0]['ip'] != '127.0.0.1'
                            or state['listeners'][0]['pid'] != state['backend'][0]['pid']):
        raise RuntimeError('Backend listener ownership mismatch')
    if state['backend']:
        if not system.health():
            raise RuntimeError('Existing backend is unhealthy; no automatic restart')
        emit('backend_reused')
    else:
        emit('backend_start', system.spawn('backend', config))
    for _ in range(health_attempts):
        if system.health():
            break
        system.sleep(.5)
    else:
        raise RuntimeError('Backend health deadline; no bridge started')
    state = system.inventory()
    if (len(state['backend']) != 1 or len(state['listeners']) != 1
            or state['listeners'][0]['pid'] != state['backend'][0]['pid']
            or state['listeners'][0]['ip'] != '127.0.0.1'):
        raise RuntimeError('Backend identity not confirmed; no bridge started')
    if 'wewin_prepare_audio' not in system.tools():
        raise RuntimeError('Existing backend needs manual code activation')
    if len(state['bridge']) > 1 or state['foreign_bridges']:
        raise RuntimeError('Ambiguous bridge inventory')
    if not state['bridge']:
        emit('bridge_start', system.spawn('bridge', config))
    else:
        emit('bridge_reused', state['bridge'][0]['pid'])
    for _ in range(bridge_attempts):
        result = check_services(config, system)
        if result['BridgeCount'] > 1:
            raise RuntimeError('Multiple bridges; no automatic termination')
        if result['Backend'] == 'HEALTHY' and result['BridgeCount'] == 1 and result['Bridge'] == 'CONNECTED':
            return result
        system.sleep(1)
    raise RuntimeError('Bridge not yet verified; keep existing reconnect owner')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--open-media', action='store_true')
    args = parser.parse_args()
    try:
        config = load_config(args.config)
        if args.check or args.dry_run:
            result = check_services(config)
            if args.dry_run:
                result.update({'mode': 'PLAN_ONLY', 'starts_processes': False, 'website_sync': False})
        else:
            if os.name != 'nt':
                raise RuntimeError('Windows startup only')
            from scripts.rotate_admin_token import restrict_directory
            from src.sync.locking import SyncLock
            from scripts.server_ops import inspect
            # Do not let an accidental empty/new path cause startup seeding.
            if inspect(config['database'])['fts']['pages'] < 1:
                raise RuntimeError('Existing runtime knowledge required')
            restrict_directory(config['directory'])
            log = logging.getLogger('wewin_startup')
            log.setLevel(logging.INFO)
            handler = RotatingFileHandler(config['directory'] / 'services.log', maxBytes=1024*1024,
                                          backupCount=3, encoding='utf-8')
            handler.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
            log.addHandler(handler)
            guard = SyncLock(config['directory'] / 'launcher.lock')
            guard.acquire('control_center_start')
            try:
                result = ensure_services(config, emit=lambda event, pid=None: log.info('%s pid=%s', event, pid))
                log.info('ready backend=%s bridge_count=%s bridge=%s', result['Backend'], result['BridgeCount'], result['Bridge'])
            finally:
                guard.release()
            if args.open_media:
                import webbrowser
                webbrowser.open('http://127.0.0.1:8000/media')
        if sys.stdout:
            print(json.dumps(result, ensure_ascii=True))
        if args.check and (result['Backend'] != 'HEALTHY' or result['BridgeCount'] != 1 or result['Bridge'] != 'CONNECTED'):
            return 2
        return 0
    except Exception as exc:
        if sys.stdout:
            print(json.dumps({'status': 'operator_attention_required', 'error_type': type(exc).__name__}))
        logging.getLogger('wewin_startup').error('operator_attention_required type=%s', type(exc).__name__)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
