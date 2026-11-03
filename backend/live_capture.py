"""Drain live camera frames independently of inference; keep only the newest."""
from threading import Condition, Event, Thread
import time


class LatestFrameReader:
    def __init__(self, capture):
        self.capture = capture
        self.condition = Condition()
        self.stop_event = Event()
        self.latest = None
        self.sequence = 0
        self.consumed = 0
        self.finished = False
        self.thread = Thread(target=self._receive, daemon=True)
        self.thread.start()

    def _receive(self):
        try:
            while not self.stop_event.is_set():
                ok, frame = self.capture.read()
                if not ok:
                    break
                with self.condition:
                    self.latest = (frame, time.time())
                    self.sequence += 1
                    self.condition.notify_all()
        finally:
            self.capture.release()
            with self.condition:
                self.finished = True
                self.condition.notify_all()

    def read(self, timeout=6):
        with self.condition:
            self.condition.wait_for(
                lambda: self.sequence > self.consumed or self.finished,
                timeout=timeout,
            )
            if self.sequence <= self.consumed:
                return False, None, None
            self.consumed = self.sequence
            frame, captured = self.latest
            return True, frame, captured

    def close(self):
        self.stop_event.set()
        self.thread.join(timeout=6)
