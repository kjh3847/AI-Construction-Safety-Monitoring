from pathlib import Path
import os
import json
import asyncio
from datetime import date
from contextlib import asynccontextmanager
from threading import RLock

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from ultralytics import YOLO

from database import (init_db, get_events, event_summary, review_event, get_event,
                      today_event_count, retention_seconds)
from monitor import Monitor, frame_payload


@asynccontextmanager
async def lifespan(app):
    init_db()
    for source in monitors().values():
        source.initialize(retention_seconds())
    try:
        yield
    finally:
        for source in monitors().values():
            source.shutdown()


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r'http://(localhost|127\.0\.0\.1)(:\d+)?',
    allow_methods=['GET', 'PATCH', 'POST'], allow_headers=['Content-Type'],
)

# main.py와 같은 폴더에 있는 파일 사용
BASE_DIR = Path(__file__).resolve().parent
MODEL_PATH = BASE_DIR / "best.pt"
VIDEO_PATH = BASE_DIR / "test.mp4"

# 학습된 모델 불러오기
model = YOLO(str(MODEL_PATH))

recording_root = Path(os.getenv('MONITOR_STORAGE_DIR') or BASE_DIR / 'recordings')
inference_lock = RLock()
monitor = Monitor(model, MODEL_PATH, VIDEO_PATH, recording_root, inference_lock=inference_lock)
monitor2 = Monitor(model, MODEL_PATH, BASE_DIR / 'test2.mp4', recording_root / 'CAM-02',
                   camera_name='CAM-02', use_camera_env=False, inference_lock=inference_lock)


def monitors():
    return {'CAM-01': monitor, 'CAM-02': monitor2}


def select_monitor(camera_id):
    source = monitors().get(camera_id)
    if source is None:
        raise HTTPException(404, '존재하지 않는 영상입니다.')
    return source


def event_source(row):
    return next(((key, source) for key, source in monitors().items()
                 if source.camera_name == row['camera_name']), (None, None))


@app.get('/api/events')
def events(limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0),
           day: date | None = None, event_type: str | None = None,
           review_status: str | None = Query(None, pattern='^(pending|reviewed)$'), camera_id: str | None = None):
    camera_name = select_monitor(camera_id).camera_name if camera_id is not None else None
    rows = get_events(limit, offset, day, event_type, review_status, camera_name)
    return {'events': [event_payload(row) for row in rows],
            'summary': {**event_summary(), 'today': today_event_count()}}


def event_payload(row):
    row = {**row, 'violation_types': json.loads(row.get('violation_types') or 'null') or [row['event_type']]}
    camera_id, source = event_source(row)
    if source is None:
        return {**row, 'camera_id': None, 'snapshot_url': None, 'playable': False}
    source.store.prune()
    snapshot = source.snapshots / Path(row['snapshot_path'] or '').name
    return {**row, 'camera_id': camera_id, 'snapshot_url': f"/api/events/{row['id']}/snapshot" if row['snapshot_path'] and snapshot.is_file() else None,
            'playable': source.store.contains(row['recording_id'], row['frame_id'])}


@app.get('/api/events/{event_id}')
def event_detail(event_id: int):
    row = get_event(event_id)
    if row is None:
        raise HTTPException(404, '이벤트 없음')
    return event_payload(row)


@app.get('/api/events/{event_id}/snapshot')
def event_snapshot(event_id: int):
    row = get_event(event_id)
    if not row or not row['snapshot_path']:
        raise HTTPException(404, '스냅샷 없음')
    _, source = event_source(row)
    if source is None:
        raise HTTPException(404, '연결된 영상 소스 없음')
    path = source.snapshots / Path(row['snapshot_path']).name
    if not path.is_file():
        raise HTTPException(404, '스냅샷 보관 기간 만료 또는 이미지 없음')
    return FileResponse(path, media_type='image/jpeg')


@app.patch('/api/events/{event_id}')
def review(event_id: int):
    event = review_event(event_id)
    if event is None:
        raise HTTPException(404, 'Event not found')
    return event


@app.get('/api/status')
def status(camera_id: str = 'CAM-01'):
    return {**select_monitor(camera_id).status(), 'camera_id': camera_id}


@app.post('/api/monitor/start')
def start_monitor(camera_id: str = 'CAM-01'):
    source = select_monitor(camera_id)
    source.start()
    return {**source.status(), 'camera_id': camera_id}


@app.post('/api/monitor/stop')
def stop_monitor(camera_id: str = 'CAM-01'):
    source = select_monitor(camera_id)
    source.stop()
    return {**source.status(), 'camera_id': camera_id}


class RecordingSettings(BaseModel):
    retention_seconds: int = Field(ge=30, le=1800)


@app.patch('/api/settings')
def settings(value: RecordingSettings):
    saved = retention_seconds(value.retention_seconds)
    for source in monitors().values():
        source.store.retention = saved
        source.store.prune()
    return monitor.store.bounds()


@app.get('/api/recordings/frame')
def recording_frame(at: float | None = Query(None, allow_inf_nan=False),
                    recording_id: str | None = None, frame_id: int | None = None, camera_id: str = 'CAM-01'):
    frame = select_monitor(camera_id).store.get(at=at, recording_id=recording_id, frame_id=frame_id)
    if frame is None:
        raise HTTPException(410, '재생 가능한 영상 없음: 저장 범위를 확인하세요.')
    return frame_payload(frame)


@app.get("/")
def home():
    return {"message": "YOLO 분석 서버 실행 중"}


@app.get('/video')
def video(camera_id: str = 'CAM-01'):
    source = select_monitor(camera_id)
    # Compatibility only: a viewer never starts or stops inference.
    async def frames():
        previous = None
        while True:
            frame = await run_in_threadpool(source.store.get)
            if frame:
                meta, jpeg = frame
                key = (meta['recording_id'], meta['frame_id'])
                if key != previous:
                    previous = key
                    yield b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + jpeg + b'\r\n'
            await asyncio.sleep(.2)
    return StreamingResponse(frames(), media_type='multipart/x-mixed-replace; boundary=frame',
                             headers={'Cache-Control': 'no-store'})
