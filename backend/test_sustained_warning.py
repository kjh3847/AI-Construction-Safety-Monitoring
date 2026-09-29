"""Time-driven detector tests; synthetic events only go into a temporary DB."""
import unittest
import test_person_dedup as fixtures
from test_person_dedup import person
from event_recorder import EventRecorder
import database


class SustainedWarningTest(unittest.TestCase):
    setUp = fixtures.PersonDedupTest.setUp
    tearDown = fixtures.PersonDedupTest.tearDown

    def run_until(self, start, end, recorder=None):
        recorder = recorder or self.recorder
        for second in range(start, end+1):
            recorder.record(person(),second,second,'2026-09-22T01:00:00.000Z')

    def test_boundary_and_twenty_minutes_with_replay(self):
        self.run_until(0,599)
        self.assertEqual(database.event_summary()['total'],1)
        self.run_until(600,600)
        warning = database.get_events()[0]
        self.assertEqual(warning['event_reason'],'sustained')
        self.assertEqual(warning['sustained_seconds'],600)
        self.assertEqual(warning['repeat_index'],1)
        self.assertEqual(warning['event_person_count'],1)
        self.assertEqual(warning['review_status'],'pending')
        database.review_event(warning['id'])
        self.run_until(601,1199)
        self.assertEqual(database.event_summary()['total'],2)
        self.run_until(1200,1200)
        self.assertEqual(database.event_summary()['total'],3)
        self.assertEqual(database.get_events()[0]['repeat_index'],2)
        replay = EventRecorder('hash','best.pt','test.mp4')
        self.run_until(0,1200,replay)
        self.assertEqual(database.event_summary()['total'],3)
        self.assertEqual(database.get_event(warning['id'])['review_status'],'reviewed')

    def test_missing_evidence_resets_continuity_without_new_initial_capture(self):
        self.run_until(0,599)
        for second in range(600,604):
            self.recorder.record(person(bad=False),second,second)
        self.run_until(604,1203)
        self.assertEqual(database.event_summary()['total'],1)
        self.run_until(1204,1204)
        self.assertEqual(database.event_summary()['total'],2)
        self.assertEqual(database.get_events()[0]['sustained_seconds'],600)

    def test_brief_dropout_and_next_frame_do_not_duplicate(self):
        self.run_until(0,598)
        self.recorder.record([],599,599)
        self.run_until(600,601)
        self.assertEqual(database.event_summary()['total'],2)
        self.assertEqual(self.recorder.episode_keys,[])

    def test_other_person_does_not_inherit_duration(self):
        self.run_until(0,599)
        self.recorder.record(person(300),600,600)
        rows = database.get_events()
        self.assertEqual(len(rows),2)
        self.assertTrue(all(row['event_reason']=='initial' for row in rows))

    def test_warning_api_payload_and_review_persist(self):
        from fastapi.testclient import TestClient
        from unittest.mock import patch
        from main import app
        self.run_until(0,600)
        warning = database.get_events()[0]
        with patch('main.monitors', return_value={}), TestClient(app) as client:
            data = client.get(f"/api/events/{warning['id']}").json()
            self.assertEqual(data['event_reason'],'sustained')
            self.assertEqual(data['sustained_seconds'],600)
            self.assertEqual(data['violation_types'],['NO-Hardhat'])
            client.patch(f"/api/events/{warning['id']}")
            self.assertEqual(client.get(f"/api/events/{warning['id']}").json()['review_status'],'reviewed')


if __name__ == '__main__':
    unittest.main()
