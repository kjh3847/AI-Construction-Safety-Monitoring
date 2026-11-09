import os
from pathlib import Path
import tempfile
from threading import Thread
import time
import unittest
from unittest.mock import patch

from camera_config import camera_configs, classify_source
from inference import FairInference
from live_capture import ReconnectingCapture
from monitor import Monitor


class CameraTests(unittest.TestCase):
    def test_source_types_and_no_network_file_operations(self):
        for source,kind in [('0','usb'),('http://camera.invalid/video','http'),
                            ('https://camera.invalid/video','https'),('rtsp://camera.invalid/live','rtsp'),
                            ('C:\\recordings\\demo.mp4','file'),('demo.mp4','file'),('','unconfigured')]:
            self.assertEqual(classify_source(source)[1],kind)
        with tempfile.TemporaryDirectory() as root:
            monitor = Monitor(None,'missing.pt','http://user:secret@camera.invalid/video',root,use_camera_env=False)
            self.assertIsNone(monitor.video_path)
            self.assertEqual(monitor.source_kind,'camera')
            self.assertNotIn('secret',str(monitor.status()))
            self.assertNotIn('camera.invalid',str(monitor.status()))

    def test_same_port_different_host_and_duplicate_address(self):
        with patch.dict(os.environ,{'CAMERA_01_SOURCE':'http://one.invalid:8080/video',
                'CAMERA_02_SOURCE':'http://two.invalid:8080/video',
                'CAMERA_03_SOURCE':'http://one.invalid:8080/video'},clear=True):
            with self.assertLogs('camera_config',level='WARNING') as log:
                config = camera_configs('.')
            self.assertEqual([c['duplicate_source'] for c in config],[False,False,True])
            self.assertNotIn('http',str(log.output))

    def test_capture_failure_isolation_recovery_latest_only_and_release(self):
        class Capture:
            def __init__(self,fail=False): self.fail,self.counter,self.released=fail,0,False
            def isOpened(self): return not self.fail
            def set(self,*args): pass
            def read(self):
                time.sleep(.002)
                self.counter+=1
                return True,self.counter
            def release(self): self.released=True
        captures=[]
        def opener(source):
            cap=Capture(fail=source==1 and sum(c.fail for c in captures)<2)
            captures.append(cap)
            return cap
        with patch.dict(os.environ,{'CAMERA_RECONNECT_INTERVAL':'.05'}):
            readers=[ReconnectingCapture(i,opener) for i in (1,2,3)]
            try:
                deadline=time.monotonic()+2
                while time.monotonic()<deadline and readers[0].generation==0: time.sleep(.01)
                for reader in readers:
                    ok,frame,timestamp=reader.read()
                    self.assertTrue(ok)
                    self.assertGreater(timestamp,0)
                self.assertGreaterEqual(readers[0].reconnect_count,2)
                self.assertEqual(readers[1].reconnect_count,0)
                before=readers[1].sequence
                time.sleep(.03)
                self.assertGreater(readers[1].read()[1],before)
            finally:
                for reader in readers: reader.close()
            self.assertTrue(all(c.released for c in captures))
            self.assertTrue(all(not r.thread.is_alive() for r in readers))

    def test_fifo_admission_without_starvation(self):
        engine=FairInference(None)
        entered=[]
        def worker(number):
            with engine.turn():
                entered.append(number)
        threads=[]
        with engine.turn():
            for number in range(3):
                thread=Thread(target=worker,args=(number,))
                threads.append(thread);thread.start()
                deadline=time.monotonic()+1
                while len(engine.queue)<number+1 and time.monotonic()<deadline: time.sleep(.001)
        for thread in threads: thread.join(timeout=1)
        self.assertEqual(entered,[0,1,2])
