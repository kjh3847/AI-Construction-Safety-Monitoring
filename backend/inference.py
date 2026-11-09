"""One set of weights, FIFO admission, and a separate BoT-SORT per camera."""
from collections import deque
from contextlib import contextmanager
from threading import Condition, RLock
import os
import time


class FairInference:
    def __init__(self, model):
        self.model = model
        self.condition = Condition()
        self.queue = deque()
        self.busy = False

    @contextmanager
    def turn(self):
        ticket = object()
        with self.condition:
            self.queue.append(ticket)
            self.condition.wait_for(lambda: not self.busy and self.queue[0] is ticket)
            self.queue.popleft()
            self.busy = True
        try:
            yield
        finally:
            with self.condition:
                self.busy = False
                self.condition.notify_all()

    def predict(self, frame):
        queued = time.perf_counter()
        with self.turn():
            started = time.perf_counter()
            result = self.model.predict(source=frame, imgsz=int(os.getenv('INFERENCE_SIZE', '640')),
                conf=.4, device=os.getenv('INFERENCE_DEVICE', 'cpu'), verbose=False)[0]
        return result, (started-queued)*1000, (time.perf_counter()-started)*1000


_botsort_lock = RLock()


class LocalBoTSORT:
    def __init__(self):
        self.tracker = None
        self.counter = 0

    def detections(self, result, frame):
        with _botsort_lock:
            return self._detections(result,frame)

    def _detections(self, result, frame):
        from ultralytics.trackers.basetrack import BaseTrack
        # Upstream uses a process-wide ID counter, even with separate tracker
        # instances. Scope it to this camera while updating under a short lock.
        BaseTrack._count = self.counter
        if self.tracker is None:
            from ultralytics.trackers.bot_sort import BOTSORT
            from ultralytics.utils import IterableSimpleNamespace, YAML
            from ultralytics.utils.checks import check_yaml
            args = IterableSimpleNamespace(**YAML.load(check_yaml('botsort.yaml')))
            # Camera-to-camera appearance is handled separately by GlobalTracker.
            args.with_reid = False
            self.tracker = BOTSORT(args=args)
        boxes = result.boxes.cpu().numpy()
        person_indices = [index for index,box in enumerate(result.boxes)
                          if result.names[int(box.cls.item())] == 'Person']
        tracks = self.tracker.update(boxes[person_indices], frame)
        self.counter = BaseTrack._count
        ids = {person_indices[int(row[-1])]: int(row[4]) for row in tracks}
        return [{'class_name': result.names[int(box.cls.item())],
                 'confidence': float(box.conf.item()), 'bbox': box.xyxy[0].tolist(),
                 'upstream_track_id': ids.get(index)} for index, box in enumerate(result.boxes)]
