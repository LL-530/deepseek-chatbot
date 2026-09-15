"""
config.py —— 全局配置
------------------------------------------------------------
所有可调参数集中在这里，通过项目根目录的 .env 覆盖。
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# 项目根目录（backend/ 的上一层）
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _bool(key: str, default: bool = False) -> bool:
    return os.getenv(key, str(default)).strip().lower() in ("1", "true", "yes", "on")


# ---------------- MySQL ----------------
DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "deepseek_chat")

# ---------------- Ollama / 大模型 ----------------
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-r1:8b")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.7"))
SUMMARY_MODEL = os.getenv("SUMMARY_MODEL", LLM_MODEL)
SHOW_THINKING = _bool("SHOW_THINKING", True)
# 上下文窗口大小。内存小的机器可以调小（如 4096）来省内存
NUM_CTX = int(os.getenv("NUM_CTX", "8192"))

# ---------------- 对话记忆策略（防 token 爆炸）----------------
# 短期记忆：原样保留最近 N 轮（1 轮 = 用户 1 条 + AI 1 条）
SLIDING_WINDOW_ROUNDS = int(os.getenv("SLIDING_WINDOW_ROUNDS", "10"))
# 滑动窗口外「溢出」的老消息攒够多少条，就触发一次摘要压缩
COMPRESS_TRIGGER = int(os.getenv("COMPRESS_TRIGGER", "10"))
# 喂给摘要模型的文本字符上限
MAX_SUMMARY_INPUT_CHARS = int(os.getenv("MAX_SUMMARY_INPUT_CHARS", "6000"))

# ---------------- 认证 ----------------
JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret-change-me")
JWT_EXPIRE_HOURS = int(os.getenv("JWT_EXPIRE_HOURS", "24"))

# ---------------- 前端 ----------------
FRONTEND_DIR = BASE_DIR / "frontend"

# ---------------- 系统提示词 ----------------
SYSTEM_PROMPT = (
    "你是「小深」，一个部署在本地的 AI 助手，由 DeepSeek 大模型驱动。\n"
    "请遵守以下规则：\n"
    "1. 用简体中文回答，语气自然、友好、简洁。\n"
    "2. 回答尽量准确；不确定时明确说明，不要编造事实。\n"
    "3. 涉及代码时给出可运行的示例，并用 Markdown 代码块包裹。\n"
    "4. 如果系统提示词里带有「【本次对话的历史摘要】」段落，那是你和用户更早之前聊过的内容，"
    "请把它当作**已知事实**，不要在回答里说「这是摘要里写的」。\n"
    "5. 当用户问起姓名、喜好、经历、之前交代过的事情时，**必须先到历史摘要和最近对话里找答案**；"
    "只有在两处都确实没有时，才可以说不知道。"
)
