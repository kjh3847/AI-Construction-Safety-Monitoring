"""Exhibition viewer, operator, and independent looping channels."""
import importlib
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

import cv2
import numpy as np
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import database


class ExhibitionTest(unittest.TestCase):
    def test_public_view_operator_updates_and_looping_uploads(self):
        key = 'test-only-' + '4' * 32
        operator = {'x-exhibition-key': key, 'content-type': 'application/octet-stream'}
        origin = 'http://localhost:5173'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env = {'EXHIBITION_ENABLED': 'true', 'EXHIBITION_OPERATOR_KEY': key,
                   'LOCAL_DEMO_ENABLED': 'false', 'MONITOR_STORAGE_DIR': str(root / 'recordings'),
                   'MONITOR_AUTOSTART': 'true', 'CAMERA_SOURCE': '', 'MEDIA_ENABLED': 'false',
                   'PUBLIC_APP_URL': origin, 'ANALYSIS_FPS': '5'}
            env.update({f'CAMERA_{number:02}_SOURCE': '' for number in range(1, 4)})
            previous = sys.modules.pop('main', None)
            try:
                with patch.dict(os.environ, env), patch.object(database, 'DB_PATH', root / 'events.db'):
                    main = importlib.import_module('main')
                    with (
                        patch.object(main, 'init_identity', side_effect=AssertionError('unexpected account DB')),
                        patch.object(main.engine, 'predict', return_value=(None, 0, 0)),
                        patch('monitor.LocalBoTSORT.detections', return_value=[]),
                        TestClient(main.app) as client,
                    ):
                        self.assertTrue(client.get('/api/runtime').json()['exhibition'])
                        self.assertEqual(client.get('/api/auth/me').status_code, 404)
                        self.assertEqual(client.get('/api/events').status_code, 200)
                        cameras = client.get('/api/cameras').json()['cameras']
                        self.assertEqual([camera['camera_id'] for camera in cameras], [f'CAM-{i:02}' for i in range(1, 6)])
                        self.assertEqual(client.post('/api/monitor/stop').status_code, 403)
                        self.assertEqual(client.patch('/api/settings', json={'retention_seconds': 120}).status_code, 403)
                        endpoint = '/api/cameras/CAM-01/source'
                        address = {'url': 'rtsp://camera.example:8554/channel'}
                        self.assertEqual(client.post(endpoint, json=address).status_code, 403)
                        self.assertEqual(client.post(endpoint, json={'url': 'file:///etc/passwd'},
                                                     headers={'x-exhibition-key': key}).status_code, 422)
                        with patch.object(main.monitor, 'start') as start:
                            result = client.post(endpoint, json=address, headers={'x-exhibition-key': key})
                            self.assertEqual(result.status_code, 200)
                            start.assert_called_once()
                        self.assertNotIn(address['url'], result.text)
                        self.assertTrue(main.monitor.source_config.is_file())

                        for channel, shade in (('CAM-04', 0), ('CAM-05', 180)):
                            path = root / (channel + '.mp4')
                            writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'mp4v'), 5, (64, 48))
                            self.assertTrue(writer.isOpened())
                            try:
                                for _ in range(4):
                                    writer.write(np.full((48, 64, 3), shade, dtype=np.uint8))
                            finally:
                                writer.release()
                            content = path.read_bytes()
                            params = {'upload_id': str(uuid4()), 'offset': 0, 'total': len(content)}
                            endpoint = f'/api/cameras/{channel}/upload'
                            self.assertEqual(client.post(endpoint, params=params, content=content).status_code, 403)
                            self.assertTrue(client.post(endpoint, params=params, headers=operator, content=content).json()['ready'])

                        deadline = time.monotonic() + 5
                        sources = list(main.test_monitors.values())
                        while time.monotonic() < deadline:
                            if all(source.latest_frame() and source.latest_frame()[0]['frame_id'] >= 5 for source in sources):
                                break
                            time.sleep(.05)
                        for source in sources:
                            self.assertEqual(source.status()['state'], 'running')
                            self.assertGreaterEqual(source.latest_frame()[0]['frame_id'], 5)
                            self.assertLess(source.latest_frame()[0]['video_seconds'], .8)
                        self.assertNotEqual(sources[0].latest_frame()[1], sources[1].latest_frame()[1])
                        with client.websocket_connect('/api/live/CAM-05', headers={'origin': origin}) as socket:
                            self.assertIn(b'CAM-05', socket.receive_bytes())
                        with self.assertRaises(WebSocketDisconnect):
                            with client.websocket_connect('/api/live/CAM-05', headers={'origin': 'https://other.example'}):
                                pass

                    sys.modules.pop('main', None)
                    restored = importlib.import_module('main')
                    self.assertEqual(restored.monitor.source, address['url'])
                    self.assertTrue(all(source.upload_path.is_file() and source.source for source in restored.test_monitors.values()))
            finally:
                sys.modules.pop('main', None)
                if previous is not None:
                    sys.modules['main'] = previous
