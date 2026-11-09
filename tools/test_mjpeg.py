"""Real OpenCV/FFmpeg HTTP ingestion against three loopback phone simulators."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import sys
from threading import Thread
import time
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from live_capture import ReconnectingCapture
import cv2
import numpy as np


def run():
    available={1:False,2:True,3:True}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def do_GET(self):
            camera=int(self.headers['Host'].split(':')[0].rsplit('.',1)[1])
            if not available[camera]:
                self.send_error(503);return
            self.send_response(200)
            self.send_header('Content-Type','multipart/x-mixed-replace; boundary=frame')
            self.end_headers()
            image=np.full((120,160,3),camera*60,np.uint8)
            jpeg=cv2.imencode('.jpg',image)[1].tobytes()
            try:
                while available[camera]:
                    self.wfile.write(b'--frame\r\nContent-Type: image/jpeg\r\nContent-Length: '+str(len(jpeg)).encode()+b'\r\n\r\n'+jpeg+b'\r\n')
                    self.wfile.flush();time.sleep(.02)
            except (ConnectionError,OSError): pass
    server=ThreadingHTTPServer(('0.0.0.0',0),Handler)
    server.daemon_threads=True
    thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    readers=[]
    def wait_for(predicate,timeout=12):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            if predicate(): return
            time.sleep(.02)
        raise AssertionError('Timed out waiting for capture state')
    try:
        with patch.dict(os.environ,{'CAMERA_RECONNECT_INTERVAL':'.1'}):
            readers=[ReconnectingCapture(f'http://127.0.0.{n}:{server.server_port}/stream') for n in (1,2,3)]
            wait_for(lambda:readers[1].sequence>5 and readers[2].sequence>5)
            assert readers[0].sequence==0
            available[1]=True
            wait_for(lambda:readers[0].sequence>3)
            for number,reader in enumerate(readers,1):
                ok,frame,_=reader.read()
                assert ok and abs(float(frame.mean())-number*60)<2
            before=[r.sequence for r in readers]
            available[1]=False
            wait_for(lambda:readers[0].connection_state=='reconnecting')
            wait_for(lambda:readers[1].sequence>before[1]+5 and readers[2].sequence>before[2]+5)
            available[1]=True
            wait_for(lambda:readers[0].generation>=2 and readers[0].sequence>before[0]+2)
            print('PASS: three real MJPEG decoders; same port/different loopback IP; CAM-01 failure/recovery twice; CAM-02/03 continue')
            print('Measured capture FPS:',[r.stats()['capture_fps'] for r in readers])
    finally:
        available.update({1:False,2:False,3:False})
        for reader in readers: reader.close()
        server.shutdown();server.server_close();thread.join(timeout=2)
    assert all(not r.thread.is_alive() for r in readers)


if __name__=='__main__': run()
