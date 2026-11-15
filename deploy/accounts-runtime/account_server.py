"""Run with uvicorn account_server:app --host 0.0.0.0 --port 8000."""
import os
from urllib.parse import urlsplit
from contextlib import asynccontextmanager
import psycopg
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from identity import router
from identity_db import init_identity


@asynccontextmanager
async def lifespan(app):
    init_identity()
    yield


def origin_allowed(origin, configured):
    if not origin or not configured:
        return False
    if origin.rstrip('/') == configured.rstrip('/'):
        return True
    # Treat only loopback host spellings as equivalent, on the same scheme/port.
    # Production domains and arbitrary development ports remain restricted.
    try:
        actual, expected = urlsplit(origin), urlsplit(configured)
        loopback = {'localhost', '127.0.0.1', '::1'}
        return (actual.scheme == expected.scheme == 'http'
                and actual.hostname in loopback and expected.hostname in loopback
                and actual.port == expected.port
                and not actual.username and not actual.password
                and actual.path in ('', '/') and not actual.query and not actual.fragment)
    except ValueError:
        return False


def attach_identity(app):
    app.include_router(router)

    @app.middleware('http')
    async def check_origin(request: Request, call_next):
        if request.method in ('POST', 'PATCH', 'PUT', 'DELETE'):
            allowed = os.getenv('PUBLIC_APP_URL', '').rstrip('/')
            if not origin_allowed(request.headers.get('origin', ''), allowed):
                return JSONResponse({'detail': '허용되지 않은 요청 출처입니다.'}, status_code=403)
        return await call_next(request)

    @app.exception_handler(psycopg.Error)
    async def database_error(request, exc):
        return JSONResponse({'detail': '계정 DB에 연결하거나 저장하지 못했습니다.'}, status_code=503)


app = FastAPI(lifespan=lifespan)
attach_identity(app)


@app.get('/health')
def health():
    return {'status': 'ok'}
