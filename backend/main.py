from pathlib import Path
import os
import json
import asyncio
import struct
import time
import psutil
from urllib.parse import urlsplit
from datetime import date
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Depends, WebSocket, WebSocketDisconnect, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from identity import monitor_user, current_user
from identity_db import init_identity
from account_server import attach_identity, origin_allowed
from camera_config import camera_configs
from inference import FairInference
from reid import GlobalTracker

from database import (init_db, get_events, event_summary, review_event, get_event,
                      today_event_count, retention_seconds)
from monitor import Monitor, frame_payload
from media_gateway import MediaGateway

LOCAL_DEMO = os.getenv('LOCAL_DEMO_ENABLED','').lower() == 'true'
if LOCAL_DEMO:
    from local_demo import validate_configuration, current_user, monitor_user
    from local_demo import initialize as init_identity
    validate_configuration()


@asynccontextmanager
async def lifespan(app):
    init_db()
    init_identity()
    global_tracker.initialize()
    await media_gateway.start()
    if os.getenv('REID_PRELOAD','false').lower() == 'true':
        await run_in_threadpool(global_tracker.encoder.encode,None,[])
    for source in monitors().values():
        source.initialize(retention_seconds())
        if os.getenv('MONITOR_AUTOSTART', 'false').lower() == 'true' and source.source is not None:
            source.start()
    try:
        yield
    finally:
        await media_gateway.close()
        for source in monitors().values():
            source.shutdown()


app = FastAPI(lifespan=lifespan)
attach_identity(app,local_demo=LOCAL_DEMO)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv('PUBLIC_APP_URL', 'http://localhost:5173').rstrip('/')],
    allow_origin_regex=(r'http://(localhost|127\.0\.0\.1):' + str(urlsplit(os.getenv('PUBLIC_APP_URL','http://localhost:5173')).port)
                        if urlsplit(os.getenv('PUBLIC_APP_URL','http://localhost:5173')).hostname in ('localhost','127.0.0.1') else None),
    allow_credentials=True,
    allow_methods=['GET', 'PATCH', 'POST', 'DELETE', 'OPTIONS'], allow_headers=['Content-Type'],
)

# main.py와 같은 폴더에 있는 파일 사용
BASE_DIR = Path(__file__).resolve().parent
MODEL_PATH = Path(os.getenv('MODEL_PATH') or BASE_DIR / 'best.pt')

class LazyYOLO:
    def __init__(self, path):
        self.path, self.loaded = path, None

    @property
    def names(self):
        return self.loaded.names if self.loaded else {}

    def predict(self, **kwargs):
        if self.loaded is None:
            if not self.path.is_file():
                raise FileNotFoundError('Configured detection model is missing')
            from ultralytics import YOLO
            self.loaded = YOLO(str(self.path))
        return self.loaded.predict(**kwargs)


model = LazyYOLO(MODEL_PATH)
engine = FairInference(model)
global_tracker = GlobalTracker()
configs = camera_configs(BASE_DIR)
media_gateway = MediaGateway()
process_metrics = psutil.Process()

recording_root = Path(os.getenv('MONITOR_STORAGE_DIR') or BASE_DIR / 'recordings')
def make_monitor(config, root):
    return Monitor(model, MODEL_PATH, config['source'], root, camera_name=config['name'],
        camera_id=config['camera_id'], use_camera_env=False, engine=engine, global_tracker=global_tracker,
        adapter=config.get('adapter','direct'))


monitor = make_monitor(configs[0], recording_root)
monitor2 = make_monitor(configs[1], recording_root / 'CAM-02')
monitor3 = make_monitor(configs[2], recording_root / 'CAM-03')


# 👇 생성된 3개의 카메라를 시스템 목록에 등록합니다.
def monitors():
    return {'CAM-01': monitor, 'CAM-02': monitor2, 'CAM-03': monitor3}


def select_monitor(camera_id):
    source = monitors().get(camera_id)
    if source is None:
        raise HTTPException(404, '존재하지 않는 영상입니다.')
    return source


def event_source(row):
    if row.get('camera_id') in monitors():
        return row['camera_id'],monitors()[row['camera_id']]
    return next(((key, source) for key, source in monitors().items()
                 if source.camera_name == row['camera_name']), (None, None))


@app.get('/api/events', dependencies=[Depends(monitor_user)])
def events(limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0),
           day: date | None = None, event_type: str | None = None,
           review_status: str | None = Query(None, pattern='^(pending|reviewed)$'), camera_id: str | None = None):
    camera_name = select_monitor(camera_id).camera_name if camera_id is not None else None
    rows = get_events(limit, offset, day, event_type, review_status, camera_name,camera_id)
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


@app.get('/api/events/{event_id}', dependencies=[Depends(monitor_user)])
def event_detail(event_id: int):
    row = get_event(event_id)
    if row is None:
        raise HTTPException(404, '이벤트 없음')
    return event_payload(row)


@app.get('/api/events/{event_id}/snapshot', dependencies=[Depends(monitor_user)])
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


@app.patch('/api/events/{event_id}', dependencies=[Depends(monitor_user)])
def review(event_id: int):
    event = review_event(event_id)
    if event is None:
        raise HTTPException(404, 'Event not found')
    return event


@app.get('/api/status', dependencies=[Depends(monitor_user)])
def status(camera_id: str = 'CAM-01'):
    source=select_monitor(camera_id)
    return {**source.status(), 'camera_id': camera_id,
            **({'relay':media_gateway.status(camera_id)} if source.adapter=='mediamtx' else {})}


@app.get('/api/cameras', dependencies=[Depends(monitor_user)])
def cameras_status():
    return {'cameras': [{**status(key),
                         'duplicate_source':configs[index]['duplicate_source']}
                        for index,(key,source) in enumerate(monitors().items())],
            'reid_state':global_tracker.encoder.state,
            'service_metrics':{'cpu_percent':process_metrics.cpu_percent(),
                'rss_bytes':process_metrics.memory_info().rss,
                'disk_free_bytes':psutil.disk_usage(str(recording_root)).free}}


@app.get('/health')
def health():
    return {'status':'ok'}


@app.get('/api/runtime')
def runtime_info():
    return {'local_demo':LOCAL_DEMO,
            'account_backend':'isolated-local-demo' if LOCAL_DEMO else 'postgresql',
            'yolo_state':'loaded' if model.loaded else 'not_loaded' if MODEL_PATH.is_file() else 'missing',
            'reid_state':global_tracker.encoder.state,'media_enabled':media_gateway.enabled}


@app.post('/api/media/{camera_id}/whep',dependencies=[Depends(monitor_user)])
async def whep_offer(camera_id: str,request: Request):
    sdp=await request.body()
    if len(sdp)>128*1024 or request.headers.get('content-type','').split(';')[0]!='application/sdp':
        raise HTTPException(400,'Invalid SDP offer')
    key,answer=await media_gateway.offer(camera_id,sdp,request)
    return Response(answer,status_code=201,media_type='application/sdp',headers={
        'Location':f'/api/media/sessions/{key}','Cache-Control':'no-store'})


@app.post('/api/media/sessions/{key}/keepalive',dependencies=[Depends(monitor_user)])
def whep_keepalive(key: str,request: Request):
    lease=media_gateway.owned(key,request);lease['expires']=time.monotonic()+60
    return {'status':'ok'}


@app.delete('/api/media/sessions/{key}',dependencies=[Depends(monitor_user)])
async def whep_delete(key: str,request: Request):
    media_gateway.owned(key,request)
    await media_gateway.delete(key)
    return Response(status_code=204)


@app.post('/api/monitor/start', dependencies=[Depends(monitor_user)])
def start_monitor(camera_id: str = 'CAM-01'):
    if camera_id == 'all':
        for source in monitors().values():
            source.start()
        return cameras_status()
    source = select_monitor(camera_id)
    source.start()
    return {**source.status(), 'camera_id': camera_id}


@app.post('/api/monitor/stop', dependencies=[Depends(monitor_user)])
def stop_monitor(camera_id: str = 'CAM-01'):
    if camera_id == 'all':
        for source in monitors().values():
            source.stop()
        return cameras_status()
    source = select_monitor(camera_id)
    source.stop()
    return {**source.status(), 'camera_id': camera_id}


class RecordingSettings(BaseModel):
    retention_seconds: int = Field(ge=30, le=30 * 86400)


@app.patch('/api/settings', dependencies=[Depends(monitor_user)])
def settings(value: RecordingSettings):
    saved = retention_seconds(value.retention_seconds)
    for source in monitors().values():
        source.store.retention = saved
        source.store.prune()
    return monitor.store.bounds()


@app.get('/api/recordings/frame', dependencies=[Depends(monitor_user)])
def recording_frame(at: float | None = Query(None, allow_inf_nan=False),
                    recording_id: str | None = None, frame_id: int | None = None, camera_id: str = 'CAM-01'):
    frame = select_monitor(camera_id).store.get(at=at, recording_id=recording_id, frame_id=frame_id)
    if frame is None:
        raise HTTPException(410, '재생 가능한 영상 없음: 저장 범위를 확인하세요.')
    return frame_payload(frame)


@app.get('/api/people', dependencies=[Depends(monitor_user)])
def people_history(global_id: str | None = None, limit: int = Query(100,ge=1,le=1000)):
    return {'tracklets':global_tracker.history(global_id,limit), 'reid_state':global_tracker.encoder.state}


class IdentityCorrection(BaseModel):
    tracklet_id: str = Field(min_length=1,max_length=200)
    global_person_id: str | None = Field(default=None,pattern=r'^P[A-F0-9]{16}$')
    reason: str = Field(min_length=3,max_length=500)


@app.patch('/api/people/correction')
def correct_identity(value: IdentityCorrection, user=Depends(monitor_user)):
    if user['role'] not in ('admin','system'):
        raise HTTPException(403,'관리자 권한이 필요합니다.')
    if len(value.reason.strip()) < 3:
        raise HTTPException(422,'수정 사유를 3자 이상 입력하세요.')
    try:
        return global_tracker.correct(value.tracklet_id,value.global_person_id,user['employee_id'],value.reason)
    except KeyError:
        raise HTTPException(404,'추적 기록 없음')


@app.websocket('/api/live/{camera_id}')
@app.websocket('/api/metadata/{camera_id}')
async def live_frames(socket: WebSocket, camera_id: str):
    if not origin_allowed(socket.headers.get('origin',''),os.getenv('PUBLIC_APP_URL','')):
        await socket.close(code=1008)
        return
    try:
        user = await run_in_threadpool(current_user,socket)
        if user['must_change_password']:
            raise HTTPException(403)
        source = select_monitor(camera_id)
    except Exception:
        await socket.close(code=1008)
        return
    await socket.accept()
    previous, checked = None, time.monotonic()
    try:
        while True:
            if time.monotonic()-checked > 30:
                user = await run_in_threadpool(current_user,socket)
                if user['must_change_password']:
                    break
                checked = time.monotonic()
            frame = source.latest_frame()
            if frame:
                meta,jpeg = frame
                key = meta['recording_id'],meta['frame_id']
                if key != previous:
                    header = json.dumps(meta,separators=(',',':')).encode('utf-8')
                    if getattr(socket,'url',None) and socket.url.path.startswith('/api/metadata/'):
                        await asyncio.wait_for(socket.send_text(header.decode('utf-8')),timeout=5)
                    else:await asyncio.wait_for(socket.send_bytes(struct.pack('!I',len(header))+header+jpeg),timeout=5)
                    previous = key
            # Also receive disconnects when an idle camera has no outgoing frames.
            try:
                message = await asyncio.wait_for(socket.receive(),timeout=.05)
                if message['type'] == 'websocket.disconnect':
                    return
            except asyncio.TimeoutError:
                pass
    except (WebSocketDisconnect, RuntimeError, asyncio.TimeoutError, HTTPException):
        pass
    finally:
        try:
            await socket.close()
        except (RuntimeError,WebSocketDisconnect):
            pass


@app.get("/", dependencies=[Depends(monitor_user)])
def home():
    return {"message": "YOLO 분석 서버 실행 중"}


@app.get('/video', dependencies=[Depends(monitor_user)])
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
