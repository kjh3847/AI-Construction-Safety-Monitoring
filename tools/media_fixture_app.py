"""Explicit integration-test detector. Never used by production main:app."""
import os
from pathlib import Path
import time

if not (os.getenv('MEDIA_TEST_SOURCE')=='true' and os.getenv('LOCAL_DEMO_ENABLED')=='true'):
    raise RuntimeError('Synthetic detector is restricted to isolated integration tests')

import torch
from ultralytics.engine.results import Results
import main


class FixtureEngine:
    def predict(self,frame):
        started=time.perf_counter()
        # These are synthetic fixture coordinates, not detections of real people.
        boxes=torch.tensor([[100,130,230,350,.95,0],[130,130,180,175,.9,1]])
        result=Results(frame,'TEST SOURCE',names={0:'Person',1:'NO-Hardhat'},boxes=boxes)
        return result,0,(time.perf_counter()-started)*1000


fixture=Path(os.environ['SAFETY_DB_PATH']).parent/'fixture-not-yolo.pt'
fixture.write_bytes(b'Explicit test fixture; not trained model weights')
for source in main.monitors().values():
    source.engine=FixtureEngine();source.model_path=fixture
app=main.app
