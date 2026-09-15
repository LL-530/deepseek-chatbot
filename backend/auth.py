"""
auth.py —— 登录认证：密码哈希 + JWT(HS256) + FastAPI 依赖
------------------------------------------------------------
对外提供：
    hash_password() / verify_password()   密码安全存储
    create_token()  / decode_token()      签发与校验 token
    get_current_user / require_admin     路由依赖（从 Header 里取 Bearer token）
    router                                POST /api/login, GET /api/me
"""
import base64
import hashlib
import hmac
import json
import os
import time
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field

from config import JWT_EXPIRE_HOURS, JWT_SECRET
from db import execute, query_one

# ============================================================
# 一、密码哈希（PBKDF2-HMAC-SHA256，绝不存明文）
# ============================================================
_ALGO = "pbkdf2_sha256"
_ITERATIONS = 200_000


def hash_password(raw: str) -> str:
    """把明文密码变成 `pbkdf2_sha256$迭代次数$盐$哈希` 格式的字符串。"""
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", raw.encode("utf-8"), salt, _ITERATIONS)
    return f"{_ALGO}${_ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(raw: str, stored: str) -> bool:
    """校验明文密码与库里的哈希是否匹配。"""
    try:
        algo, iterations, salt_hex, hash_hex = stored.split("$")
        if algo != _ALGO:
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", raw.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations)
        )
        return hmac.compare_digest(dk.hex(), hash_hex)
    except (ValueError, AttributeError):
        return False


# ============================================================
# 二、JWT（手写 HS256，零依赖，方便看清 token 到底是什么）
# ============================================================
def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(signing_input: str) -> str:
    digest = hmac.new(JWT_SECRET.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256).digest()
    return _b64url_encode(digest)


def create_token(user_id: int, username: str, role: str) -> str:
    """签发 token，默认 24 小时过期。"""
    now = int(time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": user_id,
        "username": username,
        "role": role,
        "iat": now,
        "exp": now + JWT_EXPIRE_HOURS * 3600,
    }
    seg = (
        f"{_b64url_encode(json.dumps(header, separators=(',', ':')).encode())}."
        f"{_b64url_encode(json.dumps(payload, separators=(',', ':')).encode())}"
    )
    return f"{seg}.{_sign(seg)}"


def decode_token(token: str) -> dict:
    """校验签名与过期时间，返回 payload；失败抛 401。"""
    invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="登录状态无效或已过期，请重新登录",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        header_b64, payload_b64, signature = token.split(".")
    except ValueError:
        raise invalid

    if not hmac.compare_digest(_sign(f"{header_b64}.{payload_b64}"), signature):
        raise invalid

    try:
        payload = json.loads(_b64url_decode(payload_b64))
    except (ValueError, json.JSONDecodeError):
        raise invalid

    if int(payload.get("exp", 0)) < int(time.time()):
        raise invalid
    return payload


# ============================================================
# 三、FastAPI 依赖
# ============================================================
def _extract_token(authorization: Optional[str]) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少 Authorization: Bearer <token> 请求头",
        )
    return authorization[7:].strip()


def get_current_user(authorization: Optional[str] = Header(default=None)) -> dict:
    """
    解析 token 并到数据库里取最新账号信息。
    注意：这里会重新查库，所以「禁用账号」可以立刻生效，不用等 token 过期。
    """
    payload = decode_token(_extract_token(authorization))
    user = query_one(
        "SELECT id, username, status, role, created_at FROM users WHERE id = %s",
        (payload.get("sub"),),
    )
    if not user:
        raise HTTPException(status_code=401, detail="账号不存在")
    if int(user["status"]) != 1:
        raise HTTPException(status_code=403, detail="账号已被禁用，请联系管理员")
    return user


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    """只有管理员能过的依赖。"""
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


# ============================================================
# 四、路由
# ============================================================
router = APIRouter(prefix="/api", tags=["认证"])


class LoginIn(BaseModel):
    username: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=1, max_length=128)


class ChangePasswordIn(BaseModel):
    old_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=6, max_length=128)


@router.post("/login", summary="用户名 + 密码登录，返回 token")
def login(body: LoginIn):
    user = query_one(
        "SELECT id, username, password_hash, status, role FROM users WHERE username = %s",
        (body.username.strip(),),
    )
    # 统一提示，避免暴露「用户名是否存在」
    if not user or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if int(user["status"]) != 1:
        raise HTTPException(status_code=403, detail="该账号已被禁用，无法登录")

    token = create_token(user["id"], user["username"], user["role"])
    return {
        "token": token,
        "expires_in": JWT_EXPIRE_HOURS * 3600,
        "user": {"id": user["id"], "username": user["username"], "role": user["role"]},
    }


@router.get("/me", summary="获取当前登录账号信息")
def me(user: dict = Depends(get_current_user)):
    return user


@router.post("/me/password", summary="修改自己的密码")
def change_my_password(body: ChangePasswordIn, user: dict = Depends(get_current_user)):
    row = query_one("SELECT password_hash FROM users WHERE id = %s", (user["id"],))
    if not verify_password(body.old_password, row["password_hash"]):
        raise HTTPException(status_code=400, detail="原密码不正确")
    execute(
        "UPDATE users SET password_hash = %s WHERE id = %s",
        (hash_password(body.new_password), user["id"]),
    )
    return {"message": "密码修改成功，请重新登录"}
