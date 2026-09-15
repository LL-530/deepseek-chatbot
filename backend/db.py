"""
db.py —— MySQL 连接与原生 SQL 工具（pymysql，不使用 ORM）
------------------------------------------------------------
对外提供：
    db_cursor()      上下文管理器，拿一个 DictCursor
    query_all()      查多行
    query_one()      查一行
    execute()        增删改，返回 (lastrowid, rowcount)
    init_db()        建库建表 + 初始化管理员（幂等，启动时调用）
"""
from contextlib import contextmanager
from typing import Any, Iterable, Optional

import pymysql
from pymysql.cursors import DictCursor

from config import DB_HOST, DB_NAME, DB_PASSWORD, DB_PORT, DB_USER


# ------------------------------------------------------------
# 连接
# ------------------------------------------------------------
def get_connection(with_database: bool = True):
    """创建一个新的 MySQL 连接。"""
    kwargs: dict[str, Any] = dict(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=True,          # 开自动提交，业务代码不用手动 commit，更直观
    )
    if with_database:
        kwargs["database"] = DB_NAME
    return pymysql.connect(**kwargs)


@contextmanager
def db_cursor(with_database: bool = True):
    """with db_cursor() as cur: ...  出作用域自动关连接。"""
    conn = get_connection(with_database=with_database)
    try:
        with conn.cursor() as cur:
            yield cur
    finally:
        conn.close()


# ------------------------------------------------------------
# 常用查询封装
# ------------------------------------------------------------
def query_all(sql: str, params: Optional[Iterable] = None) -> list[dict]:
    with db_cursor() as cur:
        cur.execute(sql, params or ())
        return list(cur.fetchall())


def query_one(sql: str, params: Optional[Iterable] = None) -> Optional[dict]:
    with db_cursor() as cur:
        cur.execute(sql, params or ())
        return cur.fetchone()


def execute(sql: str, params: Optional[Iterable] = None) -> tuple[int, int]:
    """返回 (lastrowid, rowcount)。"""
    with db_cursor() as cur:
        rows = cur.execute(sql, params or ())
        return cur.lastrowid or 0, rows


def executemany(sql: str, seq: Iterable) -> int:
    with db_cursor() as cur:
        return cur.executemany(sql, seq)


# ------------------------------------------------------------
# 建表 + 初始化数据（幂等）
# ------------------------------------------------------------
SCHEMA_STATEMENTS = [
    # 1) 账号表
    """
    CREATE TABLE IF NOT EXISTS users (
        id            INT AUTO_INCREMENT PRIMARY KEY,
        username      VARCHAR(50)  NOT NULL,
        password_hash VARCHAR(255) NOT NULL,
        status        TINYINT      NOT NULL DEFAULT 1,
        role          VARCHAR(20)  NOT NULL DEFAULT 'user',
        created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        UNIQUE KEY uk_username (username)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    # 2) 会话表
    """
    CREATE TABLE IF NOT EXISTS conversations (
        id              INT AUTO_INCREMENT PRIMARY KEY,
        user_id         INT          NOT NULL,
        title           VARCHAR(120) NOT NULL DEFAULT '新对话',
        summary         TEXT         NULL,
        summary_upto_id BIGINT       NOT NULL DEFAULT 0,
        created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        KEY idx_conv_user (user_id),
        CONSTRAINT fk_conv_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    # 3) 聊天历史表
    """
    CREATE TABLE IF NOT EXISTS chat_history (
        id              BIGINT AUTO_INCREMENT PRIMARY KEY,
        user_id         INT         NOT NULL,
        conversation_id INT         NOT NULL,
        role            VARCHAR(20) NOT NULL,
        content         MEDIUMTEXT  NOT NULL,
        created_at      DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
        KEY idx_hist_conv (conversation_id, id),
        KEY idx_hist_user (user_id),
        CONSTRAINT fk_hist_conv FOREIGN KEY (conversation_id) REFERENCES conversations (id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
]

DEFAULT_ADMIN = ("admin", "admin123")


def init_db() -> None:
    """建库 -> 建表 -> 补默认管理员。可以重复执行。"""
    # 建库（这一步不能指定 database）
    with db_cursor(with_database=False) as cur:
        cur.execute(
            f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}` "
            f"DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )

    # 建表
    with db_cursor() as cur:
        for stmt in SCHEMA_STATEMENTS:
            cur.execute(stmt)

    # 默认管理员（首次启动才写）
    from auth import hash_password  # 局部导入，避免循环依赖

    username, raw_password = DEFAULT_ADMIN
    if not query_one("SELECT id FROM users WHERE username = %s", (username,)):
        execute(
            "INSERT INTO users (username, password_hash, status, role) VALUES (%s, %s, 1, 'admin')",
            (username, hash_password(raw_password)),
        )
        print(f"[db] 已创建默认管理员：{username} / {raw_password}")
