"""Database-backed login. Only token digests and password hashes are stored."""
import datetime as dt
import hashlib
import secrets
import threading
import time
from collections import OrderedDict
from urllib.parse import urlsplit
from fastapi import HTTPException, Request, Response
from sqlalchemy import select, delete
from sqlalchemy.orm import Session
from .db import User, LoginSession, now

COOKIE = 'oa_session'
TTL = 12 * 60 * 60

def hash_password(password):
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 600000).hex()
    return f'pbkdf2_sha256$600000${salt}${digest}'

def verify_password(password, encoded):
    try:
        algo, rounds, salt, digest = encoded.split('$')
        if algo != 'pbkdf2_sha256' or int(rounds) != 600000:
            return False
        actual = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), int(rounds)).hex()
        return secrets.compare_digest(actual, digest)
    except (ValueError, TypeError):
        return False

_dummy = hash_password('unused-comparison-password')
_attempts = OrderedDict()
_lock = threading.Lock()

def public_user(user):
    return {key: getattr(user, key) for key in ('id', 'username', 'display_name', 'role', 'department')}

def check_origin(request):
    origin = request.headers.get('origin')
    if origin and urlsplit(origin).netloc != request.headers.get('host'):
        raise HTTPException(403, '请求来源不匹配，请刷新页面后重试')

def authorize(request: Request):
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        check_origin(request)
    if request.url.path == '/api/auth/login':
        return None
    token = request.cookies.get(COOKIE, '')
    with Session(request.app.state.engine) as db:
        item = db.get(LoginSession, hashlib.sha256(token.encode()).hexdigest()) if token else None
        user = db.get(User, item.user_id) if item and item.expires_at > now() else None
        if not user or not user.active:
            raise HTTPException(401, '登录已过期，请重新登录')
        return public_user(user)

def login(request: Request, response: Response, username, password, db):
    check_origin(request)
    key = request.client.host if request.client else 'unknown'
    clock = time.monotonic()
    with _lock:
        attempts = [t for t in _attempts.get(key, []) if clock - t < 300]
        if len(attempts) >= 20:
            raise HTTPException(429, '尝试次数过多，请五分钟后再试')
        _attempts[key] = attempts + [clock]
        _attempts.move_to_end(key)
        while len(_attempts) > 10000:
            _attempts.popitem(last=False)
    user = db.scalar(select(User).where(User.username == username.strip()))
    valid = verify_password(password, user.password_hash if user else _dummy)
    if not valid or not user or not user.active:
        raise HTTPException(401, '账号或密码错误')
    token = secrets.token_urlsafe(32)
    old = request.cookies.get(COOKIE)
    if old:
        db.execute(delete(LoginSession).where(LoginSession.token_hash == hashlib.sha256(old.encode()).hexdigest()))
    db.execute(delete(LoginSession).where(LoginSession.expires_at <= now()))
    db.add(LoginSession(token_hash=hashlib.sha256(token.encode()).hexdigest(), user_id=user.id,
                        expires_at=now() + dt.timedelta(seconds=TTL)))
    user.last_login_at = now()
    db.commit()
    # Production reverse proxy supplies the original HTTPS scheme to Uvicorn.
    response.set_cookie(COOKIE, token, max_age=TTL, httponly=True,
                        secure=request.url.scheme == 'https', samesite='strict', path='/')
    response.headers['Cache-Control'] = 'no-store'
    return public_user(user)

def logout(request, response, db):
    token = request.cookies.get(COOKIE, '')
    db.execute(delete(LoginSession).where(LoginSession.token_hash == hashlib.sha256(token.encode()).hexdigest()))
    db.commit()
    response.delete_cookie(COOKIE, path='/')
    return {'status': 'ok'}
