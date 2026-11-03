import hashlib
import os
import secrets
import string
from datetime import datetime, timedelta, timezone

import httpx
import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field
from pwdlib import PasswordHash

from identity_db import connect

router = APIRouter(prefix='/api')
hasher = PasswordHash.recommended()
DUMMY_HASH = hasher.hash(secrets.token_urlsafe(32))
COOKIE = 'safety_session'


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def temporary_password():
    groups = [string.ascii_lowercase, string.ascii_uppercase, string.digits, '!@#$%&*?']
    chars = [secrets.choice(group) for group in groups]
    chars += [secrets.choice(''.join(groups)) for _ in range(7)]
    secrets.SystemRandom().shuffle(chars)
    return ''.join(chars)


def validate_password(value):
    if not (11 <= len(value) <= 128) or not all((any(c.islower() for c in value),
            any(c.isupper() for c in value), any(c.isdigit() for c in value),
            any(c in string.punctuation for c in value))):
        raise HTTPException(422, '비밀번호는 11~128자리이며 영문 대소문자·숫자·특수문자를 포함해야 합니다.')


def public(row):
    return {key: row[key] for key in ('employee_id', 'email', 'role', 'status', 'must_change_password')}


def current_user(request: Request):
    token = request.cookies.get(COOKIE, '')
    with connect() as db:
        row = db.execute('''SELECT a.* FROM accounts a JOIN account_sessions s USING(employee_id)
            WHERE s.token_hash=%s AND s.expires_at>now() AND a.status='active' ''',
            (digest(token),)).fetchone()
    if not row:
        raise HTTPException(401, '로그인이 필요합니다.')
    return row


def system_user(user=Depends(current_user)):
    if user['role'] != 'system' or user['must_change_password']:
        raise HTTPException(403, '시스템팀 권한이 필요합니다.')
    return user


def monitor_user(user=Depends(current_user)):
    if user['must_change_password']:
        raise HTTPException(403, '먼저 임시 비밀번호를 변경하세요.')
    return user


class Login(BaseModel):
    employee_id: str = Field(min_length=1, max_length=32, pattern=r'^[A-Za-z0-9_-]+$')
    password: str = Field(min_length=1, max_length=128)


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=11, max_length=128)
    confirm_password: str = Field(min_length=11, max_length=128)


class AccountInput(BaseModel):
    employee_id: str = Field(min_length=1, max_length=32, pattern=r'^[A-Za-z0-9_-]+$')
    email: EmailStr


class DisableInput(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


@router.post('/auth/login')
def login(value: Login, response: Response):
    authenticated = None
    with connect() as db:
        row = db.execute('SELECT * FROM accounts WHERE employee_id=%s FOR UPDATE',
                         (value.employee_id,)).fetchone()
        valid = hasher.verify(value.password, row['password_hash'] if row else DUMMY_HASH)
        now = datetime.now(timezone.utc)
        locked = row and row['locked_until'] and row['locked_until'] > now
        if row and valid and not locked and row['status'] == 'active':
            token = secrets.token_urlsafe(32)
            db.execute('UPDATE accounts SET failed_attempts=0, locked_until=NULL WHERE employee_id=%s', (value.employee_id,))
            db.execute('DELETE FROM account_sessions WHERE expires_at<=now()')
            db.execute('INSERT INTO account_sessions VALUES (%s,%s,%s)',
                       (digest(token), value.employee_id, now + timedelta(hours=8)))
            authenticated = public(row)
        elif row and not locked:
            failures = row['failed_attempts'] + 1
            db.execute('UPDATE accounts SET failed_attempts=%s, locked_until=%s WHERE employee_id=%s',
                       (0 if failures >= 5 else failures, now + timedelta(minutes=15) if failures >= 5 else None, value.employee_id))
    if not authenticated:
        raise HTTPException(401, '아이디 또는 비밀번호가 올바르지 않습니다.')
    response.set_cookie(COOKIE, token, httponly=True, secure=os.getenv('COOKIE_SECURE', 'true') == 'true',
                        samesite='strict', max_age=8*3600, path='/')
    return authenticated


@router.get('/auth/me')
def me(user=Depends(current_user)):
    return public(user)


@router.post('/auth/logout')
def logout(request: Request, response: Response):
    with connect() as db:
        db.execute('DELETE FROM account_sessions WHERE token_hash=%s', (digest(request.cookies.get(COOKIE, '')),))
    response.delete_cookie(COOKIE, path='/')
    return {'message': '로그아웃되었습니다.'}


@router.post('/auth/password')
def change_password(value: PasswordChange, response: Response, user=Depends(current_user)):
    validate_password(value.new_password)
    if value.new_password != value.confirm_password or value.new_password == value.current_password:
        raise HTTPException(422, '새 비밀번호 확인을 점검하세요. 현재 비밀번호와 달라야 합니다.')
    with connect() as db:
        row = db.execute('SELECT * FROM accounts WHERE employee_id=%s FOR UPDATE', (user['employee_id'],)).fetchone()
        if row['status'] != 'active' or not hasher.verify(value.current_password, row['password_hash']):
            raise HTTPException(400, '현재 비밀번호가 올바르지 않습니다.')
        db.execute('UPDATE accounts SET password_hash=%s, must_change_password=FALSE WHERE employee_id=%s',
                   (hasher.hash(value.new_password), user['employee_id']))
        db.execute('DELETE FROM account_sessions WHERE employee_id=%s', (user['employee_id'],))
        db.execute('INSERT INTO account_audit(actor,employee_id,action) VALUES (%s,%s,%s)',
                   (user['employee_id'], user['employee_id'], 'password_changed'))
    response.delete_cookie(COOKIE, path='/')
    return {'message': '비밀번호가 변경되었습니다. 다시 로그인하세요.'}


def deliver(employee_id):
    key, sender = os.getenv('BREVO_API_KEY'), os.getenv('BREVO_SENDER_EMAIL')
    if not key or not sender:
        raise HTTPException(503, '이메일 설정이 필요합니다. 계정은 발급 대기 상태입니다.')
    # Lock serializes reissues; only a hash is persisted. A timeout leaves the account pending.
    with connect() as db:
        row = db.execute('SELECT * FROM accounts WHERE employee_id=%s FOR UPDATE', (employee_id,)).fetchone()
        if not row or row['status'] != 'pending':
            raise HTTPException(409, '발급 대기 계정만 전송할 수 있습니다.')
        password = temporary_password()
        try:
            result = httpx.post('https://api.brevo.com/v3/smtp/email', timeout=15,
                headers={'api-key': key}, json={'sender': {'email': sender, 'name': '현장지킴'},
                'to': [{'email': row['email']}], 'subject': '현장지킴 관리자 계정 발급',
                'textContent': f"아이디: {employee_id}\n임시 비밀번호: {password}\n로그인: {os.getenv('PUBLIC_APP_URL', '')}\n최초 로그인 후 비밀번호를 변경하세요."})
            result.raise_for_status()
        except httpx.HTTPError:
            raise HTTPException(502, '이메일 전송을 확인하지 못했습니다. 계정은 발급 대기 상태입니다. 재전송하세요.') from None
        db.execute("UPDATE accounts SET password_hash=%s,status='active' WHERE employee_id=%s",
                   (hasher.hash(password), employee_id))
    return {'message': '계정이 발급되었으며 이메일 전송 요청이 접수되었습니다.'}


@router.get('/admin/accounts')
def list_accounts(user=Depends(system_user)):
    with connect() as db:
        rows = db.execute('SELECT employee_id,email,role,status,must_change_password FROM accounts ORDER BY created_at DESC LIMIT 500').fetchall()
    return {'accounts': rows}


@router.post('/admin/accounts')
def create_account(value: AccountInput, user=Depends(system_user)):
    try:
        with connect() as db:
            db.execute("INSERT INTO accounts(employee_id,email,password_hash,role,status) VALUES (%s,%s,%s,'admin','pending')",
                       (value.employee_id, str(value.email), hasher.hash(secrets.token_urlsafe(32))))
            db.execute('INSERT INTO account_audit(actor,employee_id,action) VALUES (%s,%s,%s)',
                       (user['employee_id'], value.employee_id, 'created'))
    except psycopg.errors.UniqueViolation:
        raise HTTPException(409, '이미 등록된 사원번호입니다.') from None
    return deliver(value.employee_id)


@router.post('/admin/accounts/{employee_id}/resend')
def resend(employee_id: str, user=Depends(system_user)):
    return deliver(employee_id)


@router.post('/admin/accounts/{employee_id}/disable')
def disable(employee_id: str, value: DisableInput, user=Depends(system_user)):
    if not value.reason.strip():
        raise HTTPException(422, '삭제 사유를 입력하세요.')
    with connect() as db:
        row = db.execute('SELECT * FROM accounts WHERE employee_id=%s FOR UPDATE', (employee_id,)).fetchone()
        if not row:
            raise HTTPException(404, '계정이 없습니다.')
        if row['role'] == 'system':
            raise HTTPException(403, '시스템팀 계정은 이 화면에서 삭제할 수 없습니다.')
        db.execute("UPDATE accounts SET status='disabled' WHERE employee_id=%s", (employee_id,))
        db.execute('DELETE FROM account_sessions WHERE employee_id=%s', (employee_id,))
        db.execute('INSERT INTO account_audit(actor,employee_id,action,reason) VALUES (%s,%s,%s,%s)',
                   (user['employee_id'], employee_id, 'disabled', value.reason.strip()))
    return {'message': '계정이 비활성화되었습니다.'}


@router.post('/admin/accounts/{employee_id}/delete')
def delete_account(employee_id: str, value: DisableInput, user=Depends(system_user)):
    if not value.reason.strip():
        raise HTTPException(422, '삭제 사유를 입력하세요.')
    with connect() as db:
        row = db.execute('SELECT * FROM accounts WHERE employee_id=%s FOR UPDATE', (employee_id,)).fetchone()
        if not row:
            raise HTTPException(404, '계정이 없습니다.')
        if row['role'] == 'system':
            raise HTTPException(403, '시스템팀 계정은 이 화면에서 삭제할 수 없습니다.')
        if row['status'] != 'disabled':
            raise HTTPException(409, '먼저 계정을 비활성화한 후 영구 삭제하세요.')
        db.execute('DELETE FROM account_sessions WHERE employee_id=%s', (employee_id,))
        db.execute('INSERT INTO account_audit(actor,employee_id,action,reason) VALUES (%s,%s,%s,%s)',
                   (user['employee_id'], employee_id, 'deleted', value.reason.strip()))
        db.execute('DELETE FROM accounts WHERE employee_id=%s', (employee_id,))
    return {'message': '계정이 영구 삭제되었습니다. 처리 이력은 보존됩니다.'}
