"""
routers/users.py —— 账号管理（管理员专属的增删改查）
------------------------------------------------------------
GET    /api/users            查询所有账号（支持关键字搜索、状态筛选）
GET    /api/users/stats      账号统计
GET    /api/users/{id}       查询单个账号
POST   /api/users            新增账号
PUT    /api/users/{id}       修改密码 / 状态 / 角色
DELETE /api/users/{id}       删除账号
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from auth import hash_password, require_admin
from db import execute, query_all, query_one

router = APIRouter(prefix="/api/users", tags=["账号管理"])


# ============================================================
# 入参模型
# ============================================================
class UserCreateIn(BaseModel):
    username: str = Field(..., min_length=3, max_length=50, description="用户名，3-50 位")
    password: str = Field(..., min_length=6, max_length=128, description="密码，至少 6 位")
    status: int = Field(1, ge=0, le=1, description="1=启用 0=禁用")
    role: str = Field("user", pattern="^(admin|user)$", description="admin / user")


class UserUpdateIn(BaseModel):
    """所有字段都可选，传了才改。"""
    password: str | None = Field(None, min_length=6, max_length=128)
    status: int | None = Field(None, ge=0, le=1)
    role: str | None = Field(None, pattern="^(admin|user)$")


# ============================================================
# 查询
# ============================================================
@router.get("/stats", summary="账号统计")
def user_stats(_: dict = Depends(require_admin)):
    row = query_one(
        """
        SELECT COUNT(*)                                        AS total,
               SUM(CASE WHEN status = 1 THEN 1 ELSE 0 END)     AS active,
               SUM(CASE WHEN status = 0 THEN 1 ELSE 0 END)     AS disabled,
               SUM(CASE WHEN role = 'admin' THEN 1 ELSE 0 END) AS admins
        FROM users
        """
    )
    return {
        "total": int(row["total"] or 0),
        "active": int(row["active"] or 0),
        "disabled": int(row["disabled"] or 0),
        "admins": int(row["admins"] or 0),
    }


@router.get("", summary="查询所有账号")
def list_users(
    keyword: str = Query("", description="按用户名模糊搜索"),
    status_filter: int | None = Query(None, alias="status", ge=0, le=1, description="按状态筛选"),
    _: dict = Depends(require_admin),
):
    sql = """
        SELECT u.id, u.username, u.status, u.role, u.created_at, u.updated_at,
               (SELECT COUNT(*) FROM chat_history h WHERE h.user_id = u.id) AS message_count
        FROM users u
        WHERE 1 = 1
    """
    params: list = []
    if keyword.strip():
        sql += " AND u.username LIKE %s"
        params.append(f"%{keyword.strip()}%")
    if status_filter is not None:
        sql += " AND u.status = %s"
        params.append(status_filter)
    sql += " ORDER BY u.id ASC"

    return {"total": len(rows := query_all(sql, params)), "items": rows}


@router.get("/{user_id}", summary="查询单个账号")
def get_user(user_id: int, _: dict = Depends(require_admin)):
    row = query_one(
        "SELECT id, username, status, role, created_at, updated_at FROM users WHERE id = %s",
        (user_id,),
    )
    if not row:
        raise HTTPException(status_code=404, detail="账号不存在")
    return row


# ============================================================
# 新增
# ============================================================
@router.post("", status_code=201, summary="新增账号")
def create_user(body: UserCreateIn, _: dict = Depends(require_admin)):
    username = body.username.strip()
    if query_one("SELECT id FROM users WHERE username = %s", (username,)):
        raise HTTPException(status_code=409, detail=f"用户名「{username}」已存在")

    user_id, _rows = execute(
        "INSERT INTO users (username, password_hash, status, role) VALUES (%s, %s, %s, %s)",
        (username, hash_password(body.password), body.status, body.role),
    )
    return {"id": user_id, "message": f"账号「{username}」创建成功"}


# ============================================================
# 修改
# ============================================================
@router.put("/{user_id}", summary="修改密码 / 状态 / 角色")
def update_user(user_id: int, body: UserUpdateIn, current: dict = Depends(require_admin)):
    target = query_one("SELECT id, username, status, role FROM users WHERE id = %s", (user_id,))
    if not target:
        raise HTTPException(status_code=404, detail="账号不存在")

    sets, params = [], []
    if body.password is not None:
        sets.append("password_hash = %s")
        params.append(hash_password(body.password))
    if body.status is not None:
        if user_id == current["id"] and body.status == 0:
            raise HTTPException(status_code=400, detail="不能禁用自己当前登录的账号")
        sets.append("status = %s")
        params.append(body.status)
    if body.role is not None:
        if user_id == current["id"] and body.role != "admin":
            raise HTTPException(status_code=400, detail="不能取消自己的管理员身份")
        sets.append("role = %s")
        params.append(body.role)

    if not sets:
        raise HTTPException(status_code=400, detail="没有需要修改的字段")

    params.append(user_id)
    execute(f"UPDATE users SET {', '.join(sets)} WHERE id = %s", params)
    return {"message": f"账号「{target['username']}」已更新"}


# ============================================================
# 删除
# ============================================================
@router.delete("/{user_id}", summary="删除账号（连带删除其会话与聊天记录）")
def delete_user(user_id: int, current: dict = Depends(require_admin)):
    target = query_one("SELECT id, username FROM users WHERE id = %s", (user_id,))
    if not target:
        raise HTTPException(status_code=404, detail="账号不存在")
    if user_id == current["id"]:
        raise HTTPException(status_code=400, detail="不能删除自己当前登录的账号")

    execute("DELETE FROM users WHERE id = %s", (user_id,))
    return {"message": f"账号「{target['username']}」及其聊天记录已删除"}
