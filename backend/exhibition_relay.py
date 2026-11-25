"""Browser publishing and short-lived, non-recorded visitor sessions."""
import asyncio
import os
import secrets
import time
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException

from media_gateway import MediaGateway


class ExhibitionRelay(MediaGateway):
    def __init__(self):
        super().__init__()
        self.publishers = {}
        self.on_live = None

    def session_valid(self, token_hash):
        return True

    def cookie_hash(self, request):
        return request.cookies.get('exhibition_viewer', '')[:64]

    def status(self, camera):
        return {**super().status(camera), 'reserved': camera in self.publishers}

    async def publish(self, camera, offer):
        path = self.path(camera)
        if not self.available:
            raise HTTPException(503, '카메라 중계 서버를 준비 중입니다.')
        if camera in self.publishers or self.paths[camera]['online']:
            raise HTTPException(409, '이미 사용 중인 체험 채널입니다.')
        token = secrets.token_urlsafe(24)
        session = {'token': token, 'expires': time.monotonic() + 30, 'url': None, 'seen_online': False}
        self.publishers[camera] = session
        try:
            async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
                reply = await client.post(self.base + f'/{path}/whip', content=offer,
                    auth=self.auth('web'), headers={'Content-Type': 'application/sdp'})
            if reply.status_code != 201:
                raise HTTPException(502, '카메라 연결에 실패했습니다. 다시 시도하세요.')
            location = urlsplit(reply.headers.get('location', '')).path
            if not location.startswith(f'/{path}/whip/') or '..' in location:
                raise HTTPException(502, '중계 서버의 응답을 확인할 수 없습니다.')
            session.update(url=self.base + location, expires=time.monotonic() + 18)
            return token, reply.content
        except httpx.HTTPError:
            self.publishers.pop(camera, None)
            raise HTTPException(503, '카메라 중계 서버에 연결할 수 없습니다.') from None
        except (Exception, asyncio.CancelledError):
            self.publishers.pop(camera, None)
            raise

    def refresh_publisher(self, camera, token):
        session = self.publishers.get(camera)
        if not session or session.get('closed') or not secrets.compare_digest(session['token'], token):
            raise HTTPException(404, '체험 연결이 종료되었습니다.')
        session['expires'] = time.monotonic() + 18

    async def stop_publisher(self, camera, token):
        session = self.publishers.get(camera)
        if session and secrets.compare_digest(session['token'], token):
            session['closed'] = True
            await self.clear_publisher(camera, session)

    async def clear_publisher(self, camera, session):
        if session['url']:
            try:
                async with httpx.AsyncClient(timeout=2, trust_env=False) as client:
                    reply = await client.delete(session['url'], auth=self.auth('web'))
                if not (reply.is_success or reply.status_code in (404, 410)):
                    return
            except httpx.HTTPError:
                return
        if self.publishers.get(camera) is session:
            self.publishers.pop(camera)

    async def maintain_publishers(self):
        if self.on_live:
            for camera, status in self.paths.items():
                session = self.publishers.get(camera)
                self.on_live(camera, bool(session and not session.get('closed') and status['online']))
        for camera, session in list(self.publishers.items()):
            online = self.paths[camera]['online']
            if online:
                session['seen_online'] = True
            if not session['url']:
                continue
            disconnected = self.available and session['seen_online'] and not online
            if disconnected or session.get('closed') or session['expires'] <= time.monotonic():
                session['closed'] = True
                await self.clear_publisher(camera, session)

    async def close(self):
        await super().close()
        await asyncio.gather(*(self.clear_publisher(camera, session)
                               for camera, session in list(self.publishers.items())),
                             return_exceptions=True)
