"""Authenticated same-origin WHEP proxy, bounded viewer leases, private path telemetry."""
import asyncio
import hashlib
import os
import time
import uuid
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException

CAMERA_PATHS={f'CAM-{n:02}':f'cam{n:02}' for n in range(1,4)}


class MediaGateway:
    def __init__(self):
        self.enabled=os.getenv('MEDIA_ENABLED','false').lower()=='true'
        self.base=os.getenv('MEDIA_WEBRTC_URL','http://mediamtx:8889').rstrip('/')
        self.api=os.getenv('MEDIA_API_URL','http://mediamtx:9997').rstrip('/')
        self.paths={camera:dict(online=False,last_received=None,ready_time=None,bytes_received=0)
                    for camera in CAMERA_PATHS}
        self.leases={}
        self.task=None
        self.available=False

    def path(self,camera):
        if not self.enabled:raise HTTPException(404,'MediaMTX mode is disabled')
        if camera not in CAMERA_PATHS:raise HTTPException(404,'Unknown camera')
        return CAMERA_PATHS[camera]

    def auth(self,kind):
        prefix='MEDIA_CONTROL' if kind=='api' else 'MEDIA_WEB'
        password=os.getenv(prefix+'_PASSWORD','')
        if not password:raise HTTPException(503,'Media service credentials are not configured')
        return httpx.BasicAuth(os.getenv(prefix+'_USER','control' if kind=='api' else 'web_gateway'),password)

    def cookie_hash(self,request):
        name='safety_local_demo' if os.getenv('LOCAL_DEMO_ENABLED','').lower()=='true' else 'safety_session'
        return hashlib.sha256(request.cookies.get(name,'').encode()).hexdigest()

    def session_valid(self,token_hash):
        if os.getenv('LOCAL_DEMO_ENABLED','').lower()=='true':
            from local_demo import connection
            with connection() as conn:
                return conn.execute('SELECT 1 FROM demo_sessions WHERE token_hash=? AND expires_at>?',
                                    (token_hash,time.time())).fetchone() is not None
        from identity_db import connect
        with connect() as conn:
            return conn.execute('''SELECT a.* FROM accounts a JOIN account_sessions s USING(employee_id)
                WHERE s.token_hash=%s AND s.expires_at>now() AND a.status='active' AND a.must_change_password=FALSE''',
                (token_hash,)).fetchone() is not None

    async def start(self):
        if self.enabled:self.task=asyncio.create_task(self._watch())

    async def close(self):
        if self.task:
            self.task.cancel()
            try:await self.task
            except asyncio.CancelledError:pass
        await asyncio.gather(*(self.delete(key) for key in list(self.leases)),return_exceptions=True)

    async def _watch(self):
        while True:
            try:
                async with httpx.AsyncClient(timeout=2,trust_env=False) as client:
                    response=await client.get(self.api+'/v3/paths/list',auth=self.auth('api'))
                    response.raise_for_status()
                    items={item['name']:item for item in response.json().get('items',[])}
                for camera,path in CAMERA_PATHS.items():
                    old=self.paths[camera];item=items.get(path,{})
                    received=item.get('bytesReceived',0)
                    if item.get('ready') and received!=old['bytes_received']:old['last_received']=time.time()
                    old.update(online=bool(item.get('ready')),ready_time=item.get('readyTime'),bytes_received=received)
                self.available=True
            except (httpx.HTTPError,ValueError,KeyError,HTTPException):
                self.available=False
                for value in self.paths.values():value['online']=False
            for key,lease in list(self.leases.items()):
                try:valid=lease['expires']>time.monotonic() and await asyncio.to_thread(self.session_valid,lease['owner'])
                except Exception:valid=False
                if not valid:await self.delete(key)
            await asyncio.sleep(2)

    def status(self,camera):
        return {**self.paths[camera],'available':self.available,'transport':'webrtc',
                'test_source':os.getenv('MEDIA_TEST_SOURCE','false').lower()=='true',
                'capture_clock':'unsynchronized','whep_url':f'/api/media/{camera}/whep'}

    async def offer(self,camera,sdp,request):
        path=self.path(camera)
        owner=self.cookie_hash(request)
        if len(self.leases)>=256 or sum(lease['owner']==owner for lease in self.leases.values())>=12:
            raise HTTPException(429,'Too many live viewers')
        try:
            async with httpx.AsyncClient(timeout=10,trust_env=False) as client:
                upstream=await client.post(self.base+f'/{path}/whep',content=sdp,
                    headers={'Content-Type':'application/sdp'},auth=self.auth('web'))
            if upstream.status_code!=201:
                raise HTTPException(503,'카메라 송출 대기 또는 WebRTC 연결 실패')
            location=urlsplit(upstream.headers.get('location','')).path
            if not location.startswith(f'/{path}/whep/') or '..' in location:
                raise HTTPException(502,'Invalid media session response')
            key=uuid.uuid4().hex
            self.leases[key]=dict(owner=owner,url=self.base+location,expires=time.monotonic()+60,camera=camera)
            return key,upstream.content
        except httpx.HTTPError:
            raise HTTPException(503,'영상 서버에 연결할 수 없습니다.') from None

    def owned(self,key,request):
        lease=self.leases.get(key)
        if not lease or lease['owner']!=self.cookie_hash(request):raise HTTPException(404,'Media session not found')
        return lease

    async def delete(self,key):
        lease=self.leases.pop(key,None)
        if lease:
            try:
                async with httpx.AsyncClient(timeout=2,trust_env=False) as client:
                    await client.delete(lease['url'],auth=self.auth('web'))
            except httpx.HTTPError:pass
