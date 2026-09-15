/* ============================================================
   common.js —— 公共工具：登录态管理 / 接口封装 / Markdown 渲染
   原生 JavaScript，无任何框架依赖

   ★ 前端与后端完全解耦：所有请求都走下面的 apiUrl()，
     后端地址在 js/config.js 里配置，改前端不用动后端。
   ============================================================ */

const TOKEN_KEY = 'ds_token';
const USER_KEY = 'ds_user';

/* ---------------- 配置读取 ---------------- */
const CFG = window.APP_CONFIG || {};

/** 读配置项，带默认值 */
function cfg(key, fallback) {
    const v = CFG[key];
    return (v === undefined || v === null) ? fallback : v;
}

/** 后端 API 根地址（末尾不带 /） */
const API_BASE = String(cfg('API_BASE', '')).replace(/\/+$/, '');

/** 把 /api/xxx 拼成完整的请求地址 */
function apiUrl(path) {
    return API_BASE + path;
}

/* ---------------- 登录态 ---------------- */
function getToken() {
    return localStorage.getItem(TOKEN_KEY) || '';
}

function getUser() {
    try {
        return JSON.parse(localStorage.getItem(USER_KEY) || 'null');
    } catch (e) {
        return null;
    }
}

function saveAuth(token, user) {
    localStorage.setItem(TOKEN_KEY, token);
    localStorage.setItem(USER_KEY, JSON.stringify(user));
}

function clearAuth() {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
}

/** 页面开头调用：没登录就踢回登录页 */
function guard() {
    if (!getToken()) {
        location.replace('login.html');
        return false;
    }
    return true;
}

function logout() {
    clearAuth();
    location.replace('login.html');
}

/* ---------------- 接口封装 ---------------- */
/**
 * 统一请求：自动带 token、自动处理 401、自动解析 JSON。
 * @throws {Error} 带 .status 属性
 */
async function api(path, options = {}) {
    const opts = Object.assign({ method: 'GET' }, options);
    opts.headers = Object.assign({ 'Content-Type': 'application/json' }, opts.headers || {});

    const token = getToken();
    if (token) opts.headers['Authorization'] = 'Bearer ' + token;
    if (opts.body && typeof opts.body !== 'string') opts.body = JSON.stringify(opts.body);

    const resp = await fetch(apiUrl(path), opts);

    if (resp.status === 401) {
        clearAuth();
        location.replace('login.html');
        throw new Error('登录已过期');
    }

    let data = null;
    const text = await resp.text();
    if (text) {
        try { data = JSON.parse(text); } catch (e) { data = { detail: text }; }
    }

    if (!resp.ok) {
        const detail = (data && (data.detail || data.message)) || `请求失败（HTTP ${resp.status}）`;
        const err = new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
        err.status = resp.status;
        throw err;
    }
    return data;
}

/* ---------------- DOM 小工具 ---------------- */
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

function escapeHtml(str) {
    return String(str)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

/** 简易提示条：type = error | success | info */
function showAlert(container, message, type = 'error') {
    const el = typeof container === 'string' ? $(container) : container;
    if (!el) return;
    el.className = 'alert alert-' + type;
    el.textContent = message;
    el.classList.remove('hidden');
}

function hideAlert(container) {
    const el = typeof container === 'string' ? $(container) : container;
    if (el) el.classList.add('hidden');
}

function formatTime(value) {
    if (!value) return '-';
    const d = new Date(String(value).replace(' ', 'T'));
    if (isNaN(d.getTime())) return value;
    const p = (n) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

/* ---------------- Markdown 渲染（极简实现，够用即可）---------------- */
/**
 * 支持：围栏代码块、行内代码、标题、加粗、斜体、无序/有序列表、
 *       引用、分割线、链接、换行。
 * 思路：先把代码块抠出来占位，避免里面的符号被误伤。
 */
function renderMarkdown(src) {
    if (!src) return '';
    const blocks = [];

    // 1) 抠出 ``` 代码块
    let text = String(src).replace(/```(\w*)\n?([\s\S]*?)```/g, (m, lang, code) => {
        const idx = blocks.length;
        blocks.push(`<pre><code class="lang-${escapeHtml(lang || 'text')}">${escapeHtml(code.replace(/\n$/, ''))}</code></pre>`);
        return `\u0000BLOCK${idx}\u0000`;
    });

    // 2) 转义剩下的内容
    text = escapeHtml(text);

    // 3) 行内代码
    text = text.replace(/`([^`\n]+)`/g, '<code>$1</code>');
    // 4) 加粗 / 斜体
    text = text.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>');
    text = text.replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>');
    // 5) 链接
    text = text.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');

    // 6) 按行处理块级元素
    const out = [];
    let listType = null;
    const closeList = () => { if (listType) { out.push(`</${listType}>`); listType = null; } };

    for (const raw of text.split('\n')) {
        const line = raw.replace(/\s+$/, '');
        let m;

        if (!line.trim()) { closeList(); continue; }
        if (/^\u0000BLOCK\d+\u0000$/.test(line.trim())) { closeList(); out.push(line.trim()); continue; }
        if ((m = line.match(/^###\s+(.*)$/))) { closeList(); out.push(`<h3>${m[1]}</h3>`); continue; }
        if ((m = line.match(/^##\s+(.*)$/))) { closeList(); out.push(`<h2>${m[1]}</h2>`); continue; }
        if ((m = line.match(/^#\s+(.*)$/))) { closeList(); out.push(`<h1>${m[1]}</h1>`); continue; }
        if (/^(-{3,}|\*{3,})$/.test(line.trim())) { closeList(); out.push('<hr>'); continue; }
        if ((m = line.match(/^&gt;\s?(.*)$/))) { closeList(); out.push(`<blockquote>${m[1]}</blockquote>`); continue; }
        if ((m = line.match(/^\s*[-*+]\s+(.*)$/))) {
            if (listType !== 'ul') { closeList(); out.push('<ul>'); listType = 'ul'; }
            out.push(`<li>${m[1]}</li>`); continue;
        }
        if ((m = line.match(/^\s*\d+[.)]\s+(.*)$/))) {
            if (listType !== 'ol') { closeList(); out.push('<ol>'); listType = 'ol'; }
            out.push(`<li>${m[1]}</li>`); continue;
        }

        closeList();
        out.push(`<p>${line}</p>`);
    }
    closeList();

    // 7) 把代码块塞回去
    return out.join('\n').replace(/\u0000BLOCK(\d+)\u0000/g, (m, i) => blocks[Number(i)]);
}
