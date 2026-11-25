from pathlib import Path
from functools import lru_cache
from uuid import UUID
import os
import secrets
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
from exhibition_relay import ExhibitionRelay
from video_upload import TestVideoUpload, CHUNK_BYTES, MAX_VIDEO_BYTES

EXHIBITION = os.getenv('EXHIBITION_ENABLED', '').lower() == 'true'
INTERACTIVE = EXHIBITION and os.getenv('EXHIBITION_INTERACTIVE', '').lower() == 'true'
EXHIBITION_KEY = os.getenv('EXHIBITION_OPERATOR_KEY', '')
LOCAL_DEMO = os.getenv('LOCAL_DEMO_ENABLED','').lower() == 'true'
if LOCAL_DEMO:
    from local_demo import validate_configuration, current_user, monitor_user
    from local_demo import initialize as init_identity
    validate_configuration()


if EXHIBITION:
    if LOCAL_DEMO or (not INTERACTIVE and len(EXHIBITION_KEY) < 32):
        raise RuntimeError('Exhibition requires its own runtime and an operator key of at least 32 characters.')

    def monitor_user():
        return None

    def require_operator(request: Request):
        supplied = request.headers.get('x-exhibition-key', '')
        if len(EXHIBITION_KEY) < 32 or not secrets.compare_digest(
                supplied.encode('utf-8'), EXHIBITION_KEY.encode('utf-8')):
            raise HTTPException(403, '전시 운영 키를 확인하세요.')
        return {'employee_id': 'exhibition-operator', 'role': 'admin'}
else:
    require_operator = monitor_user


@asynccontextmanager
async def lifespan(app):
    init_db()
    if not EXHIBITION:
        init_identity()
    global_tracker.initialize()
    await media_gateway.start()
    if os.getenv('REID_PRELOAD','false').lower() == 'true':
        await run_in_threadpool(global_tracker.encoder.encode,None,[])
    for source in monitors().values():
        source.initialize(retention_seconds())
        if source.ephemeral or source.camera_id in s3_monitors:
            continue
        if (os.getenv('MONITOR_AUTOSTART', 'false').lower() == 'true'
                and source.source is not None and (EXHIBITION or source.upload_path is None)):
            source.start()
    try:
        yield
    finally:
        await media_gateway.close()
        for source in monitors().values():
            source.shutdown()


app = FastAPI(lifespan=lifespan)
if not EXHIBITION:
    attach_identity(app,local_demo=LOCAL_DEMO)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv('PUBLIC_APP_URL', 'http://localhost:5173').rstrip('/')],
    allow_origin_regex=(r'http://(localhost|127\.0\.0\.1):' + str(urlsplit(os.getenv('PUBLIC_APP_URL','http://localhost:5173')).port)
                        if urlsplit(os.getenv('PUBLIC_APP_URL','http://localhost:5173')).hostname in ('localhost','127.0.0.1') else None),
    allow_credentials=True,
    allow_methods=['GET', 'PATCH', 'POST', 'DELETE', 'OPTIONS'], allow_headers=['Content-Type', 'X-Exhibition-Key'],
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
media_gateway = ExhibitionRelay() if INTERACTIVE else MediaGateway()
process_metrics = psutil.Process()

recording_root = Path(os.getenv('MONITOR_STORAGE_DIR') or BASE_DIR / 'recordings')
def make_monitor(config, root):
    return Monitor(model, MODEL_PATH, config['source'], root, camera_name=config['name'],
        camera_id=config['camera_id'], use_camera_env=False, engine=engine,
        global_tracker=None if INTERACTIVE else global_tracker, adapter=config.get('adapter','direct'),
        ephemeral=INTERACTIVE)


monitor = make_monitor(configs[0], recording_root)
monitor2 = make_monitor(configs[1], recording_root / 'CAM-02')
monitor3 = make_monitor(configs[2], recording_root / 'CAM-03')
live_monitors = {'CAM-01': monitor, 'CAM-02': monitor2, 'CAM-03': monitor3}
if INTERACTIVE:
    def set_live_camera(camera, online):
        source = live_monitors[camera]
        if online:
            source.start()
        elif not source.stop_event.is_set():
            source.stop()

    media_gateway.on_live = set_live_camera
if EXHIBITION and not INTERACTIVE:
    for source in live_monitors.values():
        if source.adapter == 'direct':
            source.load_saved_source(recording_root / f'{source.camera_id}.json')

test_monitors = {}
test_video_uploads = {}
upload_channels = () if INTERACTIVE else ('CAM-04', 'CAM-05') if EXHIBITION else ('CAM-04',)
for camera_id in upload_channels:
    root = recording_root / camera_id
    source = Monitor(model, MODEL_PATH, None, root, camera_name=camera_id,
                     camera_id=camera_id, use_camera_env=False, engine=engine,
                     upload_path=root / 'test-video.mp4', loop_upload=EXHIBITION)
    test_monitors[camera_id] = source
    test_video_uploads[camera_id] = TestVideoUpload(source)
s3_monitors = {}
if INTERACTIVE:
    for camera_id, label, filename in (
            ('CAM-04', '건설장비 착용', '착용.mp4'), ('CAM-05', '건설장비 미착용', '미착용.mp4')):
        s3_monitors[camera_id] = Monitor(model, MODEL_PATH, None, recording_root / camera_id,
            camera_name=label, camera_id=camera_id, use_camera_env=False, engine=engine,
            upload_path=Path(os.getenv('EXHIBITION_VIDEO_DIR', '/exhibition-videos')) / filename,
            loop_upload=True, smooth_file=True)

monitor4 = (s3_monitors if INTERACTIVE else test_monitors)['CAM-04']


def monitors():
    return {**live_monitors, **test_monitors, **s3_monitors}


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


@app.patch('/api/events/{event_id}', dependencies=[Depends(require_operator)])
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
    if EXHIBITION and not INTERACTIVE:
        sources = [source.source for source in live_monitors.values()]
        duplicates = {camera_id for camera_id, address in zip(live_monitors, sources)
                      if address is not None and sources.count(address) > 1}
    else:
        duplicates = {config['camera_id'] for config in configs if config['duplicate_source']}
    return {'cameras': [{**status(key), 'duplicate_source': key in duplicates} for key in monitors()],
            'reid_state':global_tracker.encoder.state,
            'service_metrics':{'cpu_percent':process_metrics.cpu_percent(),
                'rss_bytes':process_metrics.memory_info().rss,
                'disk_free_bytes':psutil.disk_usage(str(recording_root)).free}}


@app.post('/api/cameras/{camera_id}/upload')
async def upload_test_video(camera_id: str, request: Request, upload_id: UUID, offset: int = Query(ge=0),
                            total: int = Query(gt=0, le=MAX_VIDEO_BYTES), user=Depends(require_operator)):
    upload = test_video_uploads.get(camera_id)
    if upload is None:
        raise HTTPException(404, '영상을 올릴 수 있는 채널이 아닙니다.')
    if request.headers.get('content-type') != 'application/octet-stream':
        raise HTTPException(415, '영상 업로드 형식이 올바르지 않습니다.')
    if upload.monitor.status()['state'] in ('starting', 'running', 'stopping'):
        raise HTTPException(409, '테스트 감지 녹화를 종료한 후 업로드하세요.')
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > CHUNK_BYTES:
            raise HTTPException(413, '영상 조각이 너무 큽니다.')
        data.extend(chunk)
    result = await run_in_threadpool(upload.append, user['employee_id'], upload_id, offset, total, data)
    if EXHIBITION and result['ready']:
        upload.monitor.start()
    return result


if EXHIBITION:
    class CameraRegistration(BaseModel):
        url: str = Field(min_length=1, max_length=2048)


    @app.post('/api/exhibition/operator', dependencies=[Depends(require_operator)])
    def verify_operator():
        return {'enabled': True}


    @app.post('/api/cameras/{camera_id}/source', dependencies=[Depends(require_operator)])
    def register_camera(camera_id: str, registration: CameraRegistration):
        if INTERACTIVE:
            raise HTTPException(404, '전시 체험 카메라는 QR로 연결합니다.')
        source = live_monitors.get(camera_id)
        if source is None or source.adapter != 'direct':
            raise HTTPException(404, '주소로 등록할 수 있는 채널이 아닙니다.')
        address = registration.url.strip()
        try:
            parsed = urlsplit(address)
            if (parsed.scheme not in ('http', 'https', 'rtsp', 'rtsps')
                    or not parsed.hostname or parsed.fragment
                    or any(character.isspace() for character in address)):
                raise ValueError
            _ = parsed.port
        except ValueError:
            raise HTTPException(422, 'HTTP(S) 또는 RTSP(S) 스트림 주소를 입력하세요.') from None
        if not source.register_source(address):
            raise HTTPException(409, '카메라 감지녹화를 완전히 중단한 뒤 등록하세요.')
        return status(camera_id)


if INTERACTIVE:
    def require_exhibition_origin(request):
        if not origin_allowed(request.headers.get('origin', ''), os.getenv('PUBLIC_APP_URL', '')):
            raise HTTPException(403, '전시 페이지에서 이 기능을 사용하세요.')


    @lru_cache(maxsize=3)
    def qr_image(url):
        import cv2
        matrix = cv2.QRCodeEncoder_create().encode(url)
        bordered = cv2.copyMakeBorder(matrix, 4, 4, 4, 4, cv2.BORDER_CONSTANT, value=255)
        enlarged = cv2.resize(bordered, None, fx=6, fy=6, interpolation=cv2.INTER_NEAREST)
        success, image = cv2.imencode('.png', enlarged)
        if not success:
            raise RuntimeError('Could not render QR code')
        return image.tobytes()


    @app.get('/api/exhibition/qr/{camera_id}')
    def camera_qr(camera_id: str):
        if camera_id not in live_monitors:
            raise HTTPException(404)
        base = os.getenv('PUBLIC_APP_URL', '').rstrip('/')
        return Response(qr_image(f'{base}/exhibition/join/{camera_id}'), media_type='image/png',
                        headers={'Cache-Control': 'private, max-age=300'})


    @app.post('/api/exhibition/publish/{camera_id}')
    async def publish_camera(camera_id: str, request: Request):
        require_exhibition_origin(request)
        if request.headers.get('content-type', '').split(';')[0] != 'application/sdp':
            raise HTTPException(415, '카메라 연결 데이터 형식이 올바르지 않습니다.')
        offer = bytearray()
        async for chunk in request.stream():
            if len(offer) + len(chunk) > 128 * 1024:
                raise HTTPException(413, '카메라 연결 데이터가 너무 큽니다.')
            offer.extend(chunk)
        token, answer = await media_gateway.publish(camera_id, bytes(offer))
        return Response(answer, status_code=201, media_type='application/sdp', headers={
            'Cache-Control': 'no-store', 'Location': f'/api/exhibition/publish/{camera_id}/{token}'})


    @app.post('/api/exhibition/publish/{camera_id}/{token}', status_code=204)
    async def keep_camera(camera_id: str, token: str, request: Request):
        require_exhibition_origin(request)
        media_gateway.refresh_publisher(camera_id, token)
        return Response(status_code=204)


    @app.delete('/api/exhibition/publish/{camera_id}/{token}', status_code=204)
    async def end_camera(camera_id: str, token: str, request: Request):
        require_exhibition_origin(request)
        await media_gateway.stop_publisher(camera_id, token)
        return Response(status_code=204)


    @app.api_route('/api/exhibition/video/{camera_id}', methods=['GET', 'HEAD'])
    def exhibition_video(camera_id: str):
        source = s3_monitors.get(camera_id)
        if not source or not source.upload_path.is_file():
            raise HTTPException(404, '시연 영상이 아직 준비되지 않았습니다.')
        return FileResponse(source.upload_path, media_type='video/mp4',
                            headers={'Cache-Control': 'private, max-age=300'})


@app.get('/health')
def health():
    return {'status':'ok'}


@app.get('/api/runtime')
def runtime_info():
    return {'local_demo':LOCAL_DEMO, 'exhibition':EXHIBITION, 'interactive':INTERACTIVE,
            'account_backend':'disabled' if EXHIBITION else 'isolated-local-demo' if LOCAL_DEMO else 'postgresql',
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


if INTERACTIVE:
    def require_playback_control(request: Request, camera_id: str = 'CAM-01'):
        if camera_id in s3_monitors:
            require_exhibition_origin(request)
            return
        require_operator(request)
else:
    require_playback_control = require_operator


@app.post('/api/monitor/start', dependencies=[Depends(require_playback_control)])
def start_monitor(camera_id: str = 'CAM-01'):
    if camera_id == 'all':
        for source in monitors().values():
            if not source.ephemeral:
                source.start()
        return cameras_status()
    source = select_monitor(camera_id)
    if source.ephemeral:
        raise HTTPException(409, '이 채널은 휴대폰 연결 시 자동으로 시작합니다.')
    if camera_id in s3_monitors and not source.status()['configured']:
        raise HTTPException(409, 'S3 시연 영상이 아직 준비되지 않았습니다.')
    source.start()
    return status(camera_id)


@app.post('/api/monitor/stop', dependencies=[Depends(require_playback_control)])
def stop_monitor(camera_id: str = 'CAM-01'):
    if camera_id == 'all':
        for source in monitors().values():
            if not source.ephemeral:
                source.stop()
        return cameras_status()
    source = select_monitor(camera_id)
    if source.ephemeral:
        raise HTTPException(409, '이 채널은 휴대폰에서 종료합니다.')
    source.stop()
    return status(camera_id)


class RecordingSettings(BaseModel):
    retention_seconds: int = Field(ge=30, le=30 * 86400)


@app.patch('/api/settings', dependencies=[Depends(require_operator)])
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
def correct_identity(value: IdentityCorrection, user=Depends(require_operator)):
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
        if not EXHIBITION:
            user = await run_in_threadpool(current_user,socket)
            if user['must_change_password']:
                raise HTTPException(403)
        source = select_monitor(camera_id)
        if source.ephemeral and not socket.url.path.startswith('/api/metadata/'):
            raise HTTPException(404)
    except Exception:
        await socket.close(code=1008)
        return
    await socket.accept()
    previous, checked = None, time.monotonic()
    try:
        while True:
            if not EXHIBITION and time.monotonic()-checked > 30:
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
                    elif jpeg:await asyncio.wait_for(socket.send_bytes(struct.pack('!I',len(header))+header+jpeg),timeout=5)
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
