"""Built UI in Chromium with explicit synthetic API/video fixtures; no production DB."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import base64
import json
from pathlib import Path
import struct
from threading import Thread
import time
from urllib.parse import parse_qs, urlsplit

import cv2
import numpy as np
from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parents[1]


def run():
    class QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self,*args): pass
    server=ThreadingHTTPServer(('127.0.0.1',0),partial(QuietHandler,directory=str(ROOT/'dist')))
    thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    now=time.time()
    sockets={}
    posts=[]
    colors={'CAM-01':(40,40,180),'CAM-02':(40,180,40),'CAM-03':(180,40,40)}
    def frame(camera,number=0):
        image=np.full((360,640,3),colors[camera],np.uint8)
        image[250:300,250:300]=number*30
        jpeg=cv2.imencode('.jpg',image)[1].tobytes()
        meta=dict(camera_id=camera,camera_name=camera,recording_id=camera[-1]*32,frame_id=number,
            timestamp=now+number*.01,person_count=int(camera[-1]),noncompliant_person_count=1,
            negative_detection_count=1,unassigned_negative_count=0,video_seconds=number*.2,
            source_kind='camera',source_name='synthetic-browser-fixture',annotation_mode='text-metadata',
            person_safety=[dict(local_track_id=1,global_person_id='P0000000000000001',match_state='unconfirmed',
                bbox=[50,120,130,300],violations=['NO-Hardhat'])])
        return meta,jpeg
    def packet(camera,number=0):
        meta,jpeg=frame(camera,number)
        header=json.dumps(meta).encode()
        return struct.pack('!I',len(header))+header+jpeg
    def event():
        return dict(id=1,camera_id='CAM-02',camera_name='CAM-02',event_type='NO-Hardhat',
            review_status='pending',created_at='2026-11-10T00:00:00Z',confidence=.9,recording_id='2'*32,
            frame_id=0,person_count=2,event_person_count=1,playable=True,violation_types=['NO-Hardhat'])
    def route_api(route):
        parts=urlsplit(route.request.url); query=parse_qs(parts.query);path=parts.path
        if route.request.method=='POST':
            posts.append((path,query.get('camera_id',[''])[0]));data={}
        elif path=='/api/auth/me':
            data=dict(employee_id='BROWSER_TEST',role='admin',must_change_password=False)
        elif path in ('/api/cameras','/api/status'):
            statuses=[dict(camera_id=camera,camera_name=camera,configured=True,state='running',
                source_kind='camera',recording_id=camera[-1]*32,buffer=dict(start=now-60,end=now+60,retention_seconds=86400),
                metrics=dict(capture_fps=20,analysis_fps=5,frame_age_ms=30)) for camera in colors]
            data={'cameras':statuses,'reid_state':'disabled'} if path=='/api/cameras' else statuses[0]
        elif path=='/api/people': data={'tracklets':[],'reid_state':'disabled'}
        elif path=='/api/runtime': data={'local_demo':False,'yolo_state':'not_loaded','reid_state':'disabled'}
        elif path=='/api/events': data={'events':[event()],'summary':dict(pending=1,today=1)}
        elif path=='/api/events/1': data=event()
        elif path=='/api/recordings/frame':
            camera=query['camera_id'][0];meta,jpeg=frame(camera)
            data={**meta,'image':'data:image/jpeg;base64,'+base64.b64encode(jpeg).decode()}
        else: raise AssertionError(path)
        route.fulfill(json=data)
    errors=[]
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True)
            page=browser.new_page(viewport={'width':1800,'height':1100})
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.route('**/api/**',route_api)
            def connect(socket):
                camera=socket.url.rsplit('/',1)[-1];sockets[camera]=socket
                socket.send(packet(camera))
            page.route_web_socket('**/api/live/*',connect)
            page.goto(f'http://127.0.0.1:{server.server_port}')
            tiles=page.locator('.camera-tile')
            expect(tiles).to_have_count(3)
            for camera in colors:
                expect(page.locator(f'[data-camera-id="{camera}"] canvas')).to_be_visible()
                page.wait_for_function("id => document.querySelector(`[data-camera-id='${id}'] canvas`).width === 640",arg=camera)
            assert len(set(round(tile.bounding_box()['y']) for tile in tiles.all()))==1
            pixel="el => Array.from(el.getContext('2d').getImageData(270,270,1,1).data).slice(0,3)"
            first=tiles.nth(0);second=tiles.nth(1)
            first.get_by_role('button',name='화면 일시정지',exact=True).click()
            paused=first.locator('canvas').evaluate(pixel)
            sockets['CAM-01'].send(packet('CAM-01',5));sockets['CAM-02'].send(packet('CAM-02',5))
            page.wait_for_function("() => document.querySelector('[data-camera-id=\"CAM-02\"] canvas').getContext('2d').getImageData(270,270,1,1).data[0] > 100")
            assert first.locator('canvas').evaluate(pixel)==paused
            first.get_by_role('button',name='전체화면',exact=True).click()
            page.wait_for_function('document.fullscreenElement !== null')
            first.get_by_role('button',name='전체화면 종료',exact=True).click()
            page.wait_for_function('document.fullscreenElement === null')
            second.get_by_role('button',name='중단',exact=True).click()
            assert posts[-1]==('/api/monitor/stop','CAM-02')
            page.get_by_role('button',name='전체 감지·녹화 시작',exact=True).click()
            assert posts[-1]==('/api/monitor/start','all')
            page.locator('.event-open').first.click()
            page.get_by_role('button',name='해당 시점 영상 보기',exact=True).click()
            expect(second.get_by_text('일시정지 · 과거 화면',exact=True)).to_be_visible()
            expect(first.get_by_text('일시정지 · 과거 화면',exact=True)).to_be_visible()
            page.set_viewport_size({'width':600,'height':1000})
            assert page.locator('.multi-camera-grid').evaluate("el => getComputedStyle(el).gridTemplateColumns.split(' ').length")==1
            assert errors==[],errors
            browser.close()
        print('PASS: 3 simultaneous canvases; independent pause; fullscreen; individual/all controls; event -> CAM-02 DVR; responsive layout; no JS errors')
    finally:
        server.shutdown();server.server_close();thread.join(timeout=2)


if __name__=='__main__': run()
