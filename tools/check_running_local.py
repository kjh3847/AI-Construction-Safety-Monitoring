"""Browser checks against running local servers. No mocked routes or synthetic media."""
import argparse
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parents[1]


def run():
    parser=argparse.ArgumentParser()
    parser.add_argument('--url',default='http://127.0.0.1:5173')
    args=parser.parse_args()
    base=args.url.rstrip('/')
    if urlsplit(base).hostname not in ('127.0.0.1','localhost'):
        raise ValueError('This check only targets loopback demo servers')
    artifacts=ROOT/'.local-run'/'verification'
    artifacts.mkdir(parents=True,exist_ok=True)
    errors=[];console_errors=[];responses=[];requests=[];sockets=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        page=browser.new_page(viewport={'width':1600,'height':1100})
        page.on('pageerror',lambda error:errors.append(str(error)))
        def console(message):
            if message.type=='error':
                location=message.location.get('url','')
                if '/api/auth/me' in location and '401' in message.text:
                    return  # Expected initial unauthenticated session check.
                console_errors.append({'text':message.text,'url':location})
        page.on('console',console)
        page.on('request',lambda request:requests.append(request.url))
        page.on('response',lambda response:responses.append({'path':urlsplit(response.url).path,'status':response.status}))
        page.on('websocket',lambda socket:sockets.append(socket.url))
        page.goto(base,wait_until='networkidle')
        expect(page.get_by_role('heading',name='관리자 로그인')).to_be_visible()
        demo=page.get_by_role('button',name='로컬 데모로 대시보드 보기',exact=True)
        expect(demo).to_be_visible()
        page.screenshot(path=str(artifacts/'login.png'),full_page=True)
        demo.click()
        expect(page.get_by_role('heading',name='현장 모니터링',exact=True)).to_be_visible()
        tiles=page.locator('.camera-tile')
        expect(tiles).to_have_count(3)
        for camera in ('CAM-01','CAM-02','CAM-03'):
            tile=page.locator(f'[data-camera-id="{camera}"]')
            expect(tile.locator('.section-title')).to_contain_text('연결 안 됨')
            expect(tile.get_by_text('카메라 연결 안 됨',exact=True)).to_be_visible()
            expect(tile.get_by_role('button',name='감지·녹화 시작',exact=True)).to_be_disabled()
        boxes=[tile.bounding_box() for tile in tiles.all()]
        assert len({round(box['y']) for box in boxes})==1,'Desktop must show a three-column row'
        runtime=page.request.get(base+'/api/runtime').json()
        assert runtime['local_demo'] is True and runtime['reid_state']=='ready'
        camera_status=page.request.get(base+'/api/cameras').json()
        assert [c['camera_id'] for c in camera_status['cameras']]==['CAM-01','CAM-02','CAM-03']
        assert all(c['state']=='unconfigured' and c['configured'] is False for c in camera_status['cameras'])
        assert page.request.get(base+'/api/events').json()['events']==[]
        close_code=page.evaluate("""url => new Promise((resolve,reject) => {
          const socket=new WebSocket(url.replace('http:','ws:')+'/api/live/CAM-01');
          socket.onopen=()=>socket.close(1000); socket.onclose=event=>resolve(event.code);
          socket.onerror=()=>reject(new Error('Authenticated WebSocket failed'));
        })""",base)
        assert close_code==1000,close_code
        first=tiles.nth(0)
        first.get_by_role('button',name='전체화면',exact=True).click()
        page.wait_for_function('document.fullscreenElement !== null')
        assert page.evaluate("document.fullscreenElement.closest('.camera-tile').dataset.cameraId")=='CAM-01'
        first.get_by_role('button',name='전체화면 종료',exact=True).click()
        page.wait_for_function('document.fullscreenElement === null')
        expect(tiles).to_have_count(3)
        headers={'origin':base}
        controlled=page.request.post(base+'/api/monitor/stop?camera_id=CAM-02',headers=headers)
        assert controlled.status==200 and controlled.json()['camera_id']=='CAM-02'
        after=page.request.get(base+'/api/cameras').json()['cameras']
        assert all(c['state']=='unconfigured' and c['recording_id'] is None for c in after)
        page.get_by_role('button',name='전체 감지·녹화 시작',exact=True).click()
        page.get_by_role('button',name='전체 중단',exact=True).click()
        page.wait_for_timeout(2200)
        assert all(c['state']=='unconfigured' for c in page.request.get(base+'/api/cameras').json()['cameras'])
        page.locator('nav').get_by_role('button',name=re.compile('이벤트 이력')).click()
        expect(page.get_by_role('heading',name='이벤트 이력',exact=True)).to_be_visible()
        page.locator('nav').get_by_role('button',name=re.compile('설정')).click()
        expect(page.locator('.settings')).to_be_visible()
        page.locator('nav').get_by_role('button',name=re.compile('모니터링')).click()
        expect(tiles).to_have_count(3)
        page.screenshot(path=str(artifacts/'dashboard.png'),full_page=True)
        page.set_viewport_size({'width':600,'height':1000})
        assert page.locator('.multi-camera-grid').evaluate("el=>getComputedStyle(el).gridTemplateColumns.split(' ').length")==1
        assert errors==[],errors
        assert console_errors==[],console_errors
        assert all(urlsplit(url).hostname in ('127.0.0.1','localhost') for url in requests)
        assert all(r['status']<400 or (r['path']=='/api/auth/me' and r['status']==401) for r in responses),responses
        assert page.request.post(base+'/api/auth/logout',headers=headers).status==200
        assert page.request.get(base+'/api/events').status==401
        page.reload(wait_until='networkidle')
        expect(demo).to_be_visible()
        browser.close()
    result=dict(frontend=base,mode='isolated-local-demo',runtime=runtime,
        cameras=[{'camera_id':c['camera_id'],'state':c['state']} for c in camera_status['cameras']],
        checks=['real login screen','explicit demo session','authenticated real WebSocket handshake and clean close','three simultaneous disconnected camera tiles',
                'fullscreen enter/exit','per-camera API isolation','all-camera controls without input',
                'events/settings navigation','mobile layout','logout revokes API access'],
        javascript_errors=errors,console_errors=console_errors,websocket_connections=len(sockets),
        limitations=['No account PostgreSQL','No best.pt','No camera input or real detection overlays tested'])
    (artifacts/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=True,indent=2))


if __name__=='__main__': run()
