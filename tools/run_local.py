"""Keep loopback frontend/backend processes running; stop only verified processes we own."""
import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
import urllib.request

from dotenv import dotenv_values
import psutil

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT/'.local-run'
MANIFEST = RUNTIME/'processes.json'


def owned_process(record):
    try:
        process = psutil.Process(record['pid'])
        if (abs(process.create_time()-record['created_at']) > .1
                or Path(process.cwd()).resolve() != ROOT.resolve()
                or process.cmdline() != record['command']):
            return None
        return process
    except (psutil.Error, KeyError, OSError):
        return None


def read_manifest():
    return json.loads(MANIFEST.read_text('utf-8')) if MANIFEST.exists() else {}


def stop_processes(state):
    for record in state.get('processes', []):
        process = owned_process(record)
        if process is None:
            continue
        children = process.children(recursive=True)
        for child in children:
            try:
                child.terminate()
            except psutil.Error:
                pass
        try:
            process.terminate()
        except psutil.Error:
            pass
        _, alive = psutil.wait_procs([process, *children],timeout=5)
        for remaining in alive:
            try:
                remaining.kill()
            except psutil.Error:
                pass


def free_port(preferred):
    for port in range(preferred, preferred+30):
        with socket.socket() as probe:
            try:
                probe.bind(('127.0.0.1',port))
                return port
            except OSError:
                continue
    raise RuntimeError('No free loopback port in the requested range')


def wait_http(url,processes):
    deadline=time.monotonic()+40
    while time.monotonic()<deadline:
        if any(owned_process(record) is None for record in processes):
            raise RuntimeError('A local server exited; see .local-run logs')
        try:
            with urllib.request.urlopen(url,timeout=1) as response:
                if response.status==200:
                    return
        except OSError:
            pass
        time.sleep(.2)
    raise RuntimeError('Local server readiness timed out; see .local-run logs')


def child_environment(mode,front_url,backend_url):
    env=dict(os.environ)
    if mode=='demo':
        configuration=ROOT/'.env.local-run'
        if not configuration.exists():
            configuration.write_text(
                '# Local demo only. Keep real credentials out of Git.\n'
                'CAMERA_01_SOURCE=\nCAMERA_02_SOURCE=\nCAMERA_03_SOURCE=\n'
                'MODEL_PATH=backend/best.pt\nREID_MODEL_PATH=models/osnet_x0_25.onnx\n'
                'ANALYSIS_FPS=5\nRECORDING_FPS=2\n',encoding='utf-8')
        values=dotenv_values(configuration)
        if values.get('DATABASE_URL'):
            raise RuntimeError('Use configured mode for PostgreSQL; demo refuses DATABASE_URL')
        for key in list(env):
            if key.startswith(('CAMERA_','BREVO_')) or key in ('DATABASE_URL','TEST_DATABASE_URL'):
                env.pop(key,None)
        env.update({key:value for key,value in values.items() if value is not None})
        data=RUNTIME/'demo'
        data.mkdir(parents=True,exist_ok=True)
        env.update(LOCAL_DEMO_ENABLED='true',SAFETY_DB_PATH=str(data/'events.sqlite3'),
                   MONITOR_STORAGE_DIR=str(data/'recordings'),MONITOR_AUTOSTART='false',
                   YOLO_CONFIG_DIR=str(data/'ultralytics'))
    else:
        values=dotenv_values(ROOT/'.env') if (ROOT/'.env').exists() else {}
        env.update({key:value for key,value in values.items() if value is not None})
        if not env.get('DATABASE_URL'):
            raise RuntimeError('DATABASE_URL is not configured; use demo mode to view the local dashboard')
        env['LOCAL_DEMO_ENABLED']='false'
    env.update(PUBLIC_APP_URL=front_url,COOKIE_SECURE='false',REID_PRELOAD='true',
               ACCOUNTS_API_URL=backend_url,MONITOR_API_URL=backend_url,
               PYTHONUTF8='1',PYTHONUNBUFFERED='1')
    env.pop('VITE_API_BASE_URL',None)
    return env


def show(state):
    print(json.dumps({key:state.get(key) for key in ('mode','frontend_url','backend_url')},indent=2))
    for record in state.get('processes',[]):
        print(f"{record['name']}: {'running' if owned_process(record) else 'stopped'} (PID {record['pid']})")


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['start','status','stop'],nargs='?',default='start')
    parser.add_argument('--mode',choices=['demo','configured'],default='demo')
    args=parser.parse_args()
    state=read_manifest()
    if args.action=='status':
        show(state);return
    if args.action=='stop':
        stop_processes(state)
        state['stopped_at']=time.time()
        if state.get('processes'):
            MANIFEST.write_text(json.dumps(state,indent=2),encoding='utf-8')
        print('Stopped verified local server processes. Data and settings were preserved.')
        return
    active=[record for record in state.get('processes',[]) if owned_process(record)]
    if active:
        if len(active)!=2:
            raise RuntimeError('One owned server is still running; inspect status or stop it before restarting')
        show(state);return
    node=shutil.which('node')
    if not node or not (ROOT/'node_modules/vite/bin/vite.js').exists():
        raise RuntimeError('Node/Vite is missing; install project dependencies first')
    RUNTIME.mkdir(parents=True,exist_ok=True)
    frontend_port,backend_port=free_port(5173),free_port(8002)
    front_url=f'http://127.0.0.1:{frontend_port}'
    backend_url=f'http://127.0.0.1:{backend_port}'
    env=child_environment(args.mode,front_url,backend_url)
    state=dict(mode=args.mode,frontend_url=front_url,backend_url=backend_url,processes=[])
    commands=[('backend',[sys.executable,'-m','uvicorn','main:app','--app-dir','backend',
                          '--host','127.0.0.1','--port',str(backend_port),'--workers','1','--no-proxy-headers']),
              ('frontend',[node,str(ROOT/'node_modules/vite/bin/vite.js'),'--host','127.0.0.1',
                           '--port',str(frontend_port),'--strictPort'])]
    try:
        for name,command in commands:
            flags=(subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW) if os.name=='nt' else 0
            with (RUNTIME/f'{name}.log').open('ab') as log:
                child=subprocess.Popen(command,cwd=ROOT,env=env,stdin=subprocess.DEVNULL,
                    stdout=log,stderr=log,creationflags=flags,start_new_session=os.name!='nt')
            process=psutil.Process(child.pid)
            state['processes'].append(dict(name=name,pid=child.pid,created_at=process.create_time(),command=command))
        MANIFEST.write_text(json.dumps(state,indent=2),encoding='utf-8')
        wait_http(backend_url+'/health',state['processes'])
        wait_http(front_url,state['processes'])
        wait_http(front_url+'/api/runtime',state['processes'])
    except Exception:
        stop_processes(state)
        raise
    show(state)
    print('Local demo: select the explicitly labeled demo button on the login page. No password is required.')
    print('Stop: .\\.venv\\Scripts\\python.exe tools/run_local.py stop')


if __name__=='__main__':
    try:
        main()
    except (RuntimeError,OSError,ValueError) as error:
        raise SystemExit(str(error)) from None
