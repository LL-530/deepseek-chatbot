/* ============================================================
   config.js —— 前端唯一的配置文件
   ------------------------------------------------------------
   ★ 改前端只需要动 frontend/ 这个文件夹，后端代码一行都不用碰。

   前后端通过 HTTP + JSON 接口通信，只要接口不变，
   你可以随意重写页面、换配色、加功能，后端完全不受影响。
   ============================================================ */

window.APP_CONFIG = {

    /* ---------- 后端地址（改这里就能前后端分离部署）---------- */
    // 留空字符串 = 跟当前页面同源（后端顺便托管前端，推荐，最省事）
    // 前后端分开部署时改成后端地址，例如：
    //   API_BASE: 'http://127.0.0.1:8000'
    // 注意：后端已开启 CORS，跨域直接可用
    API_BASE: '',

    /* ---------- 界面文案（纯前端展示，随便改）---------- */
    APP_NAME: '本地聊天机器人',
    APP_SUBTITLE: 'DeepSeek · 本地部署 · 记忆增强',
    BOT_NAME: '小深',
    BOT_AVATAR: '🤖',
    APP_LOGO: '🤖',

    /* ---------- 登录页 ---------- */
    LOGIN_TITLE: '本地聊天机器人',
    LOGIN_HINT: '默认管理员账号：<code>admin</code> / <code>admin123</code>',

    /* ---------- 聊天页 ---------- */
    EMPTY_HINT: '开始和 AI 聊聊吧～ 试试问它「你好，请介绍一下你自己」',
    INPUT_PLACEHOLDER: '输入消息，Enter 发送，Shift + Enter 换行',
    // 是否默认展开模型的思考过程（deepseek-r1 特有）
    SHOW_THINKING: true,

    /* ---------- 主题配色（对应 css/app.css 里的 CSS 变量）---------- */
    THEME: {
        accent: '#4f7cff',
        accentHover: '#6a90ff',
        violet: '#8b5cf6'
    }
};

/* 把主题色应用到 CSS 变量上，改上面 THEME 就能整体换色 */
(function applyTheme() {
    const t = window.APP_CONFIG.THEME;
    if (!t) return;
    const root = document.documentElement;
    if (t.accent) root.style.setProperty('--accent', t.accent);
    if (t.accentHover) root.style.setProperty('--accent-hover', t.accentHover);
    if (t.violet) root.style.setProperty('--violet', t.violet);
})();
