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
    parser=argparse.ArgumentParser();parser.add_argument('--keep',action='store_true');args=parser.parse_args()
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
        'LOCAL_DEMO_ENABLED':'true','DATABASE_URL':'','SAFETY_DB_PATH':str(ROOT/'.local-run/demo/media-test-events.sqlite3'),
        'MONITOR_STORAGE_DIR':str(ROOT/'.local-run/demo/media-test-recordings'),
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
    result={'native_not_docker':True,'synthetic_not_phone':True}
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
        launch('backend',[sys.executable,'-m','uvicorn','media_fixture_app:app','--host','127.0.0.1','--port','18002','--no-proxy-headers','--no-access-log'])
        launch('frontend',['node',str(ROOT/'node_modules/vite/bin/vite.js'),'--host','127.0.0.1','--port','15173','--strictPort'])
        wait(lambda:http_ready('http://127.0.0.1:18002/health'),40)
        wait(lambda:http_ready('http://127.0.0.1:15173'))
        from playwright.sync_api import sync_playwright,expect
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True)
            page=browser.new_page(viewport={'width':1800,'height':1100})
            errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto('http://127.0.0.1:15173')
            page.get_by_role('button',name='로컬 데모로 대시보드 보기').click()
            page.wait_for_function("Array.from(document.querySelectorAll('.webrtc-video')).length===3 && Array.from(document.querySelectorAll('.webrtc-video')).every(v=>v.videoWidth>0)",timeout=45000)
            page.wait_for_function("Array.from(document.querySelectorAll('.webrtc-video')).every(v=>Number(v.dataset.alignedFrames)>2)",timeout=45000)
            result['three_webrtc_and_exact_rtp_overlay']=True
            page.wait_for_timeout(4000)
            result['display_metrics']=page.locator('.webrtc-metrics').all_text_contents()
            result['video_dimensions']=page.locator('.webrtc-video').evaluate_all('(items)=>items.map(v=>[v.videoWidth,v.videoHeight])')
            states=page.request.get('http://127.0.0.1:15173/api/cameras').json()
            result['analysis_metrics']=[{'camera_id':c['camera_id'],'metrics':c['metrics']} for c in states['cameras']]
            assert all(c['relay']['online'] for c in states['cameras'])
            before=page.locator('[data-camera-id="CAM-02"] video').evaluate('v=>v.currentTime')
            publishers[1].terminate();publishers[1].wait(timeout=5)
            page.wait_for_timeout(4000)
            after=page.locator('[data-camera-id="CAM-02"] video').evaluate('v=>v.currentTime')
            assert after>before
            publishers[1]=publish(1)
            page.wait_for_function("document.querySelector('[data-camera-id=\"CAM-01\"] video').videoWidth>0 && document.querySelector('[data-camera-id=\"CAM-01\"] video').currentTime>1",timeout=45000)
            result['publisher_restart_isolated']=True
            invalid=publish(1,path='cam02',password='invalid-test-password')
            page.wait_for_timeout(2000)
            assert invalid.poll() is not None
            result['invalid_publish_rejected']=True
            assert page.request.post('http://127.0.0.1:15173/api/monitor/stop?camera_id=CAM-02',headers={'origin':'http://127.0.0.1:15173'}).status==200
            before=page.locator('[data-camera-id="CAM-02"] video').evaluate('v=>v.currentTime')
            page.wait_for_timeout(2000)
            assert page.locator('[data-camera-id="CAM-02"] video').evaluate('v=>v.currentTime')>before
            result['video_continues_when_ai_stopped']=True
            page.screenshot(path=str(work/'three-channel-webrtc.png'),full_page=True)
            assert not errors,errors
            result['javascript_errors']=errors
            browser.close()
        result['success']=True
    except Exception as error:
        result['success']=False;result['failure_type']=type(error).__name__
        print('Integration failure:',type(error).__name__,'See private logs in',work.name)
    finally:
        if not args.keep:
            for child in reversed(children):
                if child.poll() is None:child.terminate()
            for child in reversed(children):
                try:child.wait(timeout=5)
                except subprocess.TimeoutExpired:child.kill()
        result['limitations']=['Synthetic FFmpeg sources and detector fixture; no trained YOLO or Larix hardware','Local CA TLS; no public DNS certificate or AWS test','Docker unavailable']
        output=ROOT/'docs/media-integration-result.json'
        output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(result,ensure_ascii=True,indent=2))
    if not result.get('success'):raise SystemExit(1)


if __name__=='__main__':main()
