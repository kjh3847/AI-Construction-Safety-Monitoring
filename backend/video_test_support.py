"""Video API regression fixture: fake YOLO, explicit user, no PostgreSQL access."""
from contextlib import contextmanager
import importlib
import os
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from identity import monitor_user


@contextmanager
def video_client(storage):
    fake = ModuleType('ultralytics')
    fake.YOLO = lambda path: SimpleNamespace(names={0: 'Person', 1: 'NO-Hardhat'})
    previous = sys.modules.pop('main', None)
    with patch.dict(os.environ, {'MONITOR_STORAGE_DIR': str(storage),
                                'PUBLIC_APP_URL': 'http://localhost:5173', 'CAMERA_SOURCE': '0'}), \
            patch.dict(sys.modules, {'ultralytics': fake}):
        try:
            main = importlib.import_module('main')
            main.app.dependency_overrides[monitor_user] = lambda: {
                'employee_id': 'VIDEO_TEST', 'role': 'admin', 'must_change_password': False}
            with patch.object(main, 'init_identity'), \
                    patch('identity.connect', side_effect=AssertionError('Unexpected PostgreSQL access')), \
                    TestClient(main.app) as client:
                client.headers['origin'] = 'http://localhost:5173'
                yield main, client
        finally:
            sys.modules.pop('main', None)
            if previous is not None:
                sys.modules['main'] = previous
