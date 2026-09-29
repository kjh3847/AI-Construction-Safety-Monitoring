"""Isolated DB tests: never insert synthetic detections into safety.db."""
import tempfile
import unittest
import os
from pathlib import Path

import database
from event_recorder import EventRecorder


class PipelineTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original = database.DB_PATH
        database.DB_PATH = Path(self.temp.name) / 'test.db'
        # Reproduce the original schema and preserve a pre-existing row.
        with database.get_connection() as conn:
            conn.execute("""CREATE TABLE safety_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, camera_name TEXT NOT NULL,
                event_type TEXT NOT NULL, model_name TEXT, confidence REAL,
                snapshot_path TEXT, review_status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')))
            """)
            conn.execute("INSERT INTO safety_events(camera_name,event_type) VALUES ('OLD','LEGACY')")
        database.init_db()
        database.init_db()

    def tearDown(self):
        database.DB_PATH = self.original
        self.temp.cleanup()

    def test_episodes_replay_and_review(self):
        recorder = EventRecorder('video-model-hash', 'best.pt', 'test.mp4')
        bad = [{'class_name': 'Person', 'confidence': .9, 'bbox': [0,0,100,200]},
               {'class_name': 'NO-Hardhat', 'confidence': .85, 'bbox': [30,0,70,40]}]
        good = [{'class_name': 'Hardhat', 'confidence': .95}]
        self.assertEqual(recorder.record(good, 0, 0), [])
        self.assertEqual(len(recorder.record(bad, 1, .1)), 1)
        self.assertEqual(recorder.record(bad, 2, .2), [])
        self.assertEqual(recorder.record(bad, 20, 2.0), [])
        self.assertEqual(recorder.record(bad, 41, 4.1), [])
        replay = EventRecorder('video-model-hash', 'best.pt', 'test.mp4')
        self.assertEqual(replay.record(bad, 1, .1), [])
        self.assertEqual(database.event_summary(), {'total': 2, 'pending': 2})
        rows = database.get_events()
        self.assertTrue(any(row['event_type'] == 'LEGACY' for row in rows))
        self.assertEqual(database.review_event(rows[0]['id'])['review_status'], 'reviewed')
        self.assertEqual(database.event_summary()['pending'], 1)
        self.assertIsNone(database.review_event(99999))

    def test_api(self):
        from fastapi.testclient import TestClient
        from unittest.mock import patch
        with patch.dict(os.environ, {'MONITOR_STORAGE_DIR': str(Path(self.temp.name)/'recordings')}):
            from main import app
        with TestClient(app) as client:
            response = client.get('/api/events', headers={'Origin': 'http://127.0.0.1:5173'})
            self.assertEqual(response.headers['access-control-allow-origin'], 'http://127.0.0.1:5173')
            self.assertEqual(response.json()['summary']['total'], 1)
            self.assertEqual(client.patch('/api/events/1').json()['review_status'], 'reviewed')
            self.assertEqual(client.patch('/api/events/999').status_code, 404)
            self.assertEqual(client.get('/api/events?limit=-1').status_code, 422)
            self.assertEqual(client.get('/api/events?offset=1').json()['events'], [])
            self.assertIn('NO-Hardhat', client.get('/api/status').json()['classes'].values())


if __name__ == '__main__':
    unittest.main()
