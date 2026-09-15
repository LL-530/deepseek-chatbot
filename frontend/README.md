# 前端说明 · 随便改，不影响后端

这个文件夹是**完全独立**的。你可以重写页面、换配色、加功能、甚至整个换一套 UI，
**后端一行代码都不用动**。

---

## 一、为什么不会影响后端

前后端之间只有一种关系：**HTTP + JSON 接口调用**。

```
frontend/                       backend/
（纯静态文件）                    （FastAPI）
   │                                │
   │  fetch('/api/chat/stream')     │
   └────────── HTTP JSON ──────────►│
                                    │
   ◄────────── SSE / JSON ──────────┘
```

- 后端**只提供接口**，不知道前端长什么样。
- 后端只是"顺便"把这些静态文件托管出去（`main.py` 最后一行挂载了 `frontend/` 目录），
  换成别的文件夹名、别的页面名都能跑，后端不关心。
- 所以：**改前端 = 改这个文件夹里的文件，刷新浏览器即可看到效果。**

---

## 二、文件说明

```
frontend/
├── index.html          入口页（自动跳转到登录页或聊天页）
├── login.html          登录页
├── chat.html           聊天页（流式打字机效果）
├── admin.html          账号管理页
├── js/
│   ├── config.js       ★ 前端唯一的配置文件，先改这里
│   └── common.js       公共工具：登录态、接口封装、Markdown 渲染
└── css/
    └── app.css         全部样式（用了 CSS 变量，改顶部 :root 就能整体换色）
```

---

## 三、最常改的几件事

### 1. 换品牌名 / 文案 / 机器人头像

打开 `js/config.js`：

```js
window.APP_CONFIG = {
    APP_NAME: '我的智能助手',        // 左上角标题
    APP_SUBTITLE: '基于 DeepSeek',
    BOT_NAME: '小深',
    BOT_AVATAR: '🐳',               // AI 头像，emoji 或图片 URL 都行
    APP_LOGO: '🐳',
    EMPTY_HINT: '来聊点什么吧～',
    ...
};
```

保存后刷新浏览器就生效，**不用重启后端**。

### 2. 换配色

同样在 `js/config.js`：

```js
THEME: {
    accent: '#ff6b6b',        // 主色（按钮、用户气泡）
    accentHover: '#ff8a8a',
    violet: '#c084fc'         // 渐变辅色（Logo、AI 头像背景）
}
```

想改得更彻底，直接编辑 `css/app.css` 最上面的 `:root { ... }` 变量块。

### 3. 前后端分开部署

默认前端和后端在同一个地址（后端顺便托管前端），`API_BASE` 留空即可。

如果你想**把前端单独部署**（比如丢到 Nginx、或者直接双击 HTML 文件打开），
改 `js/config.js`：

```js
API_BASE: 'http://127.0.0.1:8000',   // 填后端的实际地址
```

后端已经开了 CORS（允许所有来源），跨域直接可用。

### 4. 加一个新页面

1. 在 `frontend/` 下新建 `mypage.html`
2. 页面里按顺序引入：
   ```html
   <link rel="stylesheet" href="css/app.css">
   <script src="js/config.js"></script>
   <script src="js/common.js"></script>
   ```
3. 用现成的工具函数：

   | 函数 | 作用 |
   |------|------|
   | `guard()` | 没登录就跳回登录页，页面开头调用 |
   | `api(path, options)` | 带 token 的请求，自动处理 401 和错误 |
   | `getUser()` / `getToken()` | 读当前登录信息 |
   | `escapeHtml(str)` | 防 XSS，渲染用户输入前一定要调 |
   | `renderMarkdown(text)` | 简易 Markdown → HTML |
   | `showAlert(el, msg, type)` | 显示提示条 |
   | `formatTime(str)` | 格式化时间 |

   示例：
   ```html
   <div id="out"></div>
   <script src="js/config.js"></script>
   <script src="js/common.js"></script>
   <script>
       if (!guard()) throw new Error('未登录');
       (async () => {
           const data = await api('/api/conversations');
           document.getElementById('out').textContent =
               `我有 ${data.total} 个会话`;
       })();
   </script>
   ```

---

## 四、可以调用的后端接口

后端接口是**契约**。只要不动后端，这些接口就是稳定的：

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/login` | 登录，返回 `{token, user}` |
| GET | `/api/me` | 当前账号信息 |
| POST | `/api/me/password` | 改自己的密码 |
| GET | `/api/users` | 账号列表（管理员） |
| GET | `/api/users/stats` | 账号统计（管理员） |
| POST | `/api/users` | 新增账号（管理员） |
| PUT | `/api/users/{id}` | 改密码/状态/角色（管理员） |
| DELETE | `/api/users/{id}` | 删除账号（管理员） |
| POST | `/api/chat/stream` | **流式对话（SSE）** |
| GET | `/api/conversations` | 会话列表 |
| POST | `/api/conversations` | 新建会话 |
| DELETE | `/api/conversations/{id}` | 删除会话 |
| GET | `/api/conversations/{id}/messages` | 历史消息 |
| GET | `/api/conversations/{id}/memory` | 记忆状态 |
| GET | `/api/health` | 健康检查 |

完整交互式文档（能直接点着试）：服务启动后打开 <http://127.0.0.1:8000/docs>

### 流式对话的事件格式

`POST /api/chat/stream` 返回 `text/event-stream`，每个事件长这样：

```
data: {"type":"delta","content":"你"}
```

| type | 含义 |
|------|------|
| `meta` | 会话 id、用户消息 id |
| `thinking` | 模型思考链（deepseek-r1 特有） |
| `delta` | 回答的一个片段，拼起来就是打字机效果 |
| `compressed` | 触发了历史摘要压缩 |
| `error` | 出错 |
| `done` | 结束，附带最新记忆状态 |

用 `fetch` + `ReadableStream` 读取（`EventSource` 不支持 POST 和自定义请求头）：

```js
const resp = await fetch(apiUrl('/api/chat/stream'), {
    method: 'POST',
    headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + getToken()
    },
    body: JSON.stringify({ message: '你好', conversation_id: null })
});

const reader = resp.body.getReader();
const decoder = new TextDecoder('utf-8');
let buf = '';
while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf('\n\n')) >= 0) {
        const chunk = buf.slice(0, i);
        buf = buf.slice(i + 2);
        const line = chunk.split('\n').find(l => l.startsWith('data:'));
        if (line) console.log(JSON.parse(line.slice(5)));
    }
}
```

---

## 五、注意事项

- **为什么零依赖？** 这套页面的交互复杂度不高，原生三件套已经够用，
  省掉构建环节和框架体积。想引入 Vue/React 也行，改 `index.html` 里的引入即可，
  后端完全不受影响。
- **`escapeHtml` 不能省。** 凡是把用户输入或 AI 输出插进 `innerHTML` 之前，
  一定要先 escape，否则有 XSS 风险。
- **改了 HTML/CSS/JS 不用重启后端**，浏览器强制刷新（Ctrl + F5）即可。
- **只有改了 `backend/` 里的 Python 代码才需要重启服务。**
