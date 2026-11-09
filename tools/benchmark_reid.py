"""Real trained OSNet inference on synthetic crops. This is not person-match accuracy."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import sys
import time

import numpy as np
import psutil

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from reid import OSNetEncoder


def run():
    parser=argparse.ArgumentParser()
    parser.add_argument('models',nargs='+')
    args=parser.parse_args()
    result=[]
    for name in args.models:
        encoder=OSNetEncoder(path=name)
        image=np.random.default_rng(42).integers(0,256,(256,128,3),dtype=np.uint8)
        people=[{'bbox':[0,0,128,256],'confidence':.95}]
        started=time.perf_counter()
        vector=encoder.encode(image,people)[0]
        assert vector is not None and vector.shape==(512,) and abs(float(np.linalg.norm(vector))-1)<1e-5
        loading_ms=(time.perf_counter()-started)*1000
        for _ in range(3): encoder.encode(image,people)
        samples=[]
        process=psutil.Process()
        initial_cpu=sum(process.cpu_times()[:2])
        for _ in range(30):
            started=time.perf_counter();repeated=encoder.encode(image,people)[0]
            samples.append((time.perf_counter()-started)*1000)
            assert float(np.dot(vector,repeated))>.99999
        cpu_seconds=sum(process.cpu_times()[:2])-initial_cpu
        result.append(dict(model=Path(name).name,sha256=hashlib.sha256(Path(name).read_bytes()).hexdigest(),
            bytes=Path(name).stat().st_size,provider='CPUExecutionProvider',intra_op_threads=1,
            load_and_first_inference_ms=round(loading_ms,3),crop_inference_median_ms=round(statistics.median(samples),3),
            cpu_ms_per_crop=round(cpu_seconds*1000/30,3),process_rss_bytes=process.memory_info().rss,
            input='synthetic RGB texture; no real identity labels',shape=list(vector.shape)))
    output=ROOT/'docs'/'benchmark-reid.json'
    output.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))


if __name__=='__main__': run()
