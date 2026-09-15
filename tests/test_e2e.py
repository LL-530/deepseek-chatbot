"""
端到端联调测试：登录 -> 账号CRUD -> 流式对话 -> 记忆压缩 -> 历史回显

用法：
    python tests/test_e2e.py                   # 默认 http://127.0.0.1:8000
    python tests/test_e2e.py --base http://127.0.0.1:8001
    python tests/test_e2e.py --max-rounds 20   # 允许更多轮对话来触发压缩

注意：记忆压缩的触发轮数取决于服务端的 SLIDING_WINDOW_ROUNDS / COMPRESS_TRIGGER。
      脚本会先探测这两个值：轮数够就跑，不够就标 SKIP（而不是误报 FAIL）。
"""
import argparse
import json
import math
import sys
import time

import httpx

parser = argparse.ArgumentParser()
parser.add_argument("--base", default="http://127.0.0.1:8000")
parser.add_argument("--max-rounds", type=int, default=8,
                    help="最多聊多少轮来触发压缩，超过就跳过该断言")
args = parser.parse_args()

client = httpx.Client(base_url=args.base, timeout=300.0)

passed = failed = skipped = 0
need_rounds = None


def ok(label, cond, extra=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"[PASS] {label} {extra}")
    else:
        failed += 1
        print(f"[FAIL] {label} {extra}")


def skip(label, why):
    global skipped
    skipped += 1
    print(f"[SKIP] {label} —— {why}")


def login(username, password):
    return client.post("/api/login", json={"username": username, "password": password})


def auth(token):
    return {"Authorization": f"Bearer {token}"}


print("=" * 70)
print(f"测试目标：{args.base}")
print("=" * 70)
print("1. 登录认证")
print("=" * 70)
r = login("admin", "admin123")
ok("admin 正常登录", r.status_code == 200, f"HTTP {r.status_code}")
admin_token = r.json()["token"]

r = login("admin", "wrong-password")
ok("错误密码被拒绝", r.status_code == 401, f"HTTP {r.status_code}")

r = client.get("/api/me", headers=auth(admin_token))
ok("GET /api/me 返回管理员", r.status_code == 200 and r.json()["role"] == "admin")

r = client.get("/api/users", headers={})
ok("无 token 访问被拒绝", r.status_code == 401, f"HTTP {r.status_code}")

r = client.get("/api/users", headers=auth("bad.token.here"))
ok("伪造 token 被拒绝", r.status_code == 401, f"HTTP {r.status_code}")

print()
print("=" * 70)
print("2. 账号管理 CRUD")
print("=" * 70)
r = client.post("/api/users", headers=auth(admin_token),
                json={"username": "testuser", "password": "test123456", "status": 1, "role": "user"})
if r.status_code == 409:
    for u in client.get("/api/users?keyword=testuser", headers=auth(admin_token)).json()["items"]:
        client.delete(f"/api/users/{u['id']}", headers=auth(admin_token))
    r = client.post("/api/users", headers=auth(admin_token),
                    json={"username": "testuser", "password": "test123456", "status": 1, "role": "user"})
ok("新增账号", r.status_code == 201, f"HTTP {r.status_code}")
test_uid = r.json()["id"]

r = client.post("/api/users", headers=auth(admin_token),
                json={"username": "testuser", "password": "test123456"})
ok("重复用户名被拒绝", r.status_code == 409, f"HTTP {r.status_code}")

r = client.get("/api/users?keyword=test", headers=auth(admin_token))
ok("关键字搜索", r.status_code == 200 and len(r.json()["items"]) >= 1, f"命中 {r.json()['total']} 条")

r = client.get("/api/users/stats", headers=auth(admin_token))
ok("账号统计", r.status_code == 200, json.dumps(r.json(), ensure_ascii=False))

r = login("testuser", "test123456")
ok("普通用户登录", r.status_code == 200, f"HTTP {r.status_code}")
user_token = r.json()["token"]

r = client.get("/api/users", headers=auth(user_token))
ok("普通用户访问管理接口被拒（403）", r.status_code == 403, f"HTTP {r.status_code}")

print()
print("=" * 70)
print("3. 流式对话（打字机）+ 记忆压缩")
print("=" * 70)


def chat(question, conversation_id):
    """发一轮对话，返回 (会话id, 事件列表, 正文, 思考链)"""
    payload = {"message": question}
    if conversation_id:
        payload["conversation_id"] = conversation_id

    events = []
    with client.stream("POST", "/api/chat/stream", json=payload, headers=auth(user_token)) as resp:
        assert resp.status_code == 200, resp.read()
        buf = ""
        for chunk in resp.iter_text():
            buf += chunk
            while "\n\n" in buf:
                raw, buf = buf.split("\n\n", 1)
                line = next((l for l in raw.split("\n") if l.startswith("data:")), None)
                if line:
                    events.append(json.loads(line[5:].strip()))

    done = next((e for e in events if e["type"] == "done"), None)
    text = "".join(e.get("content", "") for e in events if e["type"] == "delta")
    think = "".join(e.get("content", "") for e in events if e["type"] == "thinking")
    return (done["conversation_id"] if done else conversation_id), events, text, think


questions = [
    "记住一个信息：我叫小明。只回复「好的」。",
    "我最喜欢的颜色是蓝色。只回复「记住了」。",
    "我养了一只叫豆豆的猫。只回复「好的」。",
    "我叫什么名字？我养了什么宠物？",
]

conv_id = None

for i, question in enumerate(questions, 1):
    t0 = time.time()
    conv_id, events, text, think = chat(question, conv_id)
    types = [e["type"] for e in events]
    compressed = next((e for e in events if e["type"] == "compressed"), None)

    print(f"\n--- 第 {i} 轮（{time.time()-t0:.1f}s）---")
    print(f"    提问: {question}")
    print(f"    事件: {sorted(set(types))}")
    print(f"    思考链 {len(think)} 字 / 正文 {len(text)} 字")
    print(f"    回复: {text.strip()[:90]}")
    if compressed:
        print(f"    ★ 触发摘要压缩：已压缩 {compressed['compressed_messages']} 条")

    if i == 1:
        ok("出现 meta 事件", "meta" in types)
        ok("流式分块 > 1（打字机效果）", types.count("delta") > 1, f"{types.count('delta')} 块")
        ok("出现 done 事件", "done" in types)

        # 探测服务端的记忆配置，决定要聊多少轮才能触发压缩
        mem = client.get(f"/api/conversations/{conv_id}/memory", headers=auth(user_token)).json()
        win, trig = mem["window_rounds"], mem["compress_trigger"]
        # 未压缩消息数 = 2N；要求 2N > 2*win 且 2N - 2*win >= trig
        need_rounds = win + math.ceil(trig / 2) + 1
        print(f"\n    服务端记忆配置：窗口 {win} 轮 / 触发阈值 {trig} 条")
        print(f"    → 约需 {need_rounds} 轮对话才会触发压缩（本次上限 {args.max_rounds} 轮）")

        if need_rounds <= args.max_rounds:
            for k in range(len(questions), need_rounds):
                questions.append(f"这是第 {k + 1} 轮，随便聊点什么。")
        else:
            print("    → 轮数需求超过上限，压缩相关断言将标记为 SKIP")

    if i == len(questions):
        if compressed is not None:
            ok("触发记忆压缩", True)
            ok("模型记得用户名字（摘要生效）", "小明" in text, f"回复={text.strip()[:60]}")
        elif need_rounds is not None and need_rounds <= args.max_rounds:
            ok("触发记忆压缩", False, "聊够轮数仍未触发")
        else:
            skip("触发记忆压缩", f"需要 {need_rounds} 轮，超过本次上限 {args.max_rounds}")

print()
print("=" * 70)
print("4. 历史回显 + 记忆状态")
print("=" * 70)
r = client.get(f"/api/conversations/{conv_id}/messages", headers=auth(user_token))
items = r.json()["items"]
ok("历史消息全量回显", r.status_code == 200 and len(items) == len(questions) * 2,
   f"{len(items)} 条 / 预期 {len(questions) * 2} 条")
ok("历史包含用户与AI两种角色", {m["role"] for m in items} == {"user", "assistant"})

mem = client.get(f"/api/conversations/{conv_id}/memory", headers=auth(user_token)).json()
print("    记忆状态:", json.dumps({k: v for k, v in mem.items() if k != "summary"}, ensure_ascii=False))
print("    摘要内容:", (mem["summary"] or "(空)")[:120])
ok("滑动窗口内消息 <= 窗口上限", mem["window_messages"] <= mem["window_rounds"] * 2,
   f"{mem['window_messages']} <= {mem['window_rounds'] * 2}")

if mem["compressed_messages"] > 0:
    ok("已压缩消息数 > 0", True, f"{mem['compressed_messages']} 条")
    ok("摘要非空", bool(mem["summary"].strip()))
else:
    skip("已压缩消息数 > 0", "对话长度还没到压缩阈值")
    skip("摘要非空", "同上")

r = client.get("/api/conversations", headers=auth(user_token))
ok("会话列表", r.status_code == 200 and r.json()["total"] >= 1, f"{r.json()['total']} 个会话")

print()
print("=" * 70)
print("5. 禁用账号 -> 立刻失效")
print("=" * 70)
r = client.put(f"/api/users/{test_uid}", headers=auth(admin_token), json={"status": 0})
ok("管理员禁用账号", r.status_code == 200, f"HTTP {r.status_code}")

r = login("testuser", "test123456")
ok("被禁用账号无法登录（403）", r.status_code == 403, f"HTTP {r.status_code}")

r = client.get("/api/me", headers=auth(user_token))
ok("已登录的 token 也立即失效", r.status_code == 403, f"HTTP {r.status_code}")

r = client.put("/api/users/1", headers=auth(admin_token), json={"status": 0})
ok("管理员不能禁用自己", r.status_code == 400, f"HTTP {r.status_code}")

print()
print("=" * 70)
print("6. 修改密码 + 删除账号")
print("=" * 70)
r = client.put(f"/api/users/{test_uid}", headers=auth(admin_token), json={"password": "newpass123"})
ok("管理员重置密码", r.status_code == 200, f"HTTP {r.status_code}")

r = client.put(f"/api/users/{test_uid}", headers=auth(admin_token), json={"status": 1})
ok("重新启用账号", r.status_code == 200)

r = login("testuser", "newpass123")
ok("新密码可登录", r.status_code == 200, f"HTTP {r.status_code}")

r = client.delete(f"/api/users/{test_uid}", headers=auth(admin_token))
ok("删除账号", r.status_code == 200, f"HTTP {r.status_code}")

r = login("testuser", "newpass123")
ok("删除后无法登录", r.status_code == 401, f"HTTP {r.status_code}")

r = client.get("/api/users", headers=auth(admin_token))
ok("账号已从列表移除", all(u["username"] != "testuser" for u in r.json()["items"]))

print()
print("=" * 70)
print(f"测试完成：{passed} 通过 / {failed} 失败 / {skipped} 跳过")
print("=" * 70)
sys.exit(1 if failed else 0)
