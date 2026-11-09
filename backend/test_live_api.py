from pathlib import Path
import json
import struct
import tempfile
import time
import unittest
from unittest.mock import patch, AsyncMock
from types import SimpleNamespace
import asyncio

import database
from video_test_support import video_client


class LiveAPITests(unittest.TestCase):
    def test_peer_disconnect_during_final_close_is_not_server_error(self):
        from starlette.websockets import WebSocketDisconnect
        with tempfile.TemporaryDirectory() as root, patch.object(database,'DB_PATH',Path(root)/'db.sqlite'):
            with video_client(Path(root)/'recordings') as (main,client):
                socket=SimpleNamespace(headers={'origin':'http://localhost:5173'},
                    accept=AsyncMock(),receive=AsyncMock(return_value={'type':'websocket.disconnect'}),
                    close=AsyncMock(side_effect=WebSocketDisconnect(1006)))
                with patch.object(main,'current_user',return_value={'must_change_password':False}):
                    asyncio.run(main.live_frames(socket,'CAM-01'))
                socket.accept.assert_awaited_once()

    def test_binary_camera_pairing_origin_and_session(self):
        with tempfile.TemporaryDirectory() as root, patch.object(database,'DB_PATH',Path(root)/'db.sqlite'):
            with video_client(Path(root)/'recordings') as (main,client):
                user={'employee_id':'TEST','role':'admin','must_change_password':False}
                for camera_id,source in main.monitors().items():
                    source.latest=({'camera_id':camera_id,'recording_id':'a'*32,'frame_id':7,'timestamp':time.time()},camera_id.encode())
                with patch.object(main,'current_user',return_value=user):
                    with client.websocket_connect('/api/live/CAM-02',headers={'origin':'http://localhost:5173'}) as socket:
                        packet=socket.receive_bytes()
                        length=struct.unpack('!I',packet[:4])[0]
                        self.assertEqual(json.loads(packet[4:4+length])['camera_id'],'CAM-02')
                        self.assertEqual(packet[4+length:],b'CAM-02')
                    from starlette.websockets import WebSocketDisconnect
                    with self.assertRaises(WebSocketDisconnect):
                        with client.websocket_connect('/api/live/CAM-01',headers={'origin':'http://evil.invalid'}): pass
                from fastapi import HTTPException
                with patch.object(main,'current_user',side_effect=HTTPException(401)):
                    with self.assertRaises(WebSocketDisconnect):
                        with client.websocket_connect('/api/live/CAM-01',headers={'origin':'http://localhost:5173'}): pass
