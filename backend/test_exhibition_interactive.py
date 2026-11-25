"""Coverage for QR, visitor leases, and private-S3 video cache routing."""
import importlib
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch

import cv2
import httpx
import numpy as np
from fastapi.testclient import TestClient

import database


def create_clip(path, shade):
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'mp4v'), 10, (64, 48))
    if not writer.isOpened():
        raise RuntimeError('MP4 encoder unavailable')
    try:
        for _ in range(22):
            writer.write(np.full((48, 64, 3), shade, dtype=np.uint8))
    finally:
        writer.release()


class InteractiveExhibitionTest(unittest.TestCase):
    def test_qr_publish_lifecycle_and_s3_playback(self):
        origin = 'https://exhibition.example'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            videos = root / 'videos'
            videos.mkdir()
            env = {
                'EXHIBITION_ENABLED': 'true', 'EXHIBITION_INTERACTIVE': 'true',
                'EXHIBITION_OPERATOR_KEY': '', 'PUBLIC_APP_URL': origin,
                'EXHIBITION_VIDEO_DIR': str(videos), 'MONITOR_STORAGE_DIR': str(root / 'recordings'),
                'MEDIA_ENABLED': 'true', 'MEDIA_AI_PASSWORD': 'test', 'MEDIA_WEB_PASSWORD': 'test',
                'LOCAL_DEMO_ENABLED': 'false', 'MONITOR_AUTOSTART': 'true', 'ANALYSIS_FPS': '5',
            }
            previous = sys.modules.pop('main', None)
            try:
                with patch.dict(os.environ, env), patch.object(database, 'DB_PATH', root / 'events.db'):
                    main = importlib.import_module('main')
                    relay = main.media_gateway
                    relay.available = True
                    upstream = []
                    def media_response(request):
                        upstream.append((request.method, request.url.path))
                        if request.method == 'POST':
                            return httpx.Response(201, content=b'answer',
                                                  headers={'Location': '/cam01/whip/fixture'})
                        return httpx.Response(204)

                    async_client = httpx.AsyncClient
                    with (
                        patch.object(relay, 'start', AsyncMock()),
                        patch('exhibition_relay.httpx.AsyncClient', side_effect=lambda **kwargs:
                            async_client(transport=httpx.MockTransport(media_response), **kwargs)),
                        patch.object(main.engine, 'predict', return_value=(None, 0, 0)),
                        patch('monitor.LocalBoTSORT.detections', return_value=[]),
                        TestClient(main.app) as client,
                    ):
                        self.assertTrue(client.get('/api/runtime').json()['interactive'])
                        statuses = client.get('/api/cameras').json()['cameras']
                        self.assertEqual([cam['camera_id'] for cam in statuses], [f'CAM-{i:02}' for i in range(1, 6)])
                        self.assertEqual([cam['camera_name'] for cam in statuses[-2:]],
                                         ['건설장비 착용', '건설장비 미착용'])
                        self.assertTrue(all(source.ephemeral and source.thread is None for source in main.live_monitors.values()))
                        for i in range(1, 4):
                            camera = f'CAM-{i:02}'
                            data = client.get('/api/exhibition/qr/' + camera).content
                            image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
                            qr, _, _ = cv2.QRCodeDetector().detectAndDecode(image)
                            self.assertEqual(qr, origin + '/exhibition/join/' + camera)

                        publish = '/api/exhibition/publish/CAM-01'
                        offer = {'content-type': 'application/sdp', 'origin': origin}
                        self.assertEqual(client.post(publish, headers={**offer, 'origin': 'https://other.example'},
                                                     content=b'offer').status_code, 403)
                        result = client.post(publish, headers=offer, content=b'offer')
                        self.assertEqual((result.status_code, result.content), (201, b'answer'))
                        lease = result.headers['location']
                        self.assertTrue(client.get('/api/status?camera_id=CAM-01').json()['relay']['reserved'])
                        self.assertEqual(client.post(publish, headers=offer, content=b'offer').status_code, 409)
                        self.assertEqual(client.post(lease, headers=offer).status_code, 204)
                        self.assertEqual(client.delete(lease, headers=offer).status_code, 204)
                        self.assertFalse(client.get('/api/status?camera_id=CAM-01').json()['relay']['reserved'])
                        self.assertEqual(upstream, [('POST', '/cam01/whip'), ('DELETE', '/cam01/whip/fixture')])

                        headers = {'origin': origin}
                        for other_camera in ('CAM-01', 'all'):
                            self.assertEqual(client.post('/api/monitor/start?camera_id=' + other_camera,
                                                         headers=headers).status_code, 403)
                        self.assertEqual(client.patch('/api/settings', json={'retention_seconds': 60},
                                                      headers=headers).status_code, 403)
                        for camera, filename, shade in (('CAM-04', '착용.mp4', 35), ('CAM-05', '미착용.mp4', 195)):
                            video_url = '/api/exhibition/video/' + camera
                            self.assertEqual(client.get(video_url).status_code, 404)
                            create_clip(videos / filename, shade)
                            self.assertTrue(client.get('/api/status?camera_id=' + camera).json()['configured'])
                            self.assertEqual(client.get(video_url, headers={'Range': 'bytes=0-19'}).status_code, 206)
                            start_url = '/api/monitor/start?camera_id=' + camera
                            self.assertEqual(client.post(start_url).status_code, 403)
                            self.assertEqual(client.post(start_url, headers={'origin': 'https://other.example'}).status_code, 403)
                            response = client.post(start_url, headers=headers)
                            self.assertEqual(response.status_code, 200)
                            with client.websocket_connect('/api/metadata/' + camera, headers={'origin': origin}) as socket:
                                metadata = socket.receive_json()
                                self.assertEqual(metadata['camera_id'], camera)
                                self.assertEqual(metadata['source_name'], filename)
                        deadline = time.monotonic() + 5
                        while time.monotonic() < deadline and not all(
                                source.latest_frame() and source.latest_frame()[0]['frame_id'] >= 22
                                for source in main.s3_monitors.values()):
                            time.sleep(.06)
                        for source in main.s3_monitors.values():
                            self.assertEqual(source.status()['state'], 'running')
                            self.assertGreaterEqual(source.latest_frame()[0]['frame_id'], 22)
                            stopped = client.post('/api/monitor/stop?camera_id=' + source.camera_id, headers=headers)
                            self.assertEqual(stopped.status_code, 200)
                            source.thread.join(timeout=2)
                            self.assertEqual(source.status()['state'], 'stopped')
                        self.assertEqual(client.get('/api/recordings/frame?camera_id=CAM-01').status_code, 410)
            finally:
                sys.modules.pop('main', None)
                if previous is not None:
                    sys.modules['main'] = previous
