"""Drain live camera frames independently of inference; keep only the newest."""
from threading import Condition, Event, Thread
import os
os.environ.setdefault('OPENCV_FFMPEG_LOGLEVEL','-8')
import time

import cv2


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


class ReconnectingCapture:
    """Own the capture entirely in one thread, including open/release/retry."""
    def __init__(self, source, opener=None):
        self.source = source
        self.opener = opener or self._open
        self.condition = Condition()
        self.stop_event = Event()
        self.latest = None
        self.latest_clock = {}
        self.consumed_clock = {}
        self.sequence = self.consumed = 0
        self.generation = 0
        self.connection_state = 'starting'
        self.last_received = None
        self.capture_fps = self.decode_ms = 0
        self.reconnect_count = 0
        self.thread = Thread(target=self._receive, daemon=True, name='camera-capture')
        self.thread.start()

    def _open(self, source):
        if isinstance(source, str):
            return cv2.VideoCapture(source, cv2.CAP_FFMPEG, [
                cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000, cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000])
        return cv2.VideoCapture(source)

    def _receive(self):
        enabled = os.getenv('CAMERA_RECONNECT_ENABLED', 'true').lower() == 'true'
        interval = max(.05, float(os.getenv('CAMERA_RECONNECT_INTERVAL', '5')))
        delay = interval
        while not self.stop_event.is_set():
            cap = None
            received = 0
            origin = time.monotonic()
            try:
                cap = self.opener(self.source)
                if not cap.isOpened():
                    self.connection_state = 'disconnected'
                else:
                    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                    self.generation += 1
                    while not self.stop_event.is_set():
                        started = time.perf_counter()
                        ok, frame = cap.read()
                        self.decode_ms = (time.perf_counter()-started)*1000
                        if not ok:
                            break
                        received += 1
                        with self.condition:
                            self.last_received = time.time()
                            self.latest = frame, self.last_received
                            self.latest_clock = dict(getattr(cap,'last_clock',{}))
                            self.sequence += 1
                            self.capture_fps = received/max(.001,time.monotonic()-origin)
                            self.connection_state = 'running'
                            self.condition.notify_all()
                    self.connection_state = 'disconnected'
            except Exception:
                self.connection_state = 'disconnected'
            finally:
                if cap is not None:
                    cap.release()
            if not enabled:
                break
            # A flapping stream must also back off; only sustained recovery resets it.
            if received >= 30:
                delay = interval
            self.reconnect_count += 1
            self.connection_state = 'reconnecting'
            if self.stop_event.wait(delay):
                break
            delay = min(60, delay*2)
        with self.condition:
            self.connection_state = 'stopped' if self.stop_event.is_set() else 'disconnected'
            self.condition.notify_all()

    def read(self, timeout=.5):
        with self.condition:
            self.condition.wait_for(lambda: self.sequence > self.consumed or self.stop_event.is_set(), timeout)
            if self.sequence <= self.consumed:
                return False, None, None
            self.consumed = self.sequence
            self.consumed_clock = dict(self.latest_clock)
            return True, *self.latest

    def stats(self):
        return dict(connection_state=self.connection_state, last_received=self.last_received,
                    capture_fps=round(self.capture_fps,2), decode_ms=round(self.decode_ms,2),
                    reconnect_count=self.reconnect_count)

    def close(self):
        self.stop_event.set()
        with self.condition:
            self.condition.notify_all()
        self.thread.join(timeout=11)
