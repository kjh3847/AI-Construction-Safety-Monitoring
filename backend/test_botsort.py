"""Exercise installed BoT-SORT on synthetic boxes, without loading model weights."""
import importlib.util
import unittest
import numpy as np

from inference import LocalBoTSORT


@unittest.skipUnless(importlib.util.find_spec('ultralytics'),'Ultralytics dependency required')
class BoTSORTTests(unittest.TestCase):
    def test_independent_trackers_and_no_plotting(self):
        import torch
        from ultralytics.engine.results import Results
        frame=np.zeros((240,320,3),dtype=np.uint8)
        trackers=[LocalBoTSORT(),LocalBoTSORT()]
        outputs=[]
        for tracker in trackers:
            first=Results(frame,'fixture',names={0:'Person'},boxes=torch.tensor([[10,10,100,200,.95,0]]))
            second=Results(frame,'fixture',names={0:'Person'},boxes=torch.tensor([[12,10,102,200,.95,0]]))
            a=tracker.detections(first,frame)
            b=tracker.detections(second,frame)
            self.assertEqual(a[0]['upstream_track_id'],b[0]['upstream_track_id'])
            self.assertIsNotNone(a[0]['upstream_track_id'])
            outputs.append(a)
        self.assertIsNot(trackers[0].tracker,trackers[1].tracker)
        self.assertEqual(outputs[0][0]['class_name'],'Person')
