"""Listener/capture separation; temporary registry, mocked sockets, no hardware."""
import asyncio
import importlib
import json
from unittest.mock import MagicMock, Mock, patch

from tests.test_voice_media import ControlTests as BaseControlTests
from src.devices.store import DeviceStore
from src.devices.registry import RobotRegistry
from src.media import control_crypto as crypto


class ListenerTests(BaseControlTests):
    def setUp(self):
        super().setUp()
        self.registry = RobotRegistry(DeviceStore(self.root / 'registry.sqlite3'))
        self.registry_patch = patch('src.devices.registry.get_robot_registry', return_value=self.registry)
        self.registry_patch.start()
        self.addCleanup(self.registry_patch.stop)
        self.control.config['enabled'] = False

    def enroll_fixture(self):
        self.registry.enroll_robot('default-site', self.h['device_id'],
            crypto.fingerprint(self.pub), self.pub)

    def test_listener_starts_without_capture_consent(self):
        before = dict(self.control.config)
        with patch('src.media.device_control.socket.socket') as sock, patch('src.media.device_control.threading.Thread') as thread:
            self.control.start()
            self.assertTrue(self.control.status()['listening'])
            sock.return_value.bind.assert_called_once_with(('10.20.30.40', 8767))
            thread.return_value.start.assert_called_once()
            self.assertEqual(before, self.control.config)
            self.assertFalse(self.control.leases)
            self.control.stop()

    def test_disabling_legacy_capture_keeps_listener(self):
        self.control.socket = Mock()
        self.control.configure('', False, False, False)
        self.assertTrue(self.control.status()['listening'])
        self.assertFalse(self.control.config['enabled'])
        self.control.socket.close.assert_not_called()
        self.control.stop()

    def test_enrolled_device_lease_and_observation_with_legacy_disabled(self):
        self.enroll_fixture()
        # Existing fixture helper derives a real ECDH/GCM key; no production pairing.
        welcome, key = self.pair()
        sid = welcome['lease_id']
        with self.registry.store.connection() as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM robot_observations').fetchone()[0], 0)
        packet = crypto.encrypt(key, sid, 1, 0, {'type':'presence','stream':{'state':'IDLE'}})
        self.control.receive(packet, ('10.20.30.41', 5678))
        with self.registry.store.connection() as conn:
            row = conn.execute('SELECT last_ip,lease_id FROM robot_observations').fetchone()
            self.assertEqual(tuple(row), ('10.20.30.41', sid))
        self.assertTrue(self.control.device()['online'])
        self.assertFalse(self.control.config['enabled'])
        self.assertFalse(self.control.config['system_mix_consent'])
        self.assertFalse(self.control.config['local_route_confirmed'])

    def test_revoked_device_still_denied_with_listener(self):
        self.enroll_fixture()
        robot = self.registry.get_robot_by_wire_id(self.h['device_id'])
        self.registry.revoke_robot(robot['id'])
        self.control.config['approved'][self.h['device_id']] = crypto.fingerprint(self.pub)
        self.assertIsNone(self.control.receive(json.dumps(self.h).encode(), ('10.20.30.41',5678)))
        self.assertFalse(self.control.leases)

    def test_lifespan_starts_listener_with_legacy_disabled(self):
        module = importlib.import_module('src.api.app')
        db = MagicMock()
        db.get_connection.return_value.__enter__.return_value.cursor.return_value.fetchone.return_value = (257,)
        control = Mock()
        control.load.return_value = {'enabled':False}
        session, stream = Mock(), Mock()
        async def run():
            with patch.object(module, 'get_db', return_value=db), \
                 patch.object(module.settings, 'AUTO_SYNC_ENABLED', False), \
                 patch('src.media.device_control.get_control', return_value=control), \
                 patch('src.media.orchestration.get_session', return_value=session), \
                 patch('src.streaming.service.get_service', return_value=stream):
                async with module.lifespan(Mock()):
                    control.load.assert_called_once()
                    control.start.assert_called_once()
                    stream.start.assert_not_called()
                control.stop.assert_called_once()
        asyncio.run(run())


# Do not run the imported base class a second time via discovery.
del BaseControlTests
