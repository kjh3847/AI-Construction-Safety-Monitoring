"""Three independent camera stores, events, and controls; no hardware required."""
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import database
from video_test_support import video_client


class SourceTest(unittest.TestCase):
    def test_sources_route_frames_events_and_controls_independently(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(database,'DB_PATH',root/'test.db'), video_client(root/'recordings') as (main,client):
                now = time.time()
                for number,(camera_id,source) in enumerate(main.monitors().items(),1):
                    recording = str(number)*32
                    source.store.add(dict(recording_id=recording,frame_id=0,timestamp=now,
                        camera_id=camera_id,camera_name=camera_id),f'jpeg{number}'.encode())
                    event_id = database.save_event(camera_id,'NO-Hardhat',event_key=camera_id)
                    database.attach_recording(camera_id,recording,0,f'{number}.jpg')
                    (source.snapshots/f'{number}.jpg').write_bytes(f'snapshot{number}'.encode())
                    frame = client.get('/api/recordings/frame',params={'camera_id':camera_id}).json()
                    self.assertEqual(frame['camera_id'],camera_id)
                    self.assertEqual(client.get(f'/api/events/{event_id}/snapshot').content,f'snapshot{number}'.encode())
                    self.assertTrue(client.get(f'/api/events/{event_id}').json()['playable'])
                self.assertEqual(client.get('/api/recordings/frame',params={
                    'camera_id':'CAM-02','recording_id':'1'*32,'frame_id':0}).status_code,410)
                rows = client.get('/api/events?camera_id=CAM-02').json()['events']
                self.assertEqual([row['camera_id'] for row in rows],['CAM-02'])
                with patch.object(main.monitor,'start') as first, patch.object(main.monitor2,'start') as second:
                    client.post('/api/monitor/start?camera_id=CAM-02')
                    first.assert_not_called()
                    second.assert_called_once()
                with patch.object(main.monitor,'start') as first, patch.object(main.monitor2,'start') as second, patch.object(main.monitor3,'start') as third:
                    client.post('/api/monitor/start?camera_id=all')
                    for call in (first,second,third): call.assert_called_once()
                client.patch('/api/settings',json={'retention_seconds':120})
                self.assertEqual([source.store.retention for source in main.monitors().values()],[120]*3)
                self.assertEqual(client.get('/api/status?camera_id=unknown').status_code,404)
                renamed=database.save_event('old display name','NO-Hardhat',camera_id='CAM-03')
                self.assertEqual(client.get(f'/api/events/{renamed}').json()['camera_id'],'CAM-03')
                filtered=client.get('/api/events?camera_id=CAM-03').json()['events']
                self.assertIn(renamed,[row['id'] for row in filtered])
