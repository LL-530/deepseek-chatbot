"""
run.py —— 一键启动脚本
------------------------------------------------------------
    python run.py                # 默认 127.0.0.1:8000
    python run.py --port 9000    # 换端口
    python run.py --reload       # 改代码自动重启（开发时用）
"""
import argparse
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))

import uvicorn  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="启动本地聊天机器人服务")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址")
    parser.add_argument("--port", type=int, default=8000, help="监听端口")
    parser.add_argument("--reload", action="store_true", help="开发模式：代码改动自动重启")
    args = parser.parse_args()

    print(f"→ 服务即将启动：http://{args.host}:{args.port}")
    uvicorn.run(
        "main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        app_dir=str(BACKEND_DIR),
    )


if __name__ == "__main__":
    main()
