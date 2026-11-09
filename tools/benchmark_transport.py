"""Repeatable synthetic microbenchmark; does not measure YOLO or ReID accuracy/FPS."""
import ast
import base64
from collections import deque
import gc
import json
from pathlib import Path
import platform
import re
import shutil
import statistics
import struct
import subprocess
import sys
import tempfile
from threading import RLock
import time
import tracemalloc

import cv2
import numpy as np
import psutil

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from frame_store import FrameStore
from database import DEFAULT_RETENTION_SECONDS


def timed(function,count=100):
    samples=[]
    for _ in range(count):
        start=time.perf_counter();function();samples.append((time.perf_counter()-start)*1000)
    return round(statistics.median(samples),4)


def run():
    source=subprocess.check_output(['git','show','HEAD:backend/monitor.py'],cwd=ROOT).decode('utf-8')
    original=next(n for n in ast.parse(source).body if isinstance(n,ast.ClassDef) and n.name=='FrameStore')
    namespace=dict(globals())
    exec(compile(ast.Module(body=[original],type_ignores=[]),'baseline_FrameStore','exec'),namespace)
    Legacy=namespace['FrameStore']
    rng=np.random.default_rng(42)
    image=rng.integers(0,256,(360,640,3),dtype=np.uint8)
    jpeg=cv2.imencode('.jpg',image,[cv2.IMWRITE_JPEG_QUALITY,80])[1].tobytes()
    meta={'camera_id':'CAM-01','recording_id':'a'*32,'frame_id':0,'timestamp':time.time(),
          'person_safety':[dict(bbox=[20,50,100,300],local_track_id=i,violations=[]) for i in range(12)]}
    def old_payload(): return json.dumps({**meta,'image':'data:image/jpeg;base64,'+base64.b64encode(jpeg).decode()}).encode()
    def new_payload():
        header=json.dumps(meta,separators=(',',':')).encode()
        return struct.pack('!I',len(header))+header+jpeg
    result={'environment':dict(os=platform.platform(),python=platform.python_version(),opencv=cv2.__version__,
        cpu=platform.processor(),logical_cpus=psutil.cpu_count()),'synthetic':True,
        'transport':dict(jpeg_bytes=len(jpeg),json_base64_bytes=len(old_payload()),binary_bytes=len(new_payload()),
            json_base64_median_ms=timed(old_payload),binary_median_ms=timed(new_payload))}
    with tempfile.TemporaryDirectory() as directory:
        root=Path(directory)
        small=cv2.imencode('.jpg',image[:36,:64])[1].tobytes()
        for number in range(1000):
            m={**meta,'frame_id':number,'timestamp':time.time()-100+number*.05}
            path=root/f"{'a'*32}_{number}"
            path.with_suffix('.jpg').write_bytes(small)
            path.with_suffix('.json').write_text(json.dumps(m),encoding='utf-8')
        gc.collect();tracemalloc.start()
        old=Legacy(root)
        old_peak=tracemalloc.get_traced_memory()[1];tracemalloc.stop()
        old_lookup=timed(lambda:old.get(recording_id='a'*32,frame_id=900))
        del old;gc.collect()
        # One-time import cost excluded from steady-state restart measurement.
        new=FrameStore(root)
        tracemalloc.start();new=FrameStore(root)
        new_peak=tracemalloc.get_traced_memory()[1];tracemalloc.stop()
        new_lookup=timed(lambda:new.get(recording_id='a'*32,frame_id=900))
        result['dvr_1000_frames']=dict(legacy_restart_python_peak_bytes=old_peak,indexed_restart_python_peak_bytes=new_peak,
            legacy_exact_lookup_median_ms=old_lookup,indexed_exact_lookup_median_ms=new_lookup)
    result['limitations']='No best.pt, phone network, GPU, OSNet weights, or 24h soak; no production FPS/accuracy claim.'
    output=ROOT/'docs'/'benchmark-synthetic.json'
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))


if __name__=='__main__': run()
