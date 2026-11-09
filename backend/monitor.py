"""Independent analysis, in-memory live frames, and asynchronous seekable recording."""
import base64
from datetime import datetime, timezone
import hashlib
import os
os.environ.setdefault('OPENCV_FFMPEG_LOGLEVEL','-8')
from pathlib import Path
import re
import shutil
from threading import Event, RLock, Thread
import time
import uuid
from queue import Queue, Full

import cv2

from database import attach_recording, get_connection, fill_event_counts
from event_recorder import EventRecorder
from person_safety import associate_people, event_counts, ASSOCIATION_METHOD
from camera_config import classify_source
from inference import FairInference, LocalBoTSORT


from frame_store import FrameStore


class Monitor:
    def __init__(self, model, model_path, video_path, root, camera_name=None, use_camera_env=True,
                 engine=None, global_tracker=None, camera_id=None, adapter='direct'):
        self.model = model
        self.adapter = adapter
        self.model_path = Path(model_path)
        source = os.getenv('CAMERA_SOURCE', '').strip() if use_camera_env else ''
        self.source, self.source_type = classify_source(source or video_path)
        self.source_kind = 'test' if self.source_type == 'file' else 'camera'
        self.video_path = Path(self.source) if self.source_type == 'file' else None
        self.camera_name = camera_name or os.getenv('CAMERA_NAME', 'CAM-01')
        self.camera_id = camera_id or self.camera_name
        self.engine = engine or FairInference(model)
        self.global_tracker = global_tracker
        self.source_name = self.video_path.name if self.video_path else '미설정' if self.source is None else '실제 카메라'
        if self.adapter=='mediamtx':self.source_name='MediaMTX 스트림'
        capacity = int(os.getenv('RECORDING_MAX_BYTES_PER_CAMERA', '0')) or None
        self.store = FrameStore(Path(root) / 'frames', max_bytes=capacity)
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
        self.latest = None
        self.capture = None
        self.metrics = {}
        self.storage_error = None
        self.writer_queue = Queue(maxsize=32)
        self.writer = None

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
            try:
                self.store.prune()
                self._cleanup_snapshots()
            except OSError:
                # Retry after transient file locks without killing the janitor.
                continue

    def _cleanup_snapshots(self):
        for path in self.snapshots.glob('*.jpg'):
            if re.fullmatch(r'[a-f0-9]{64}\.jpg',path.name) and path.stat().st_mtime < time.time()-self.store.retention:
                path.unlink(missing_ok=True)

    def start(self):
        with self.lock:
            if self.source is None:
                self.state,self.error = 'idle',None
                return
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
            self.thread.join(timeout=20)
        if self.janitor:
            self.janitor.join(timeout=2)

    def status(self):
        with self.lock:
            stale = self.state == 'running' and self.updated_at and time.time() - self.updated_at > 10
            current = self.latest[0] if self.latest and self.state == 'running' and not stale else None
            return {'state': 'unconfigured' if self.source is None else 'disconnected' if stale else self.state, 'error': self.error,
                    'updated_at': self.updated_at, 'camera_name': self.camera_name,
                    'source_name': self.source_name, 'source_kind': self.source_kind,
                    'source_type': self.source_type, 'configured': self.source is not None,
                    'input_adapter':self.adapter,'live_transport':'webrtc' if self.adapter=='mediamtx' else 'binary',
                    'metrics': {**self.metrics, **(self.capture.stats() if self.capture else {})},
                    'storage_error': self.storage_error,
                    'current_counts':({key:current.get(key) for key in ('person_count','noncompliant_person_count')}
                                      if current else None),
                    'recording_id': self.recording_id, 'buffer': self.store.bounds(),
                    'model_name': self.model_path.name, 'classes': getattr(self.model,'names',{}),
                    'person_association': True, 'person_association_method': ASSOCIATION_METHOD}

    def latest_frame(self):
        with self.lock:
            return self.latest

    def _write_loop(self):
        while True:
            item = self.writer_queue.get()
            try:
                if item is None:
                    return
                meta, jpeg, keys = item
                started = time.perf_counter()
                retained = self.store.add(meta, jpeg)
                for key in keys:
                    name = hashlib.sha256(key.encode()).hexdigest() + '.jpg'
                    (self.snapshots / name).write_bytes(jpeg)
                    attach_recording(key, meta['recording_id'] if retained else None,
                                     meta['frame_id'] if retained else None, name)
                self.metrics['recording_write_ms'] = round((time.perf_counter()-started)*1000,2)
                self.storage_error = None if retained else '녹화 용량 한도에 도달했습니다.'
            except Exception:
                self.storage_error = '녹화 저장 실패 · 디스크 공간과 권한을 확인하세요.'
            finally:
                self.writer_queue.task_done()

    def _run(self):
        cap = None
        live_reader = None
        try:
            if self.source is None:
                self.state, self.error = 'idle', '카메라 입력이 설정되지 않았습니다.'
                return
            if self.source_kind == 'test':
                cap = cv2.VideoCapture(self.source)
                if not cap.isOpened():
                    self.state, self.error = 'error', '시험 영상 파일을 열 수 없습니다.'
                    return
            else:
                from live_capture import ReconnectingCapture
                if self.adapter=='mediamtx':
                    from rtsp_clock import RTSPClockCapture
                    self.capture = live_reader = ReconnectingCapture(self.source,RTSPClockCapture)
                else:self.capture = live_reader = ReconnectingCapture(self.source)
            fps = cap.get(cv2.CAP_PROP_FPS) if cap else 25
            fps = fps if 0 < fps <= 240 else 25
            digest = hashlib.sha256()
            for path in (self.video_path, self.model_path) if self.source_kind == 'test' else ():
                with path.open('rb') as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                        digest.update(chunk)
            source_id = digest.hexdigest() if self.source_kind == 'test' else self.recording_id
            recorder = EventRecorder(source_id, self.model_path.name, self.source_name,
                                     camera_name=self.camera_name,camera_id=self.camera_id)
            frame_id, last_saved, last_generation = 0, 0, None
            origin = time.monotonic()
            local_tracker = LocalBoTSORT()
            self.writer = Thread(target=self._write_loop, daemon=True, name=f'{self.camera_id}-recording')
            self.writer.start()
            analysis_interval = 1/max(.1,float(os.getenv('ANALYSIS_FPS', '5')))
            recording_interval = 1/max(.1,float(os.getenv('RECORDING_FPS', '2')))
            while not self.stop_event.is_set():
                started = time.monotonic()
                if live_reader is not None:
                    success, frame, captured = live_reader.read()
                else:
                    success, frame = cap.read()
                    captured = time.time()
                if not success:
                    with self.lock:
                        self.state = 'finished' if self.source_kind == 'test' else live_reader.connection_state
                        self.error = None if self.source_kind == 'test' else '카메라 영상 수신이 끊겼습니다.'
                    if live_reader is None or not live_reader.thread.is_alive():
                        break
                    continue
                if live_reader is not None and last_generation != live_reader.generation:
                    local_tracker = LocalBoTSORT()
                    # A reconnect starts a fresh local identity/violation clock.
                    recorder = EventRecorder(f'{source_id}:{live_reader.generation}', self.model_path.name,
                                             self.source_name, camera_name=self.camera_name,camera_id=self.camera_id)
                    last_generation = live_reader.generation
                max_width = int(os.getenv('CAPTURE_MAX_WIDTH', '1280'))
                if frame.shape[1] > max_width:
                    frame = cv2.resize(frame, (max_width,round(frame.shape[0]*max_width/frame.shape[1])))
                result, wait_ms, inference_ms = self.engine.predict(frame)
                detections = local_tracker.detections(result, frame)
                video_seconds = frame_id / fps if self.source_kind == 'test' else started - origin
                tracks = recorder.tracker.update(detections, frame_id, video_seconds)
                association = associate_people(detections)
                people = [detections[p['detection_index']] for p in association['person_safety']]
                violations = {str(detections[p['detection_index']]['track_id']):p['violations']
                              for p in association['person_safety']}
                identities = {}
                if self.global_tracker:
                    vectors = self.global_tracker.encoder.encode(frame, people)
                    # RTP time aligns this stream's frames but is not a trusted
                    # capture clock shared between phones. Cross-camera matching
                    # is disabled unless clock bounds were independently verified.
                    if self.adapter=='mediamtx' and os.getenv('PUSH_CAPTURE_CLOCK_VERIFIED','false').lower()!='true':
                        vectors=[None]*len(people)
                    identities = self.global_tracker.observe(self.camera_id,
                        f'{source_id if self.source_kind == "test" else self.recording_id}:{last_generation}',
                        people, captured, vectors, violations)
                for person in association['person_safety']:
                    detection = detections[person['detection_index']]
                    person.update(bbox=detection['bbox'], local_track_id=detection['track_id'],
                                  **identities.get(str(detection['track_id']), {}))
                recorder.record(detections, frame_id, video_seconds,
                    datetime.fromtimestamp(captured, timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z'),
                    tracks=tracks, identities=identities)
                # Encode the original pixels once. Labels are synchronized metadata.
                encode_started = time.perf_counter()
                ok, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                if not ok:
                    raise RuntimeError('녹화 프레임 인코딩 실패')
                jpeg = buffer.tobytes()
                meta = {'recording_id': self.recording_id, 'frame_id': frame_id,
                    'timestamp': captured, 'captured_at': datetime.fromtimestamp(captured, timezone.utc).isoformat(),
                    'video_seconds': video_seconds, 'camera_id':self.camera_id, 'camera_name': self.camera_name,
                    'source_kind': self.source_kind, 'source_name': self.source_name,
                    'detections': detections, 'annotation_mode':'text-metadata',
                    'width':frame.shape[1], 'height':frame.shape[0],
                    'media_clock':dict(live_reader.consumed_clock) if live_reader else {},
                    'source_generation':f'{self.recording_id}:{last_generation}',
                    'person_count': sum(d['class_name'] == 'Person' for d in detections),
                    **association,
                    'negative_detection_count': sum(d['class_name'] in ('NO-Hardhat', 'NO-Safety Vest') for d in detections)}
                with self.lock:
                    self.latest = meta, jpeg
                if captured - last_saved >= recording_interval or recorder.episode_keys:
                    try:
                        self.writer_queue.put_nowait((meta, jpeg, list(recorder.episode_keys)))
                    except Full:
                        self.storage_error = '녹화 처리 지연 · 저장 프레임 일부 누락'
                        self.metrics['recording_dropped'] = self.metrics.get('recording_dropped',0)+1
                    last_saved = captured
                elapsed = time.monotonic()-started
                self.metrics.update(inference_wait_ms=round(wait_ms,2), inference_ms=round(inference_ms,2),
                    jpeg_ms=round((time.perf_counter()-encode_started)*1000,2), jpeg_bytes=len(jpeg),
                    processing_ms=round(elapsed*1000,2), frame_age_ms=round((time.time()-captured)*1000,2),
                    analysis_fps=round((frame_id+1)/max(.001,time.monotonic()-origin),2))
                with self.lock:
                    self.state, self.updated_at, self.error = 'running', captured, None
                frame_id += 1
                if self.source_kind == 'test':
                    self.stop_event.wait(max(0, 1 / fps - (time.monotonic() - started)))
                else:
                    self.stop_event.wait(max(0,analysis_interval-elapsed))
        except Exception as exc:
            with self.lock:
                self.state = 'error'
                # Avoid returning camera URLs / credentials in exception text.
                self.error = ('모델 또는 시험 영상 파일을 찾을 수 없습니다. 서버 파일 설정을 확인하세요.'
                              if isinstance(exc, FileNotFoundError) else
                              '영상 저장에 실패했습니다. 디스크 여유 공간과 저장 폴더 권한을 확인하세요.'
                              if isinstance(exc, OSError) else
                              '영상 감지 또는 저장에 실패했습니다. 서버 로그와 소스 연결을 확인하세요.')
            import logging
            logging.getLogger(__name__).error('Monitor failed (%s)', type(exc).__name__)
        finally:
            if live_reader is not None:
                live_reader.close()
            elif cap is not None:
                cap.release()
            if self.writer and self.writer.is_alive():
                self.writer_queue.put(None)
                self.writer.join(timeout=10)
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
