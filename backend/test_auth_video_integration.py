"""Separate account/video apps sharing a fake session DB; no RDS or camera I/O."""
from contextlib import contextmanager
import importlib
import os
from pathlib import Path
import sys
import tempfile
import time
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
import account_server
import database
import identity


class SessionDatabase:
    def __init__(self):
        self.user = dict(employee_id='LOCAL_TEST', email='test@example.com',
                         password_hash=identity.hasher.hash('LocalTest123!'),
                         role='admin', status='active', must_change_password=False,
                         failed_attempts=0, locked_until=None)
        self.sessions = set()
        self.row = None

    @contextmanager
    def connect(self):
        yield self

    def execute(self, sql, params=()):
        self.row = None
        if sql.startswith('SELECT * FROM accounts WHERE employee_id='):
            self.row = self.user if params[0] == self.user['employee_id'] else None
        elif 'JOIN account_sessions' in sql:
            self.row = self.user if params[0] in self.sessions else None
        elif sql.startswith('INSERT INTO account_sessions'):
            self.sessions.add(params[0])
        elif sql.startswith('DELETE FROM account_sessions WHERE token_hash='):
            self.sessions.discard(params[0])
        elif not (sql.startswith('UPDATE accounts SET failed_attempts=') or
                  sql.startswith('DELETE FROM account_sessions WHERE expires_at')):
            raise AssertionError('Unexpected database operation in isolated test')
        return self

    def fetchone(self):
        return self.row


class AuthVideoIntegrationTests(unittest.TestCase):
    def test_login_three_cameras_events_permissions_and_logout(self):
        fake_yolo = ModuleType('ultralytics')
        fake_yolo.YOLO = lambda path: SimpleNamespace(names={0: 'Person', 1: 'NO-Hardhat'})
        db = SessionDatabase()
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {
                'MONITOR_STORAGE_DIR': directory, 'CAMERA_SOURCE': '0',
                'PUBLIC_APP_URL': 'http://localhost:5173', 'COOKIE_SECURE': 'false',
            }), patch.dict(sys.modules, {'ultralytics': fake_yolo}), \
                    patch('identity.connect', db.connect), \
                    patch('account_server.init_identity'), \
                    patch.object(database, 'DB_PATH', Path(directory)/'events.db'):
                # Import real routing and Monitor/FrameStore; only YOLO and PostgreSQL are mocked.
                previous = sys.modules.pop('main', None)
                try:
                    video = importlib.import_module('main')
                    with patch.object(video, 'init_identity'), \
                            TestClient(account_server.app, base_url='http://localhost:5173') as accounts, \
                            TestClient(video.app, base_url='http://localhost:5173') as client:
                        accounts.headers['origin'] = client.headers['origin'] = 'http://localhost:5173'
                        self.assertEqual(client.get('/api/events').status_code, 401)
                        response = accounts.post('/api/auth/login', json={
                            'employee_id': db.user['employee_id'], 'password': 'LocalTest123!'})
                        self.assertEqual(response.status_code, 200)
                        self.assertIn('HttpOnly', response.headers['set-cookie'])
                        client.cookies.update(accounts.cookies)
                        self.assertEqual(set(video.monitors()), {'CAM-01', 'CAM-02', 'CAM-03'})
                        for number, (camera_id, source) in enumerate(video.monitors().items(), 1):
                            recording = str(number)*32
                            source.store.add(dict(recording_id=recording, frame_id=0,
                                                  timestamp=time.time(), camera_name=camera_id), b'jpeg')
                            event_id = database.save_event(camera_id, 'NO-Hardhat', event_key=camera_id)
                            database.attach_recording(camera_id, recording, 0, None)
                            self.assertEqual(client.get('/api/status', params={'camera_id': camera_id}).status_code, 200)
                            frame = client.get('/api/recordings/frame', params={'camera_id': camera_id})
                            self.assertEqual(frame.status_code, 200)
                            self.assertEqual(frame.json()['camera_name'], camera_id)
                            self.assertTrue(client.get(f'/api/events/{event_id}').json()['playable'])
                        self.assertEqual(len(client.get('/api/events').json()['events']), 3)
                        for app in (accounts, client):
                            self.assertEqual(app.get('/api/admin/accounts').status_code, 403)
                            self.assertEqual(app.post('/api/admin/accounts', json={
                                'employee_id': 'DENIED', 'email': 'denied@example.com'}).status_code, 403)
                        self.assertEqual(client.post('/api/monitor/start',
                            headers={'origin': 'http://evil.example'}).status_code, 403)
                        self.assertEqual(accounts.post('/api/auth/logout').status_code, 200)
                        # Keep the old cookie on the video client: shared-session revocation must deny it.
                        for path in ('/api/events', '/api/status', '/api/recordings/frame', '/video'):
                            self.assertEqual(client.get(path).status_code, 401)
                finally:
                    sys.modules.pop('main', None)
                    if previous is not None:
                        sys.modules['main'] = previous


if __name__ == '__main__':
    unittest.main()
