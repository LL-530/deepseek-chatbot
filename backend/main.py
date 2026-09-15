"""
main.py —— FastAPI 应用入口
------------------------------------------------------------
启动： python run.py      （或 uvicorn main:app --reload --port 8000）
文档： http://127.0.0.1:8000/docs
"""
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# 让 `python main.py` / uvicorn 都能正确 import 同目录模块
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import RedirectResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

import llm  # noqa: E402
from auth import router as auth_router  # noqa: E402
from config import FRONTEND_DIR, LLM_MODEL, OLLAMA_BASE_URL  # noqa: E402
from db import init_db  # noqa: E402
from routers.chat import router as chat_router  # noqa: E402
from routers.users import router as users_router  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时：建库建表 + 自检模型；关闭时什么都不用做。"""
    print("=" * 60)
    print("  基于 DeepSeek 的本地聊天机器人 —— 启动中")
    print("=" * 60)

    try:
        init_db()
        print("[ok] 数据库已就绪（建库 / 建表 / 默认管理员）")
    except Exception as exc:  # noqa: BLE001
        print(f"[!!] 数据库初始化失败：{exc}")
        print("     请检查 .env 里的 DB_USER / DB_PASSWORD 是否正确，MySQL 是否已启动。")

    ok, message = llm.check_model_ready()
    print(f"[{'ok' if ok else '!!'}] {message}")
    if not ok:
        print("     提示：执行 `ollama pull deepseek-r1:8b` 下载模型后再试。")

    print("-" * 60)
    print(f"  对话模型 : {LLM_MODEL}")
    print(f"  Ollama   : {OLLAMA_BASE_URL}")
    print("  访问地址 : http://127.0.0.1:8000")
    print("=" * 60)
    yield


app = FastAPI(
    title="基于 DeepSeek 的本地聊天机器人",
    description="FastAPI + MySQL + LangChain + Ollama(deepseek-r1:8b)",
    version="1.0.0",
    lifespan=lifespan,
)

# 前后端同源部署时用不到 CORS；这里开着是为了方便你单独调试前端页面
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------- 业务路由 ----------------
app.include_router(auth_router)
app.include_router(users_router)
app.include_router(chat_router)


@app.get("/api/health", tags=["系统"], summary="健康检查")
def health():
    ok, message = llm.check_model_ready()
    return {"status": "ok", "model": LLM_MODEL, "model_ready": ok, "detail": message}


@app.get("/", include_in_schema=False)
def index():
    return RedirectResponse(url="/login.html")


# ---------------- 前端静态页（必须最后挂载）----------------
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=False)
