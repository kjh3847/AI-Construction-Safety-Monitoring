"""Independent inference worker and bounded, seekable annotated-frame recording."""
import base64
from collections import deque
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from threading import Event, RLock, Thread
import time
import uuid

import cv2

from database import attach_recording, get_connection, fill_event_counts
from event_recorder import EventRecorder
from person_safety import associate_people, event_counts, ASSOCIATION_METHOD


class FrameStore:
    def __init__(self, root, retention=300, max_bytes=256 * 1024 * 1024):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.retention = retention
        self.max_bytes = max_bytes
        self.lock = RLock()
        self.frames = deque()
        self.bytes = 0
        self.sizes = {}
        self.pending_deletes = {}
        self.capacity_limited = False
        for path in self.root.glob('*.json'):
            if not re.fullmatch(r'[a-f0-9]{32}_\d+\.json', path.name):
                continue
            try:
                meta = json.loads(path.read_text('utf-8'))
                jpeg = path.with_suffix('.jpg')
                if jpeg.exists():
                    self.frames.append(meta)
                    size = jpeg.stat().st_size
                    self.bytes += size
                    self.sizes[jpeg] = size
            except (OSError, ValueError, KeyError):
                continue
        self.frames = deque(sorted(self.frames, key=lambda item: item['timestamp']))
        self.prune()

    def _path(self, frame):
        return self.root / f"{frame['recording_id']}_{frame['frame_id']}.jpg"

    def prune(self, now=None, reserve=0):
        with self.lock:
            for path, size in list(self.pending_deletes.items()):
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    continue
                self.bytes -= size
                del self.pending_deletes[path]
            cutoff = (time.time() if now is None else now) - self.retention
            while self.frames and (self.frames[0]['timestamp'] < cutoff or self.bytes + reserve > self.max_bytes):
                if self.bytes + reserve > self.max_bytes:
                    self.capacity_limited = True
                frame = self.frames.popleft()
                path = self._path(frame)
                for target, size in ((path, self.sizes.pop(path, 0)), (path.with_suffix('.json'), 0)):
                    try:
                        target.unlink(missing_ok=True)
                    except OSError:
                        # OneDrive/Windows can lock a file temporarily. It is
                        # no longer playable, but still counts toward capacity.
                        self.pending_deletes[target] = size
                    else:
                        self.bytes -= size

    def add(self, meta, jpeg):
        with self.lock:
            self.prune(reserve=len(jpeg))
            if self.bytes + len(jpeg) > self.max_bytes or len(self.pending_deletes) > 10000:
                self.capacity_limited = True
                return False
            path = self._path(meta)
            path.write_bytes(jpeg)
            path.with_suffix('.json').write_text(json.dumps(meta), encoding='utf-8')
            self.frames.append(meta)
            self.bytes += len(jpeg)
            self.sizes[path] = len(jpeg)
            self.prune()
            return True

    def bounds(self):
        with self.lock:
            self.prune()
            return {'start': self.frames[0]['timestamp'] if self.frames else None,
                    'end': self.frames[-1]['timestamp'] if self.frames else None,
                    'retention_seconds': self.retention, 'frames': len(self.frames),
                    'bytes': self.bytes, 'max_bytes': self.max_bytes,
                    'capacity_limited': self.capacity_limited}

    def get(self, at=None, recording_id=None, frame_id=None):
        with self.lock:
            self.prune()
            if not self.frames:
                return None
            if recording_id is not None:
                chosen = next((f for f in self.frames if f['recording_id'] == recording_id
                               and f['frame_id'] == frame_id), None)
            elif at is not None:
                if at < self.frames[0]['timestamp'] or at > self.frames[-1]['timestamp']:
                    return None
                chosen = next((f for f in reversed(self.frames) if f['timestamp'] <= at), None)
            else:
                chosen = self.frames[-1]
            if chosen is None:
                return None
            try:
                return dict(chosen), self._path(chosen).read_bytes()
            except OSError:
                return None

    def contains(self, recording_id, frame_id):
        with self.lock:
            return any(f['recording_id'] == recording_id and f['frame_id'] == frame_id for f in self.frames)


class Monitor:
    def __init__(self, model, model_path, video_path, root, camera_name=None, use_camera_env=True, inference_lock=None):
        self.model = model
        self.model_path = Path(model_path)
        self.video_path = Path(video_path)
        source = os.getenv('CAMERA_SOURCE', '').strip() if use_camera_env else ''
        self.source = int(source) if source.isdigit() else source or str(video_path)
        self.source_kind = 'camera' if source else 'test'
        self.camera_name = camera_name or os.getenv('CAMERA_NAME', 'CAM-01')
        self.inference_lock = inference_lock or RLock()
        self.source_name = '실제 카메라' if source else self.video_path.name
        self.store = FrameStore(Path(root) / 'frames')
        self.snapshots = Path(root) / 'snapshots'
        self.snapshots.mkdir(parents=True, exist_ok=True)
        self.lock = RLock()
        self.stop_event = Event()
        self.shutdown_event = Event()
        self.thread = None
        self.janitor = None
        self.state = 'idle'
        self.error = None
        self.updated_at = None
        self.recording_id = None

    def initialize(self, retention):
        self.store.retention = retention
        # Backfill only exact retained source frames, never today's live count.
        with get_connection() as conn:
            rows = conn.execute('SELECT event_key,event_type,recording_id,frame_id FROM safety_events WHERE event_person_count IS NULL AND recording_id IS NOT NULL').fetchall()
        for row in rows:
            frame = self.store.get(recording_id=row['recording_id'], frame_id=row['frame_id'])
            if frame and 'detections' in frame[0]:
                fill_event_counts(row['event_key'], event_counts(frame[0]['detections'], row['event_type']))
        self.shutdown_event.clear()
        if self.janitor is None or not self.janitor.is_alive():
            self.janitor = Thread(target=self._cleanup_loop, daemon=True)
            self.janitor.start()

    def _cleanup_loop(self):
        while not self.shutdown_event.wait(5):
            self.store.prune()
            try:
                self._cleanup_snapshots()
            except OSError:
                # Retry after transient file locks without killing the janitor.
                continue

    def _cleanup_snapshots(self):
            files = sorted((p for p in self.snapshots.glob('*.jpg')
                            if re.fullmatch(r'[a-f0-9]{64}\.jpg', p.name)), key=lambda p: p.stat().st_mtime)
            total = sum(p.stat().st_size for p in files)
            for path in files:
                if path.stat().st_mtime < time.time() - 7 * 86400 or total > 512 * 1024 * 1024:
                    total -= path.stat().st_size
                    path.unlink(missing_ok=True)

    def start(self):
        with self.lock:
            if self.thread and self.thread.is_alive():
                return
            self.stop_event.clear()
            self.state, self.error, self.updated_at = 'starting', None, None
            self.recording_id = uuid.uuid4().hex
            self.thread = Thread(target=self._run, daemon=True)
            self.thread.start()

    def stop(self):
        self.stop_event.set()
        with self.lock:
            if self.thread and self.thread.is_alive():
                self.state = 'stopping'

    def shutdown(self):
        self.stop()
        self.shutdown_event.set()
        if self.thread:
            self.thread.join(timeout=12)
        if self.janitor:
            self.janitor.join(timeout=2)

    def status(self):
        with self.lock:
            stale = self.state == 'running' and self.updated_at and time.time() - self.updated_at > 10
            return {'state': 'disconnected' if stale else self.state, 'error': self.error,
                    'updated_at': self.updated_at, 'camera_name': self.camera_name,
                    'source_name': self.source_name, 'source_kind': self.source_kind,
                    'recording_id': self.recording_id, 'buffer': self.store.bounds(),
                    'model_name': self.model_path.name, 'classes': self.model.names,
                    'person_association': True, 'person_association_method': ASSOCIATION_METHOD}

    def _run(self):
        cap = None
        try:
            if isinstance(self.source, str) and self.source.startswith(('rtsp://', 'http://', 'https://')):
                cap = cv2.VideoCapture(self.source, cv2.CAP_FFMPEG,
                    [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000, cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000])
            else:
                cap = cv2.VideoCapture(self.source)
            if not cap.isOpened():
                with self.lock:
                    self.state = 'disconnected' if self.source_kind == 'camera' else 'error'
                    self.error = '영상 소스를 열 수 없습니다. 카메라 연결 또는 시험 파일을 확인하세요.'
                return
            fps = cap.get(cv2.CAP_PROP_FPS)
            fps = fps if 0 < fps <= 240 else 25
            digest = hashlib.sha256()
            for path in (self.video_path, self.model_path) if self.source_kind == 'test' else (self.model_path,):
                with path.open('rb') as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                        digest.update(chunk)
            source_id = digest.hexdigest() if self.source_kind == 'test' else self.recording_id
            recorder = EventRecorder(source_id, self.model_path.name, self.source_name, camera_name=self.camera_name)
            frame_id, last_saved = 0, 0
            origin = time.monotonic()
            while not self.stop_event.is_set():
                started = time.monotonic()
                success, frame = cap.read()
                captured = time.time()
                if not success:
                    with self.lock:
                        self.state = 'finished' if self.source_kind == 'test' else 'disconnected'
                        self.error = None if self.source_kind == 'test' else '카메라 영상 수신이 끊겼습니다.'
                    break
                # Ultralytics predictor is shared by the two sources.
                with self.inference_lock:
                    result = self.model.predict(source=frame, imgsz=640, conf=0.4, device='cpu', verbose=False)[0]
                detections = [{'class_name': result.names[int(box.cls.item())],
                    'confidence': float(box.conf.item()), 'bbox': box.xyxy[0].tolist()} for box in result.boxes]
                video_seconds = frame_id / fps if self.source_kind == 'test' else started - origin
                recorder.record(detections, frame_id, video_seconds,
                    datetime.fromtimestamp(captured, timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z'))
                # DVR stores up to 5 fps plus every new event frame. Inference
                # continues on all decoded frames, independently of viewers.
                if captured - last_saved >= .2 or recorder.episode_keys:
                    ok, buffer = cv2.imencode('.jpg', result.plot(), [cv2.IMWRITE_JPEG_QUALITY, 80])
                    if not ok:
                        raise RuntimeError('녹화 프레임 인코딩 실패')
                    jpeg = buffer.tobytes()
                    meta = {'recording_id': self.recording_id, 'frame_id': frame_id,
                        'timestamp': captured, 'captured_at': datetime.fromtimestamp(captured, timezone.utc).isoformat(),
                        'video_seconds': video_seconds, 'camera_name': self.camera_name,
                        'source_kind': self.source_kind, 'source_name': self.source_name,
                        'detections': detections,
                        'person_count': sum(d['class_name'] == 'Person' for d in detections),
                        **associate_people(detections),
                        'negative_detection_count': sum(d['class_name'] in ('NO-Hardhat', 'NO-Safety Vest') for d in detections)}
                    self.store.add(meta, jpeg)
                    for key in recorder.episode_keys:
                        name = hashlib.sha256(key.encode()).hexdigest() + '.jpg'
                        (self.snapshots / name).write_bytes(jpeg)
                        attach_recording(key, self.recording_id, frame_id, name)
                    last_saved = captured
                with self.lock:
                    self.state, self.updated_at = 'running', captured
                frame_id += 1
                if self.source_kind == 'test':
                    self.stop_event.wait(max(0, 1 / fps - (time.monotonic() - started)))
        except Exception as exc:
            with self.lock:
                self.state = 'error'
                # Avoid returning camera URLs / credentials in exception text.
                self.error = '영상 감지 또는 저장에 실패했습니다. 서버 로그와 소스 연결을 확인하세요.'
            import logging
            logging.getLogger(__name__).error('Monitor failed (%s)', type(exc).__name__)
        finally:
            if cap is not None:
                cap.release()
            with self.lock:
                if self.stop_event.is_set():
                    self.state = 'stopped'


def frame_payload(frame):
    meta, jpeg = frame
    # Old recordings contain the actual boxes too: calculate from that frame,
    # never from current live detections. Leave files/DB unchanged.
    if 'person_association_method' not in meta and 'detections' in meta:
        meta = {**meta, **associate_people(meta['detections'])}
    return {**meta, 'image': 'data:image/jpeg;base64,' + base64.b64encode(jpeg).decode('ascii')}
