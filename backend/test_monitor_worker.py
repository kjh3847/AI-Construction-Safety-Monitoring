"""Real decoder/BoT-SORT/DB/DVR using explicit synthetic detector outputs."""
import importlib.util
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import cv2
import numpy as np
import database
from monitor import Monitor
from reid import GlobalTracker


@unittest.skipUnless(importlib.util.find_spec('ultralytics'),'Ultralytics dependency required')
class WorkerTests(unittest.TestCase):
    def test_text_metadata_raw_pixels_and_exact_event_evidence(self):
        import torch
        from ultralytics.engine.results import Results
        class FixtureEngine:
            def predict(self,frame):
                boxes=torch.tensor([[10,10,100,200,.95,0],[30,10,70,45,.9,1]])
                result=Results(frame,'synthetic',names={0:'Person',1:'NO-Hardhat'},boxes=boxes)
                return result,0,1
        with tempfile.TemporaryDirectory() as directory, patch.dict('os.environ',{'CAMERA_SOURCE':''}):
            root=Path(directory)
            with patch.object(database,'DB_PATH',root/'db.sqlite'):
                database.init_db()
                path=root/'synthetic.avi'
                writer=cv2.VideoWriter(str(path),cv2.VideoWriter_fourcc(*'MJPG'),10,(320,240))
                image=np.full((240,320,3),70,np.uint8)
                for _ in range(8): writer.write(image)
                writer.release()
                (root/'model.pt').write_bytes(b'test-only-no-real-weights')
                tracker=GlobalTracker(transitions={})
                source=Monitor(None,root/'model.pt',path,root/'recordings',engine=FixtureEngine(),global_tracker=tracker)
                source.initialize(120);source.start()
                try:
                    source.thread.join(timeout=15)
                    self.assertFalse(source.thread.is_alive())
                    self.assertEqual(source.state,'finished',source.error)
                    meta,jpeg=source.latest_frame()
                    self.assertEqual(meta['annotation_mode'],'text-metadata')
                    self.assertEqual(meta['noncompliant_person_count'],1)
                    decoded=cv2.imdecode(np.frombuffer(jpeg,np.uint8),cv2.IMREAD_COLOR)
                    self.assertLess(float(decoded.std()),1,'No detection boxes or labels baked into pixels')
                    rows=database.get_events()
                    self.assertEqual(len(rows),1)
                    event=rows[0]
                    saved=source.store.get(recording_id=event['recording_id'],frame_id=event['frame_id'])
                    self.assertIsNotNone(saved)
                    self.assertEqual((source.snapshots/event['snapshot_path']).read_bytes(),saved[1])
                    self.assertEqual(event['global_person_id'],saved[0]['person_safety'][0]['global_person_id'])
                    source.start();source.thread.join(timeout=15)
                    self.assertEqual(len(database.get_events()),1,'Replay deduplication must survive a new recording session')
                    repeated=database.get_events()[0]
                    replay=source.store.get(recording_id=repeated['recording_id'],frame_id=repeated['frame_id'])
                    self.assertEqual(repeated['global_person_id'],replay[0]['person_safety'][0]['global_person_id'])
                finally:
                    source.shutdown()
