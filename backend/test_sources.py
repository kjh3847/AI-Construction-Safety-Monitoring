import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import database
from monitor import Monitor


class SourceTest(unittest.TestCase):
    def test_sources_route_frames_events_and_controls_independently(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original_db = database.DB_PATH
            database.DB_PATH = root/'test.db'
            with patch.dict(os.environ, {'MONITOR_STORAGE_DIR':str(root/'initial')}):
                import main
            originals = main.monitor, main.monitor2
            main.monitor = Monitor(main.model,main.MODEL_PATH,main.VIDEO_PATH,root/'one',camera_name='CAM-01',use_camera_env=False)
            main.monitor2 = Monitor(main.model,main.MODEL_PATH,main.BASE_DIR/'test2.mp4',root/'two',camera_name='CAM-02',use_camera_env=False)
            try:
                from fastapi.testclient import TestClient
                with TestClient(main.app) as client:
                    now=time.time()
                    for number,source in [(1,main.monitor),(2,main.monitor2)]:
                        recording=str(number)*32
                        source.store.add({'recording_id':recording,'frame_id':0,'timestamp':now,
                            'camera_name':f'CAM-0{number}','source_name':source.source_name},f'jpeg{number}'.encode())
                        event_id=database.save_event(f'CAM-0{number}','NO-Hardhat',event_key=f'key{number}')
                        database.attach_recording(f'key{number}',recording,0,f'{number}.jpg')
                        (source.snapshots/f'{number}.jpg').write_bytes(f'snapshot{number}'.encode())
                        data=client.get('/api/recordings/frame',params={'camera_id':f'CAM-0{number}'}).json()
                        self.assertEqual(data['source_name'],'test.mp4' if number==1 else 'test2.mp4')
                        self.assertEqual(data['camera_name'],f'CAM-0{number}')
                        self.assertEqual(client.get(f'/api/events/{event_id}/snapshot').content,f'snapshot{number}'.encode())
                        self.assertTrue(client.get(f'/api/events/{event_id}').json()['playable'])
                    self.assertEqual(client.get('/api/status?camera_id=CAM-02').json()['source_name'],'test2.mp4')
                    self.assertEqual(client.get('/api/recordings/frame',params={'camera_id':'CAM-02','recording_id':'1'*32,'frame_id':0}).status_code,410)
                    rows=client.get('/api/events?camera_id=CAM-02').json()['events']
                    self.assertEqual(len(rows),1)
                    self.assertEqual(rows[0]['camera_id'],'CAM-02')
                    self.assertEqual(len(client.get('/api/events').json()['events']),2)
                    with patch.object(main.monitor,'start') as first, patch.object(main.monitor2,'start') as second:
                        self.assertEqual(client.post('/api/monitor/start?camera_id=CAM-02').status_code,200)
                        first.assert_not_called()
                        second.assert_called_once()
                    with patch.object(main.monitor,'stop') as first, patch.object(main.monitor2,'stop') as second:
                        client.post('/api/monitor/stop?camera_id=CAM-02')
                        first.assert_not_called()
                        second.assert_called_once()
                    client.patch('/api/settings',json={'retention_seconds':120})
                    self.assertEqual(main.monitor.store.retention,120)
                    self.assertEqual(main.monitor2.store.retention,120)
                    self.assertEqual(client.get('/api/status?camera_id=CAM-03').status_code,404)
            finally:
                main.monitor, main.monitor2 = originals
                database.DB_PATH = original_db


if __name__ == '__main__':
    unittest.main()
