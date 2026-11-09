"""Bounded DVR and filtered DB regression tests (isolated temporary files)."""
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from datetime import date

import database
from monitor import FrameStore, Monitor, frame_payload


class RecordingTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.original_db = database.DB_PATH
        database.DB_PATH = self.root / 'test.db'
        database.init_db()

    def tearDown(self):
        database.DB_PATH = self.original_db
        self.temp.cleanup()

    def test_seek_exact_frame_and_metadata(self):
        store = FrameStore(self.root / 'frames')
        now = time.time()
        for i in range(3):
            store.add({'recording_id':'a'*32, 'frame_id':i, 'timestamp':now - 3 + i,
                       'person_count':i, 'detections':[{'class_name':'Person'}] * i}, bytes([i])*10)
        meta, jpeg = store.get(at=now-1.5)
        self.assertEqual(meta['frame_id'], 1)
        self.assertEqual(meta['person_count'], len(meta['detections']))
        self.assertEqual(jpeg, bytes([1])*10)
        self.assertEqual(store.get(recording_id='a'*32, frame_id=1), (meta, jpeg))
        self.assertIsNone(store.get(at=now-4))
        self.assertIsNone(store.get(at=now+1))
        self.assertEqual(frame_payload((meta,jpeg))['person_count'],1)
        restarted = FrameStore(self.root/'frames')
        self.assertEqual(restarted.get(recording_id='a'*32,frame_id=1),(meta,jpeg))

    def test_retention_and_capacity(self):
        store = FrameStore(self.root/'frames', retention=30, max_bytes=15)
        now = time.time()
        for i in range(3):
            store.add({'recording_id':'b'*32,'frame_id':i,'timestamp':now-3+i}, b'1234567890')
        self.assertEqual(store.bounds()['frames'],1)
        self.assertTrue(store.bounds()['capacity_limited'])
        self.assertFalse(store.contains('b'*32,0))
        store.prune(now=now+31)
        self.assertEqual(store.bounds()['frames'],0)
        self.assertEqual(list((self.root/'frames').glob('*.jpg')),[])
        self.assertEqual(list((self.root/'frames').glob('*.json')),[])

    def test_locked_expired_file_retries_without_exceeding_capacity(self):
        store=FrameStore(self.root/'frames',retention=30,max_bytes=10)
        now=time.time()
        meta={'recording_id':'d'*32,'frame_id':1,'timestamp':now}
        store.add(meta,b'12345678')
        original_unlink=Path.unlink
        def locked(path, *args, **kwargs):
            if path.suffix=='.jpg':
                raise PermissionError('simulated file lock')
            return original_unlink(path,*args,**kwargs)
        with patch.object(Path,'unlink',locked):
            store.prune(now=now+31)
            self.assertIsNone(store.get())
            self.assertEqual(store.bytes,8)
            self.assertFalse(store.add({**meta,'frame_id':2},b'1234'))
            self.assertEqual(FrameStore(self.root/'frames',retention=30,max_bytes=10).bytes,8)
        store.prune()
        self.assertEqual(store.bytes,0)
        self.assertEqual(store.pending_deletes,{})

    def test_filters_today_and_settings(self):
        with database.get_connection() as conn:
            for timestamp in ['2026-09-21T14:59:59.999Z', '2026-09-21T15:00:00.000Z', '2026-09-22T14:59:59.999Z', '2026-09-22T15:00:00.000Z']:
                conn.execute("INSERT INTO safety_events(camera_name,event_type,created_at) VALUES ('CAM-01','NO-Hardhat',?)",(timestamp,))
        rows = database.get_events(day=date(2026,9,22),event_type='NO-Hardhat',review_status='pending')
        self.assertEqual(len(rows),2)
        self.assertEqual({row['created_at'] for row in rows}, {'2026-09-21T15:00:00.000Z','2026-09-22T14:59:59.999Z'})
        database.review_event(rows[0]['id'])
        self.assertEqual(len(database.get_events(day=date(2026,9,22),review_status='reviewed')),1)
        self.assertEqual(database.retention_seconds(),30 * 86400)
        self.assertEqual(database.retention_seconds(120),120)
        self.assertEqual(database.retention_seconds(),120)

    def test_api_expired_event_and_snapshot(self):
        from video_test_support import video_client
        with video_client(self.root/'recordings') as (main, client):
            event_id = database.save_event('CAM-01','NO-Hardhat',event_key='isolated')
            database.attach_recording('isolated','c'*32,1,'e'*64+'.jpg')
            (main.monitor.snapshots/('e'*64+'.jpg')).write_bytes(b'test-snapshot')
            now = time.time()
            main.monitor.store.add({'recording_id':'c'*32,'frame_id':1,'timestamp':now},b'frame')
            self.assertTrue(client.get(f'/api/events/{event_id}').json()['playable'])
            self.assertEqual(client.get(f'/api/events/{event_id}/snapshot').content,b'test-snapshot')
            self.assertEqual(client.get('/api/recordings/frame',params={'at':now+100}).status_code,410)
            main.monitor.store.prune(now=now+30*86400+1)
            self.assertFalse(client.get(f'/api/events/{event_id}').json()['playable'])
            self.assertEqual(client.get('/api/recordings/frame').status_code,410)
            self.assertEqual(client.patch('/api/settings',json={'retention_seconds':1}).status_code,422)
            self.assertEqual(client.patch('/api/settings',json={'retention_seconds':30*86400+1}).status_code,422)
            self.assertEqual(client.patch('/api/settings',json={'retention_seconds':30*86400}).status_code,200)
            self.assertEqual(client.patch('/api/settings',json={'retention_seconds':60}).status_code,200)
            self.assertEqual(database.retention_seconds(),60)
            client.patch(f'/api/events/{event_id}')
            self.assertEqual(client.get(f'/api/events/{event_id}').json()['review_status'],'reviewed')

    def test_month_retention_survives_restart_without_old_capacity_limit(self):
        root = self.root/'month'
        root.mkdir()
        now = time.time()
        for frame_id, age, size in [(1,29,257*1024*1024),(2,31,10)]:
            stem = root/f"{'a'*32}_{frame_id}"
            with stem.with_suffix('.jpg').open('wb') as stream:
                stream.truncate(size)
            stem.with_suffix('.json').write_text(json.dumps({
                'recording_id':'a'*32, 'frame_id':frame_id,
                'timestamp':now-age*86400}),encoding='utf-8')
        store = FrameStore(root)
        self.assertTrue(store.contains('a'*32,1))
        self.assertFalse(store.contains('a'*32,2))
        self.assertFalse(store.capacity_limited)
        self.assertIsNone(store.max_bytes)
        self.assertTrue(FrameStore(root).contains('a'*32,1))

    def test_snapshots_follow_month_retention(self):
        import os
        monitor = Monitor(None, self.root/'model.pt', self.root/'test.mp4', self.root/'snapshots-test')
        now=time.time()
        paths=[]
        for character, age in [('a',29),('b',31)]:
            path=monitor.snapshots/(character*64+'.jpg')
            path.write_bytes(b'jpeg')
            os.utime(path,(now-age*86400,now-age*86400))
            paths.append(path)
        monitor._cleanup_snapshots()
        self.assertTrue(paths[0].exists())
        self.assertFalse(paths[1].exists())

    def test_low_disk_space_does_not_delete_recent_frames(self):
        from collections import namedtuple
        store=FrameStore(self.root/'disk')
        meta={'recording_id':'f'*32,'frame_id':1,'timestamp':time.time()}
        store.add(meta,b'original')
        usage=namedtuple('Usage','total used free')(100,99,1)
        with patch('monitor.shutil.disk_usage',return_value=usage):
            with self.assertRaises(OSError):
                store.add({**meta,'frame_id':2},b'new')
        self.assertEqual(store.get(recording_id='f'*32,frame_id=1)[1],b'original')


if __name__ == '__main__':
    unittest.main()
