import tempfile
from pathlib import Path
import unittest
import json

import database
from event_recorder import EventRecorder


class EventFactsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original = database.DB_PATH
        database.DB_PATH = Path(self.temp.name)/'test.db'
        database.init_db()

    def tearDown(self):
        database.DB_PATH = self.original
        self.temp.cleanup()

    def detections(self):
        return [{'class_name':name,'bbox':bbox,'confidence':.9} for name,bbox in [
            ('Person',[0,0,100,200]), ('Person',[200,0,300,200]),
            ('NO-Hardhat',[30,0,70,40]), ('NO-Safety Vest',[20,60,80,150]),
            ('NO-Safety Vest',[220,60,280,150])]]

    def test_counts_are_class_specific_and_persist_after_replay(self):
        recorder = EventRecorder('hash','best.pt','test.mp4')
        recorder.record(self.detections(),107,3.57,'2026-09-22T01:02:03.456Z')
        rows = {row['event_type']:row for row in database.get_events()}
        self.assertEqual(rows['NO-Hardhat']['event_person_count'],1)
        self.assertEqual(rows['NO-Safety Vest']['event_person_count'],1)
        self.assertEqual(json.loads(rows['NO-Hardhat']['violation_types']), ['NO-Hardhat','NO-Safety Vest'])
        self.assertEqual(len(database.get_events(event_type='NO-Safety Vest')),2)
        for row in rows.values():
            self.assertEqual(row['person_count'],2)
            self.assertEqual(row['noncompliant_person_count'],2)
            self.assertEqual(row['detected_at'],'2026-09-22T01:02:03.456Z')
            self.assertEqual(row['video_seconds'],3.57)
        event_id = rows['NO-Hardhat']['id']
        database.review_event(event_id)
        EventRecorder('hash','best.pt','test.mp4').record(self.detections(),107,3.57,'2026-09-23T01:02:03.456Z')
        self.assertEqual(database.event_summary()['total'],2)
        again = database.get_event(event_id)
        self.assertEqual(again['detected_at'],'2026-09-22T01:02:03.456Z')
        self.assertEqual(again['review_status'],'reviewed')
        self.assertEqual(again['event_person_count'],1)

    def test_legacy_missing_is_not_zero_and_backfill_preserves_time(self):
        event_id=database.save_event('CAM-01','NO-Hardhat',event_key='hash:CAM-01:NO-Hardhat:107')
        before=database.get_event(event_id)
        self.assertIsNone(before['event_person_count'])
        database.init_db()
        from person_safety import event_counts
        database.fill_event_counts(before['event_key'], event_counts(self.detections(),'NO-Hardhat'))
        after=database.get_event(event_id)
        self.assertEqual(after['event_person_count'],1)
        self.assertEqual(after['created_at'],before['created_at'])
        self.assertIsNone(after['detected_at'])


if __name__ == '__main__':
    unittest.main()
