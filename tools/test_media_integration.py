"""Native Windows MediaMTX/RTMPS/WebRTC integration. No AWS and no real phone claims."""
import argparse
from datetime import datetime,timedelta,timezone
import ipaddress
import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import time
import traceback
import urllib.request
from urllib.parse import urlencode

from dotenv import dotenv_values
import yaml

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'));sys.path.insert(0,str(ROOT/'tools'))
from issue_stream_credentials import issue,private_write


def tls(directory):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes,serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'Safety local integration CA')])
    now=datetime.now(timezone.utc)
    ca=x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=1)).not_valid_after(now+timedelta(days=2)).add_extension(x509.BasicConstraints(ca=True,path_length=0),critical=True).add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()),False).add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()),False).add_extension(x509.KeyUsage(True,False,False,False,False,True,True,None,None),True).sign(key,hashes.SHA256())
    server_key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    cert=x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'localhost')])).issuer_name(name).public_key(server_key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=1)).not_valid_after(now+timedelta(days=1)).add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost'),x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]),critical=False).add_extension(x509.BasicConstraints(ca=False,path_length=None),True).add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()),False).add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]),False).sign(key,hashes.SHA256())
    directory.mkdir(parents=True,exist_ok=True)
    private_write(directory/'privkey.pem',server_key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()).decode())
    (directory/'fullchain.pem').write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (directory/'ca.pem').write_bytes(ca.public_bytes(serialization.Encoding.PEM))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--real-app',action='store_true',help='Run production main:app without the synthetic detector');args=parser.parse_args()
    for port in (18003,11936,18554,19997,18889,18189,18002,15173):
        with socket.socket() as probe:
            probe.bind(('127.0.0.1',port))
    work=ROOT/'.local-run'/'media-integration'
    if work.exists():
        work=ROOT/'.local-run'/('media-integration-'+str(int(time.time())))
    work.mkdir(parents=True)
    tls(work/'tls')
    credentials=issue('localhost',11936,work/'secrets.env',work/'phones.json')
    config=yaml.safe_load((ROOT/'deploy/mediamtx.yml').read_text('utf-8'))
    config.update(logLevel='info',apiAddress='127.0.0.1:19997',rtspAddress='127.0.0.1:18554',
        rtmpsAddress='127.0.0.1:11936',webrtcAddress='127.0.0.1:18889',
        webrtcAdditionalHosts=['127.0.0.1'],webrtcLocalUDPAddress='127.0.0.1:18189',
        webrtcLocalTCPAddress='127.0.0.1:18189',authHTTPAddress='http://127.0.0.1:18003/auth',
        rtmpServerKey=str(work/'tls/privkey.pem'),rtmpServerCert=str(work/'tls/fullchain.pem'))
    (work/'mediamtx.yml').write_text(yaml.safe_dump(config),encoding='utf-8')
    env={**os.environ,**credentials,'PUBLIC_APP_URL':'http://127.0.0.1:15173','COOKIE_SECURE':'false',
        'LOCAL_DEMO_ENABLED':'true','DATABASE_URL':'','SAFETY_DB_PATH':str(ROOT/'.local-run/demo'/work.name/'events.sqlite3'),
        'MONITOR_STORAGE_DIR':str(ROOT/'.local-run/demo'/work.name/'recordings'),
        'MEDIA_ENABLED':'true','MEDIA_TEST_SOURCE':'true','MEDIA_RTSP_URL':'rtsp://127.0.0.1:18554',
        'MEDIA_API_URL':'http://127.0.0.1:19997','MEDIA_WEBRTC_URL':'http://127.0.0.1:18889',
        'REID_MODEL_PATH':str(ROOT/'models/osnet_x0_25.onnx'),'REID_PRELOAD':'true',
        'MONITOR_AUTOSTART':'true','CAMERA_RECONNECT_INTERVAL':'.5','ANALYSIS_FPS':'5','RECORDING_FPS':'2',
        'ACCOUNTS_API_URL':'http://127.0.0.1:18002','MONITOR_API_URL':'http://127.0.0.1:18002',
        'PYTHONPATH':str(ROOT/'backend')+os.pathsep+str(ROOT/'tools'),'PYTHONUTF8':'1'}
    env.pop('VITE_API_BASE_URL',None)
    children=[];publishers={}
    def launch(name,command):
        with (work/(name+'.log')).open('ab') as log:
            process=subprocess.Popen(command,cwd=ROOT,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=log,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        children.append(process);return process
    def wait(predicate,timeout=25):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            try:
                if predicate():return
            except Exception:pass
            time.sleep(.2)
        raise AssertionError('Integration readiness timed out; inspect private logs')
    def http_ready(url):
        with urllib.request.urlopen(url,timeout=1) as response:return response.status==200
    import imageio_ffmpeg
    ffmpeg=imageio_ffmpeg.get_ffmpeg_exe()
    def publish(number,path=None,password=None):
        user=credentials[f'CAMERA_{number:02}_PUBLISH_USER']
        password=password or credentials[f'CAMERA_{number:02}_PUBLISH_PASSWORD']
        target=f'rtmps://localhost:11936/{path or f"cam{number:02}"}?'+urlencode({'user':user,'pass':password})
        command=[ffmpeg,'-hide_banner','-loglevel','error','-re','-f','lavfi','-i',f'testsrc2=size=640x360:rate=15',
            '-vf',f'hue=h={number*80}','-an','-c:v','libx264','-preset','ultrafast','-tune','zerolatency',
            '-pix_fmt','yuv420p','-profile:v','baseline','-g','15','-bf','0','-tls_verify','1','-ca_file',str(work/'tls/ca.pem'),'-f','flv',target]
        return launch(f'publisher-{number}-{len(children)}',command)
    result={'native_not_docker':True,'synthetic_not_phone':True,'synthetic_detector':not args.real_app}
    def stage(name):
        result['stage']=name
        print('Stage:',name,flush=True)
    try:
        launch('auth',[sys.executable,'-m','uvicorn','media_auth:app','--host','127.0.0.1','--port','18003','--no-access-log'])
        wait(lambda:http_ready('http://127.0.0.1:18003/health'))
        result['stage']='auth_ready'
        media=launch('mediamtx',[str(ROOT/'.local-run/media-tools/mediamtx.exe'),str(work/'mediamtx.yml')])
        def tls_ready():
            try:
                context=ssl.create_default_context(cafile=str(work/'tls/ca.pem'))
                with context.wrap_socket(socket.create_connection(('127.0.0.1',11936),timeout=2),server_hostname='localhost') as stream:
                    result['tls_probe_version']=stream.version();return True
            except Exception as error:
                result['tls_probe_error']={'type':type(error).__name__,'verification':getattr(error,'verify_message',None)}
                return False
        wait(tls_ready);result['rtmps_certificate_verified']=True
        result.pop('tls_probe_error',None);result['stage']='tls_ready'
        for number in range(1,4):publishers[number]=publish(number)
        launch('backend',[sys.executable,'-m','uvicorn','main:app' if args.real_app else 'media_fixture_app:app','--host','127.0.0.1','--port','18002','--no-proxy-headers','--no-access-log'])
        node=ROOT/'.local-run/node-lts/node.exe'
        launch('frontend',[str(node) if node.is_file() else 'node',str(ROOT/'node_modules/vite/bin/vite.js'),'--host','127.0.0.1','--port','15173','--strictPort'])
        wait(lambda:http_ready('http://127.0.0.1:18002/health'),40)
        wait(lambda:http_ready('http://127.0.0.1:15173'))
        stage('services_ready')
        from playwright.sync_api import sync_playwright,expect
        with sync_playwright() as p:
            stage('browser_launch')
            browser=p.chromium.launch(headless=True,timeout=30000)
            page=browser.new_page(viewport={'width':1800,'height':1100})
            page.add_init_script("""window.__peers=[];const Native=window.RTCPeerConnection;
                window.RTCPeerConnection=class extends Native {constructor(...args){super(...args);window.__peers.push(this);}};""")
            def browser_log(line):
                with (work/'browser.log').open('a',encoding='utf-8') as log:log.write(line+'\n')
            page.on('console',lambda message:browser_log(message.type+': '+message.text))
            page.on('response',lambda response:browser_log(str(response.status)+' '+response.url) if '/api/media/' in response.url else None)
            errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            stage('login')
            page.goto('http://127.0.0.1:15173')
            page.get_by_role('button',name='로컬 데모로 대시보드 보기').click()
            stage('three_video_playback')
            try:
                page.wait_for_function("Array.from(document.querySelectorAll('.webrtc-video')).length===3 && Array.from(document.querySelectorAll('.webrtc-video')).every(v=>v.videoWidth>0)",timeout=45000)
            except Exception:
                browser_log(json.dumps(page.evaluate("window.__peers.map(p=>({connection:p.connectionState,ice:p.iceConnectionState,local:p.localDescription?.sdp,remote:p.remoteDescription?.sdp}))")))
                page.screenshot(path=str(work/'failure.png'),timeout=5000)
                raise
            result['three_webrtc_playback']=True
            if not args.real_app:
                stage('exact_rtp_overlay')
                page.wait_for_function("Array.from(document.querySelectorAll('.webrtc-video')).every(v=>Number(v.dataset.alignedFrames)>2)",timeout=45000)
                result['three_webrtc_and_exact_rtp_overlay']=True
            else:
                result['runtime']=page.request.get('http://127.0.0.1:15173/api/runtime').json()
                assert result['runtime']['yolo_state']=='missing','This scenario specifically checks absent trained weights'
                result['video_without_yolo_model']=True
            page.wait_for_timeout(11000)
            stage('controls_and_security')
            result['display_metrics']=page.locator('.webrtc-metrics').all_text_contents()
            result['video_dimensions']=page.locator('.webrtc-video').evaluate_all('(items)=>items.map(v=>[v.videoWidth,v.videoHeight])')
            states=page.request.get('http://127.0.0.1:15173/api/cameras').json()
            result['analysis_metrics']=[{'camera_id':c['camera_id'],'metrics':c['metrics']} for c in states['cameras']]
            assert all(c['relay']['online'] for c in states['cameras'])
            tile=page.locator('[data-camera-id="CAM-01"]')
            tile.get_by_role('button',name='화면 일시정지',exact=True).click()
            assert tile.locator('video').evaluate('v=>v.paused')
            tile.get_by_role('button',name='재생',exact=True).click()
            page.wait_for_function("!document.querySelector('[data-camera-id=\"CAM-01\"] video').paused")
            tile.get_by_role('button',name='전체화면',exact=True).click()
            page.wait_for_function('document.fullscreenElement !== null')
            page.evaluate('document.exitFullscreen()')
            result['pause_and_fullscreen']=True
            if not args.real_app:
                result['transport_comparison']=page.evaluate("""async()=>{
                    const peers=window.__peers.filter(p=>p.connectionState==='connected');
                    const stats=async()=>Promise.all(peers.map(async p=>[...(await p.getStats()).values()].find(s=>s.type==='inbound-rtp' && s.kind==='video')));
                    const first=await stats();let frames=0,bytes=0;
                    const socket=new WebSocket(location.origin.replace('http:','ws:')+'/api/live/CAM-01');socket.binaryType='arraybuffer';
                    socket.onmessage=e=>{frames++;bytes+=e.data.byteLength;};
                    const start=performance.now();await new Promise(r=>setTimeout(r,5000));socket.close();
                    const seconds=(performance.now()-start)/1000,last=await stats();
                    return {seconds,binary_cam01:{fps:frames/seconds,bytes_per_second:bytes/seconds},
                      webrtc:last.map((s,i)=>({fps:(s.framesDecoded-first[i].framesDecoded)/seconds,bytes_per_second:(s.bytesReceived-first[i].bytesReceived)/seconds,
                        jitter_buffer_ms:1000*s.jitterBufferDelay/s.jitterBufferEmittedCount}))};
                }""")
                assert result['transport_comparison']['binary_cam01']['fps']>0
                for metric in result['transport_comparison']['webrtc']:assert metric['fps']>10
                assert page.request.get('http://127.0.0.1:15173/api/events').json()['events']
                assert page.request.get('http://127.0.0.1:15173/api/recordings/frame?camera_id=CAM-01').status==200
                result['event_and_recording_saved']=True
            before=page.locator('[data-camera-id="CAM-02"] video').evaluate('v=>v.currentTime')
            old_ready=states['cameras'][0]['relay']['ready_time']
            publishers[1].terminate();publishers[1].wait(timeout=5)
            wait(lambda:not page.request.get('http://127.0.0.1:15173/api/cameras').json()['cameras'][0]['relay']['online'])
            after=page.locator('[data-camera-id="CAM-02"] video').evaluate('v=>v.currentTime')
            assert after>before
            publishers[1]=publish(1)
            wait(lambda:(lambda r:r['online'] and r['ready_time']!=old_ready)(page.request.get('http://127.0.0.1:15173/api/cameras').json()['cameras'][0]['relay']))
            page.wait_for_function("document.querySelector('[data-camera-id=\"CAM-01\"] video').videoWidth>0 && document.querySelector('[data-camera-id=\"CAM-01\"] video').currentTime>1",timeout=45000)
            result['publisher_restart_isolated']=True
            invalid=publish(1,path='cam02',password='invalid-test-password')
            wait(lambda:invalid.poll() is not None)
            assert invalid.returncode!=0
            result['invalid_publish_rejected']=True
            invalid_path=publish(1,path='cam02')
            wait(lambda:invalid_path.poll() is not None)
            assert invalid_path.returncode!=0
            result['valid_credentials_wrong_path_rejected']=True
            import httpx
            with httpx.Client(timeout=5,trust_env=False) as anonymous:
                assert anonymous.post('http://127.0.0.1:18002/api/media/CAM-01/whep',content='v=0\r\n',headers={'origin':'http://127.0.0.1:15173','content-type':'application/sdp'}).status_code==401
                assert anonymous.post('http://127.0.0.1:18889/cam01/whep',content='v=0\r\n',headers={'content-type':'application/sdp'}).status_code==401
            result['anonymous_gateway_and_direct_view_rejected']=True
            assert page.request.post('http://127.0.0.1:15173/api/monitor/stop?camera_id=CAM-02',headers={'origin':'http://127.0.0.1:15173'}).status==200
            before=page.locator('[data-camera-id="CAM-02"] video').evaluate('v=>v.currentTime')
            page.wait_for_timeout(2000)
            assert page.locator('[data-camera-id="CAM-02"] video').evaluate('v=>v.currentTime')>before
            result['video_continues_when_ai_stopped']=True
            page.screenshot(path=str(work/'three-channel-webrtc.png'),full_page=True)
            assert not errors,errors
            result['javascript_errors']=errors
            assert page.request.post('http://127.0.0.1:15173/api/auth/logout',headers={'origin':'http://127.0.0.1:15173'}).status==200
            def no_viewers():
                with httpx.Client(timeout=5,trust_env=False) as client:
                    response=client.get('http://127.0.0.1:19997/v3/webrtcsessions/list',auth=(credentials['MEDIA_CONTROL_USER'],credentials['MEDIA_CONTROL_PASSWORD']))
                    response.raise_for_status()
                    return len(response.json()['items'])==0
            wait(no_viewers,15)
            result['logout_revokes_active_media']=True
            browser.close()
        stage('complete')
        result['success']=True
    except Exception as error:
        result['success']=False;result['failure_type']=type(error).__name__
        # Tracebacks can contain request details. Keep diagnostics outside Git.
        (work/'failure.txt').write_text(traceback.format_exc(),encoding='utf-8')
        print('Integration failure:',type(error).__name__,'See private logs in',work.name)
    finally:
        if children:
            import psutil
            descendants=[]
            for child in children:
                if child.poll() is None:
                    try:descendants.extend(psutil.Process(child.pid).children(recursive=True))
                    except psutil.NoSuchProcess:pass
            for child in reversed(children):
                if child.poll() is None:child.terminate()
            for child in reversed(children):
                try:child.wait(timeout=5)
                except subprocess.TimeoutExpired:child.kill()
            for process in reversed(descendants):
                try:process.terminate()
                except psutil.NoSuchProcess:pass
            _,alive=psutil.wait_procs(descendants,timeout=5)
            for process in alive:
                try:process.kill()
                except psutil.NoSuchProcess:pass
        result['limitations']=['Synthetic FFmpeg sources; no trained YOLO or Larix hardware','Local CA TLS; no public DNS certificate or AWS test','Docker unavailable']
        output=ROOT/('docs/media-no-model-result.json' if args.real_app else 'docs/media-integration-result.json')
        output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(result,ensure_ascii=True,indent=2))
    if not result.get('success'):raise SystemExit(1)


if __name__=='__main__':main()
