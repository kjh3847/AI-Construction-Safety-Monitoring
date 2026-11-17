"""Exercise deduplication with isolated DB and actual person/negative box relationships."""
import tempfile
from pathlib import Path
import unittest
import database
from event_recorder import EventRecorder


def person(x=0, bad=True, vest=False):
    boxes = [('Person', [x,0,x+100,200])]
    if bad:
        boxes.append(('NO-Hardhat',[x+30,0,x+70,40]))
    if vest:
        boxes.append(('NO-Safety Vest',[x+20,60,x+80,150]))
    return [{'class_name': name, 'bbox': box, 'confidence': .9} for name,box in boxes]


class PersonDedupTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original = database.DB_PATH
        database.DB_PATH = Path(self.temp.name)/'test.db'
        database.init_db()
        self.recorder = EventRecorder('hash','best.pt','test.mp4')

    def tearDown(self):
        database.DB_PATH = self.original
        self.temp.cleanup()

    def observe(self, detections, start=0, recorder=None):
        recorder = recorder or self.recorder
        saved = []
        for frame in range(start * 2, (start + 3) * 2 + 1):
            saved.extend(recorder.record(detections, frame, frame / 2))
        return saved

    def test_transient_vest_miss_and_conflicting_worn_box_do_not_record(self):
        worn = person(bad=False)
        worn.append({'class_name': 'Safety Vest', 'bbox': [20,60,80,150], 'confidence': .9})
        for frame in range(7):
            if frame == 0:
                detections = person(bad=False, vest=True)
            elif frame == 6:
                detections = worn + person(bad=False, vest=True)[1:]
            else:
                detections = worn
            self.assertEqual(self.recorder.record(detections, frame, frame / 2), [])
        self.assertEqual(database.event_summary()['total'], 0)

    def test_one_worn_vote_is_tolerated_when_vest_is_mostly_missing(self):
        for frame in range(7):
            detections = person(bad=frame == 6, vest=frame != 3)
            if frame == 3:
                detections.append({'class_name': 'Safety Vest', 'bbox': [20,60,80,150], 'confidence': .9})
            saved = self.recorder.record(detections, frame, frame / 2)
            self.assertEqual(len(saved), int(frame == 6))
        event = database.get_events()[0]
        self.assertEqual(event['event_type'], 'NO-Safety Vest')
        self.assertEqual(event['violation_types'], '["NO-Safety Vest"]')
        self.assertEqual(event['video_seconds'], 3)

    def test_one_unopposed_negative_and_too_few_samples_do_not_record(self):
        for frame in range(7):
            self.assertEqual(self.recorder.record(person(bad=frame == 0), frame, frame / 2), [])
        self.assertEqual(database.event_summary()['total'], 0)
        for second in range(10, 17):
            self.assertEqual(self.recorder.record(person(), second * 2, second), [])

    def test_one_capture_even_after_negative_class_disappears(self):
        self.assertEqual(len(self.observe(person(vest=True))),1)
        for frame in range(31,601):
            self.recorder.record(person(x=min(frame,50),bad=frame%80<5,vest=frame>400),frame,frame/10)
            self.assertEqual(self.recorder.episode_keys,[])
        self.assertEqual(database.event_summary()['total'],1)

    def test_short_person_dropout_and_other_person_are_distinct(self):
        self.observe(person())
        self.recorder.record([],8,4)
        self.assertEqual(self.recorder.record(person(5),9,4.5),[])
        self.assertEqual(len(self.observe(person(5)+person(300),start=5)),1)
        self.assertEqual(database.event_summary()['total'],2)
        self.assertEqual(len({row['person_track_id'] for row in database.get_events()}),2)

    def test_new_person_after_timeout_and_camera_isolation(self):
        self.observe(person())
        self.assertEqual(len(self.observe(person(),start=14)),1)
        other = EventRecorder('hash','best.pt','test.mp4',camera_name='CAM-02')
        self.assertEqual(len(self.observe(person(),recorder=other)),1)

    def test_unassigned_negative_is_not_a_person_event(self):
        self.assertEqual(self.recorder.record(person()[1:],0,0),[])
        self.assertEqual(database.event_summary()['total'],0)

    def test_detection_order_changes_preserve_tracks(self):
        first = person()+person(300)
        self.assertEqual(len(self.observe(first)),2)
        self.assertEqual(self.recorder.record(list(reversed(first)),7,3.5),[])

    def test_immediate_zoom_keeps_person_but_distant_person_does_not(self):
        from person_tracker import PersonTracker
        tracker = PersonTracker()
        def boxes(box):
            return [{'class_name':'Person','bbox':box}]
        first = tracker.update(boxes([194,62,316,325]),180,6)[0]['id']
        self.assertEqual(tracker.update(boxes([256,6,539,359]),194,6.46)[0]['id'], first)
        self.assertNotEqual(tracker.update(boxes([700,6,800,300]),195,6.5)[0]['id'], first)


if __name__ == '__main__':
    unittest.main()
