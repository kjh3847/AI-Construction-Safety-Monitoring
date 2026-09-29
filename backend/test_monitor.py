"""Real YOLO/video integration, storing all test output in a temporary directory."""
import tempfile
from pathlib import Path
import time
import unittest

import cv2
import numpy as np
from ultralytics import YOLO
import database
from monitor import Monitor
from person_safety import associate_people


class RealMonitorTest(unittest.TestCase):
    def test_independent_detection_recording_and_evidence(self):
        base = Path(__file__).resolve().parent
        original = database.DB_PATH
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database.DB_PATH = root/'test.db'
            monitor = None
            try:
                database.init_db()
                monitor = Monitor(YOLO(str(base/'best.pt')),base/'best.pt',base/'test.mp4',root/'recordings')
                self.assertEqual(monitor.source_kind,'test', 'Run this test without CAMERA_SOURCE')
                monitor.initialize(300)
                monitor.start()
                deadline = time.monotonic()+120
                first = None
                while time.monotonic()<deadline:
                    if monitor.state == 'error':
                        self.fail(monitor.error)
                    latest = monitor.store.get()
                    if latest and first is None:
                        first = latest
                    if first and latest[0]['frame_id'] >= 210:
                        break
                    time.sleep(.1)
                self.assertIsNotNone(first)
                self.assertGreaterEqual(database.event_summary()['total'],1)
                latest = monitor.store.get()
                self.assertGreaterEqual(latest[0]['frame_id'],210)
                self.assertGreater(latest[0]['frame_id'],first[0]['frame_id'])
                # No viewer or streaming request has been created. A paused
                # client's immutable frame still matches after worker progress.
                self.assertEqual(monitor.store.get(recording_id=first[0]['recording_id'],frame_id=first[0]['frame_id']),first)
                rows = database.get_events()
                self.assertEqual(len({row['person_track_id'] for row in rows}),len(rows),
                                 'Each tracked person must only produce one event')
                deadline = time.monotonic()+5
                while not all(row['snapshot_path'] for row in rows) and time.monotonic()<deadline:
                    time.sleep(.1)
                    rows = database.get_events()
                for row in rows:
                    meta,jpeg = monitor.store.get(recording_id=row['recording_id'],frame_id=row['frame_id'])
                    self.assertEqual((monitor.snapshots/row['snapshot_path']).read_bytes(),jpeg)
                    self.assertIsNotNone(cv2.imdecode(np.frombuffer(jpeg,dtype=np.uint8),cv2.IMREAD_COLOR))
                    self.assertEqual(meta['person_count'],sum(d['class_name']=='Person' for d in meta['detections']))
                    self.assertEqual(meta['noncompliant_person_count'],associate_people(meta['detections'])['noncompliant_person_count'])
                    self.assertLessEqual(meta['noncompliant_person_count'],meta['person_count'])
                    self.assertTrue(any(d['class_name']==row['event_type'] and d['confidence']==row['confidence'] for d in meta['detections']))
                    self.assertEqual(row['review_status'],'pending')
                    self.assertEqual(row['person_count'],meta['person_count'])
                    self.assertEqual(row['noncompliant_person_count'],meta['noncompliant_person_count'])
                    self.assertIsNotNone(row['detected_at'])
                print('Real model classes:',monitor.model.names)
                print('Frames progressed:',first[0]['frame_id'],'->',latest[0]['frame_id'],'New real events:',len(rows))
            finally:
                if monitor:
                    monitor.shutdown()
                database.DB_PATH = original


if __name__ == '__main__':
    unittest.main()
