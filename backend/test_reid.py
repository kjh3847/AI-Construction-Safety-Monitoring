"""Synthetic embeddings test matching rules only, never OSNet accuracy."""
import os
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import database
from reid import GlobalTracker, OSNetEncoder


class ReIDTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patch = patch.object(database,'DB_PATH',Path(self.temp.name)/'events.db')
        self.patch.start()
        database.init_db()
        self.tracker = GlobalTracker(encoder=SimpleNamespace(fingerprint='fixture-model'),transitions={
            'CAM-01>CAM-02':[3,30], 'CAM-02>CAM-03':[3,30]})
        self.now = time.time()

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def see(self,camera,local,vector,seconds,session='session',tracker=None):
        return (tracker or self.tracker).observe(camera,session,[{'track_id':local}],self.now+seconds,[vector])[str(local)]

    def test_local_identity_then_two_camera_transitions(self):
        first = self.see('CAM-01',1,[1,0],0)
        same = self.see('CAM-01',1,[1,0],1)
        second = self.see('CAM-02',7,[1,0],5)
        third = self.see('CAM-03',8,[1,0],10)
        self.assertEqual({x['global_person_id'] for x in (first,same,second,third)},{first['global_person_id']})
        self.assertEqual(second['match_state'],'estimated')
        self.assertEqual(len(self.tracker.history(first['global_person_id'])),3)

    def test_unknown_topology_never_links(self):
        first = self.see('CAM-01',1,[1,0],0)
        unknown = self.see('CAM-03',1,[1,0],5)
        self.assertNotEqual(first['global_person_id'],unknown['global_person_id'])

    def test_same_clothing_near_tie_is_unconfirmed(self):
        self.see('CAM-01',1,[1,.01],0)
        self.see('CAM-01',2,[1,-.01],0)
        result = self.see('CAM-02',3,[1,0],5)
        self.assertEqual(result['match_state'],'unconfirmed')
        self.assertEqual(result['reason'],'ambiguous_candidates')

    def test_simultaneous_impossible_and_low_similarity(self):
        first = self.see('CAM-01',1,[1,0],0)
        simultaneous = self.see('CAM-02',2,[1,0],.2)
        low = self.see('CAM-02',3,[0,1],5)
        self.assertNotEqual(first['global_person_id'],simultaneous['global_person_id'])
        self.assertNotEqual(first['global_person_id'],low['global_person_id'])
        self.assertEqual(low['match_state'],'unconfirmed')

    def test_one_identity_cannot_be_assigned_twice_in_batch(self):
        first = self.see('CAM-01',1,[1,0],0)
        result = self.tracker.observe('CAM-02','session',[{'track_id':2},{'track_id':3}],self.now+5,[[1,0],[1,0]])
        self.assertEqual(sum(r['global_person_id']==first['global_person_id'] for r in result.values()),1)

    def test_restart_model_change_and_reconnect(self):
        first = self.see('CAM-01',1,[1,0],0)
        restarted = GlobalTracker(encoder=SimpleNamespace(fingerprint='fixture-model'),transitions={'CAM-01>CAM-02':[3,30]})
        restarted.initialize()
        second = self.see('CAM-02',1,[1,0],5,tracker=restarted)
        self.assertEqual(first['global_person_id'],second['global_person_id'])
        restarted.encoder.fingerprint='different-model'
        third = self.see('CAM-01',1,[1,0],10,session='reconnect',tracker=restarted)
        self.assertNotEqual(second['global_person_id'],third['global_person_id'])
        self.assertNotEqual(first['tracklet_id'],third['tracklet_id'])

    def test_manual_split_updates_only_linked_events_and_audits(self):
        first = self.see('CAM-01',1,[1,0],0)
        second = self.see('CAM-02',2,[1,0],5)
        a = database.save_event('CAM-01','NO-Hardhat',global_person_id=first['global_person_id'],tracklet_id=first['tracklet_id'])
        b = database.save_event('CAM-02','NO-Hardhat',global_person_id=second['global_person_id'],tracklet_id=second['tracklet_id'])
        corrected = self.tracker.correct(second['tracklet_id'],None,'ADMIN','different worker')
        self.assertEqual(database.get_event(a)['global_person_id'],first['global_person_id'])
        self.assertEqual(database.get_event(b)['global_person_id'],corrected['global_person_id'])
        self.assertNotEqual(first['global_person_id'],corrected['global_person_id'])
        with database.get_connection() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM identity_corrections').fetchone()[0],1)

    def test_missing_model_and_invalid_embedding_fail_closed(self):
        encoder = OSNetEncoder(path=str(Path(self.temp.name)/'missing.onnx'))
        self.assertEqual(encoder.encode(None,[{}]),[None])
        self.assertEqual(encoder.state,'unavailable')
        first = self.see('CAM-01',1,[1,0],0)
        second = self.see('CAM-02',2,[float('nan'),0],5)
        self.assertNotEqual(first['global_person_id'],second['global_person_id'])

    def test_transition_reduces_new_alert_without_counting_unobserved_duration(self):
        from datetime import datetime, timezone
        from event_recorder import EventRecorder
        first=self.see('CAM-01','local',[1,0],0)
        second=self.see('CAM-02','local',[1,0],5)
        detections=[{'class_name':'Person','confidence':.95,'bbox':[0,0,100,200]},
                    {'class_name':'NO-Hardhat','confidence':.9,'bbox':[30,0,70,40]}]
        trackers=[]
        for camera,identity,seconds in [('CAM-01',first,0),('CAM-02',second,5)]:
            recorder=EventRecorder(camera,'model.pt','camera',camera_name=camera)
            track={'id':'local','recorded':False}
            stamp=datetime.fromtimestamp(self.now+seconds,timezone.utc).isoformat()
            recorder.record(detections,0,0,stamp,tracks={0:track},identities={'local':identity})
            trackers.append((recorder,track))
        rows=database.get_events()
        self.assertEqual(len(rows),2)
        self.assertEqual(rows[0]['notification_suppressed'],1)
        recorder,track=trackers[-1]
        recorder.record(detections,1,600,tracks={0:track},identities={'local':second})
        self.assertEqual(len(database.get_events()),2,'An unobserved ten-minute gap must not become a sustained warning')
