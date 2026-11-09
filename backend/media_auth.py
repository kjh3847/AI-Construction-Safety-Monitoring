"""Internal MediaMTX HTTP authorization service. No public proxy route exposes it."""
import hmac
import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app=FastAPI(docs_url=None,redoc_url=None,openapi_url=None)
PATHS={'cam01','cam02','cam03'}


class MediaIdentity(BaseModel):
    user: str = Field(default='',max_length=128)
    password: str = Field(default='',max_length=512)
    action: str
    path: str = ''
    protocol: str = ''


def authorized(value):
    def matches(user_key,password_key,default_user):
        expected=os.getenv(password_key,'')
        return bool(expected) and hmac.compare_digest(value.user.encode(),os.getenv(user_key,default_user).encode()) and hmac.compare_digest(value.password.encode(),expected.encode())
    if value.path in PATHS:
        number=int(value.path[-2:])
        if value.action=='publish' and value.protocol=='rtmp':
            return matches(f'CAMERA_{number:02}_PUBLISH_USER',f'CAMERA_{number:02}_PUBLISH_PASSWORD',f'cam{number:02}_publisher')
        if value.action=='read' and value.protocol=='rtsp':
            return matches('MEDIA_AI_USER','MEDIA_AI_PASSWORD','ai_reader')
        if value.action=='read' and value.protocol=='webrtc':
            return matches('MEDIA_WEB_USER','MEDIA_WEB_PASSWORD','web_gateway')
    return value.action=='api' and matches('MEDIA_CONTROL_USER','MEDIA_CONTROL_PASSWORD','control')


@app.post('/auth')
def authorize(value: MediaIdentity):
    if not authorized(value):
        raise HTTPException(403,'Stream permission denied')
    return {}


@app.get('/health')
def health():return {'status':'ok'}
