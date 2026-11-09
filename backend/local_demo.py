"""Explicit loopback-only demo sessions, isolated from all production accounts."""
from contextlib import contextmanager
import hashlib
import ipaddress
import os
from pathlib import Path
import secrets
import sqlite3
import time
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response

ROOT = Path(__file__).resolve().parents[1]
COOKIE = 'safety_local_demo'
router = APIRouter(prefix='/api/auth')
USER = dict(employee_id='LOCAL_DEMO', email='demo@example.invalid', role='admin',
            status='active', must_change_password=False)


def validate_configuration():
    if os.getenv('LOCAL_DEMO_ENABLED', '').lower() != 'true':
        raise RuntimeError('Local demo must be explicitly enabled')
    if os.getenv('DATABASE_URL'):
        raise RuntimeError('Local demo refuses production account database settings')
    origin = urlsplit(os.getenv('PUBLIC_APP_URL', ''))
    if origin.scheme != 'http' or origin.hostname not in ('localhost', '127.0.0.1', '::1'):
        raise RuntimeError('Local demo requires a loopback HTTP origin')
    root = (ROOT/'.local-run'/'demo').resolve()
    for key in ('SAFETY_DB_PATH', 'MONITOR_STORAGE_DIR'):
        path = Path(os.getenv(key, '')).resolve()
        if not path.is_relative_to(root):
            raise RuntimeError('Local demo data must stay inside .local-run/demo')
    return root


def check_peer(request):
    try:
        local = request.client and ipaddress.ip_address(request.client.host).is_loopback
        host = urlsplit('http://' + request.headers.get('host', '')).hostname
    except ValueError:
        local, host = False, None
    if not local or host not in ('localhost', '127.0.0.1', '::1'):
        raise HTTPException(403, '로컬 데모는 이 PC에서만 사용할 수 있습니다.')


@contextmanager
def connection():
    root = validate_configuration()
    root.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(root/'sessions.sqlite3', timeout=5)
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def initialize():
    with connection() as conn:
        conn.execute('CREATE TABLE IF NOT EXISTS demo_sessions (token_hash TEXT PRIMARY KEY, expires_at REAL NOT NULL)')


def current_user(request: Request):
    check_peer(request)
    token = request.cookies.get(COOKIE, '')
    with connection() as conn:
        row = conn.execute('SELECT 1 FROM demo_sessions WHERE token_hash=? AND expires_at>?',
                           (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone()
    if row is None:
        raise HTTPException(401, '로컬 데모 버튼으로 접속하세요.')
    return dict(USER)


def monitor_user(user=Depends(current_user)):
    return user


@router.post('/local-demo')
def enter_demo(request: Request, response: Response):
    check_peer(request)
    token = secrets.token_urlsafe(32)
    with connection() as conn:
        conn.execute('DELETE FROM demo_sessions WHERE expires_at<=?', (time.time(),))
        conn.execute('INSERT INTO demo_sessions VALUES (?,?)',
                     (hashlib.sha256(token.encode()).hexdigest(), time.time()+3600))
    response.set_cookie(COOKIE, token, httponly=True, secure=False, samesite='strict', max_age=3600, path='/')
    return dict(USER)


@router.get('/me')
def me(user=Depends(current_user)):
    return user


@router.post('/logout')
def logout(request: Request, response: Response):
    check_peer(request)
    with connection() as conn:
        conn.execute('DELETE FROM demo_sessions WHERE token_hash=?',
                     (hashlib.sha256(request.cookies.get(COOKIE, '').encode()).hexdigest(),))
    response.delete_cookie(COOKIE, path='/')
    return {'message':'로컬 데모에서 로그아웃했습니다.'}


@router.post('/login')
@router.post('/password')
def production_account_unavailable():
    raise HTTPException(409, '현재 로컬 데모 모드입니다. 기존 계정 인증은 계정 DB 설정 후 사용할 수 있습니다.')
