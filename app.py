#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""ZeppLife 刷步数 Web 服务 — 启动后浏览器访问 http://127.0.0.1:5000"""

import logging
import threading
import time

from flask import Flask, jsonify, render_template_string, request

from zepp_client import ZeppClient, ZeppError

# ---------------------------------------------------------------------------
# 日志 & Flask
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("zepp_web")
app = Flask(__name__)

# Token 缓存：避免频繁登录触发限流
_token_cache = {}
_rate_limit_until = {}
_cache_lock = threading.Lock()
CACHE_TTL = 3600  # token 缓存 1 小时


def _get_cached_tokens(account: str) -> dict | None:
    with _cache_lock:
        entry = _token_cache.get(account)
        if entry and time.time() < entry["expires"]:
            return {"login_token": entry["login_token"], "app_token": entry["app_token"], "user_id": entry["user_id"]}
        return None


def _set_cached_tokens(account: str, login_token: str, app_token: str, user_id: str):
    with _cache_lock:
        _token_cache[account] = {
            "login_token": login_token,
            "app_token": app_token,
            "user_id": user_id,
            "expires": time.time() + CACHE_TTL,
        }


def zepp_submit(account: str, password: str, steps: int) -> dict:
    """Submit steps, re-authenticating once if a cached token has expired."""
    with _cache_lock:
        retry_at = _rate_limit_until.get(account, 0)
    retry_after = max(0, int(retry_at - time.time()))
    if retry_after:
        return {
            "ok": False,
            "error": f"请求过于频繁，请等待 {retry_after} 秒后再试",
            "retry_after": retry_after,
        }

    client = ZeppClient(logger=log)
    cached = _get_cached_tokens(account)

    for attempt in range(2):
        try:
            if cached:
                log.info("使用缓存 token，跳过登录")
                app_token = cached["app_token"]
                user_id = cached["user_id"]
            else:
                login_token, app_token, user_id = client.authenticate(account, password)
                _set_cached_tokens(account, login_token, app_token, user_id)

            return client.submit_steps(user_id, app_token, steps)
        except ZeppError as exc:
            if exc.auth_expired and cached and attempt == 0:
                with _cache_lock:
                    _token_cache.pop(account, None)
                cached = None
                log.info("缓存 token 已过期，正在重新登录")
                continue
            result = {"ok": False, "error": str(exc)}
            if exc.retry_after:
                with _cache_lock:
                    _rate_limit_until[account] = time.time() + exc.retry_after
                result["retry_after"] = exc.retry_after
            log.warning("提交失败: account=%s error=%s", account, exc)
            return result

    return {"ok": False, "error": "提交失败"}


# ---------------------------------------------------------------------------
# 前端页面
# ---------------------------------------------------------------------------

HTML_PAGE = r"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<title>ZeppLife 步数刷取</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  /* ===== Design Tokens ===== */
  :root {
    --bg-deep: #020203;
    --bg-base: #050506;
    --bg-elevated: #0a0a0c;
    --surface: rgba(255,255,255,0.04);
    --surface-hover: rgba(255,255,255,0.06);
    --foreground: #EDEDEF;
    --foreground-muted: #8A8F98;
    --accent: #22C55E;
    --accent-glow: rgba(34,197,94,0.18);
    --accent-soft: rgba(34,197,94,0.12);
    --danger: #EF4444;
    --danger-soft: rgba(239,68,68,0.12);
    --border: rgba(255,255,255,0.07);
    --border-focus: rgba(34,197,94,0.35);
    --radius-sm: 10px;
    --radius: 16px;
    --radius-lg: 20px;
    --easing: cubic-bezier(0.16,1,0.3,1);
    --font: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    --transition-fast: 150ms;
    --transition: 250ms;
  }

  /* ===== Reset & Base ===== */
  *, *::before, *::after { margin: 0; padding: 0; box-sizing: border-box; }
  html { -webkit-text-size-adjust: 100%; }
  body {
    font-family: var(--font);
    background: var(--bg-deep);
    color: var(--foreground);
    min-height: 100dvh;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 20px;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
    overflow-x: hidden;
  }
  /* Ambient light blobs */
  .bg-blobs {
    position: fixed; inset: 0; overflow: hidden; pointer-events: none; z-index: 0;
  }
  .bg-blob {
    position: absolute;
    border-radius: 50%;
    filter: blur(100px);
    opacity: 0.06;
    animation: blobFloat 12s ease-in-out infinite alternate;
  }
  .bg-blob:nth-child(1) {
    width: 600px; height: 600px;
    background: #22C55E;
    top: -200px; left: -150px;
    animation-delay: 0s;
  }
  .bg-blob:nth-child(2) {
    width: 500px; height: 500px;
    background: #16A34A;
    top: 50%; right: -200px;
    animation-delay: -4s;
    animation-duration: 15s;
  }
  .bg-blob:nth-child(3) {
    width: 400px; height: 400px;
    background: #4ade80;
    bottom: -150px; left: 30%;
    animation-delay: -8s;
    animation-duration: 18s;
    opacity: 0.04;
  }
  @keyframes blobFloat {
    0% { transform: translate(0,0) scale(1); }
    33% { transform: translate(60px,-40px) scale(1.12); }
    66% { transform: translate(-30px,30px) scale(0.92); }
    100% { transform: translate(-20px,-20px) scale(1.05); }
  }
  /* Subtle dot grid overlay */
  .dot-grid {
    position: fixed; inset: 0; pointer-events: none; z-index: 0;
    background-image: radial-gradient(rgba(255,255,255,0.03) 1px, transparent 1px);
    background-size: 28px 28px;
    mask-image: radial-gradient(ellipse 60% 60% at 50% 50%, black 30%, transparent 70%);
    -webkit-mask-image: radial-gradient(ellipse 60% 60% at 50% 50%, black 30%, transparent 70%);
  }

  /* ===== Container ===== */
  .container { position: relative; z-index: 1; width: 100%; max-width: 420px; }

  /* ===== Card — Glassmorphism ===== */
  .card {
    background: rgba(10,10,12,0.7);
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: var(--radius-lg);
    padding: 36px 28px 28px;
    backdrop-filter: blur(40px) saturate(200%);
    -webkit-backdrop-filter: blur(40px) saturate(200%);
    box-shadow:
      0 1px 0 rgba(255,255,255,0.03) inset,
      0 32px 80px rgba(0,0,0,0.6),
      0 0 0 1px rgba(255,255,255,0.02);
    position: relative;
  }
  /* Card subtle top highlight */
  .card::before {
    content: '';
    position: absolute; inset: 0;
    border-radius: var(--radius-lg);
    background: linear-gradient(180deg, rgba(255,255,255,0.02) 0%, transparent 40%);
    pointer-events: none;
  }

  /* ===== Logo ===== */
  .logo {
    text-align: center;
    margin-bottom: 30px;
  }
  .logo-icon {
    width: 56px; height: 56px;
    background: linear-gradient(135deg, #22C55E 0%, #16A34A 100%);
    border-radius: var(--radius);
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-size: 28px;
    margin-bottom: 12px;
    box-shadow:
      0 0 0 8px rgba(34,197,94,0.08),
      0 0 60px rgba(34,197,94,0.15),
      0 16px 40px rgba(34,197,94,0.25);
    position: relative;
  }
  .logo-icon::after {
    content: '';
    position: absolute; inset: -2px;
    border-radius: 18px;
    background: linear-gradient(135deg, rgba(34,197,94,0.4), transparent 60%);
    pointer-events: none;
  }
  .logo h1 {
    font-size: 22px;
    font-weight: 700;
    letter-spacing: -0.3px;
    color: var(--foreground);
  }
  .logo p {
    color: var(--foreground-muted);
    font-size: 13px;
    margin-top: 4px;
    font-weight: 400;
  }

  /* ===== Form ===== */
  .form-group { margin-bottom: 18px; }
  .form-group label:first-child {
    display: block;
    font-size: 12px;
    font-weight: 600;
    color: var(--foreground-muted);
    margin-bottom: 7px;
    text-transform: uppercase;
    letter-spacing: 0.6px;
  }
  .input-wrap { position: relative; }
  .form-group input[type="text"],
  .form-group input[type="password"],
  .form-group input[type="number"] {
    width: 100%;
    padding: 13px 16px;
    background: rgba(255,255,255,0.03);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    color: var(--foreground);
    font-size: 15px;
    font-family: var(--font);
    transition: all 0.25s var(--easing);
    outline: none;
  }
  .form-group input:hover {
    border-color: rgba(255,255,255,0.12);
    background: rgba(255,255,255,0.04);
  }
  .form-group input:focus {
    border-color: var(--accent);
    background: rgba(34,197,94,0.04);
    box-shadow: 0 0 0 4px var(--accent-glow), 0 0 20px rgba(34,197,94,0.05);
  }
  .form-group input::placeholder {
    color: rgba(138,143,152,0.5);
  }

  /* ===== Step Presets ===== */
  .presets {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 8px;
    margin-bottom: 10px;
  }
  .presets button {
    padding: 10px 0;
    background: rgba(255,255,255,0.03);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    color: var(--foreground-muted);
    font-size: 13px;
    font-weight: 500;
    font-family: var(--font);
    font-variant-numeric: tabular-nums;
    cursor: pointer;
    transition: all 0.2s var(--easing);
    user-select: none;
    -webkit-tap-highlight-color: transparent;
    touch-action: manipulation;
    backdrop-filter: blur(8px);
    -webkit-backdrop-filter: blur(8px);
  }
  .presets button:hover {
    border-color: rgba(255,255,255,0.15);
    color: var(--foreground);
    background: rgba(255,255,255,0.06);
    transform: translateY(-1px);
  }
  .presets button:active {
    transform: scale(0.95);
    transition: transform 80ms var(--easing);
  }
  .presets button.preset-active {
    border-color: var(--accent);
    color: var(--accent);
    background: rgba(34,197,94,0.08);
    font-weight: 600;
    box-shadow: 0 0 12px rgba(34,197,94,0.1);
  }

  /* ===== Save Toggle ===== */
  .save-toggle {
    display: flex; align-items: center; gap: 8px;
    margin-top: 10px;
    font-size: 12px; color: var(--foreground-muted);
    cursor: pointer; user-select: none;
    transition: color var(--transition-fast) var(--easing);
  }
  .save-toggle:hover { color: var(--foreground); }
  .save-toggle input[type=checkbox] {
    width: 18px; height: 18px;
    accent-color: var(--accent); cursor: pointer;
    border-radius: 4px;
  }

  /* ===== Submit Button ===== */
  .btn-submit {
    width: 100%;
    padding: 15px 24px;
    background: linear-gradient(135deg, #22C55E 0%, #16A34A 100%);
    border: none;
    border-radius: var(--radius);
    color: #fff;
    font-size: 16px;
    font-weight: 600;
    font-family: var(--font);
    cursor: pointer;
    margin-top: 6px;
    position: relative;
    overflow: hidden;
    transition: all var(--transition) var(--easing);
    -webkit-tap-highlight-color: transparent;
    touch-action: manipulation;
    box-shadow:
      0 0 0 0 rgba(34,197,94,0.4),
      0 4px 20px rgba(34,197,94,0.3);
    animation: btnPulse 3s ease-in-out infinite;
  }
  @keyframes btnPulse {
    0%, 100% { box-shadow: 0 0 0 0 rgba(34,197,94,0.4), 0 4px 20px rgba(34,197,94,0.3); }
    50% { box-shadow: 0 0 0 8px rgba(34,197,94,0), 0 4px 28px rgba(34,197,94,0.5); }
  }
  .btn-submit:hover:not(:disabled) {
    transform: translateY(-2px);
    box-shadow: 0 8px 28px rgba(34,197,94,0.4);
  }
  .btn-submit:active:not(:disabled) {
    transform: scale(0.97);
    transition: transform 80ms var(--easing);
  }
  .btn-submit:disabled {
    opacity: 0.55;
    cursor: not-allowed;
    transform: none;
    filter: grayscale(0.3);
  }
  .btn-submit:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 3px;
  }

  /* Button loading state */
  .btn-submit.loading {
    background: var(--surface);
    color: transparent;
    pointer-events: none;
    box-shadow: none;
  }
  .btn-submit.loading::before {
    content: '';
    position: absolute;
    inset: 0;
    background: linear-gradient(90deg, transparent, rgba(255,255,255,0.06), transparent);
    animation: shimmer 1.5s infinite;
  }
  .btn-submit .spinner {
    display: none;
  }
  .btn-submit.loading .spinner {
    display: flex;
    position: absolute;
    inset: 0;
    align-items: center;
    justify-content: center;
    gap: 10px;
  }
  .btn-submit.loading .spinner-text {
    color: var(--foreground-muted);
    font-size: 14px;
    font-weight: 500;
  }
  .spinner-ring {
    width: 20px; height: 20px;
    border: 2px solid rgba(255,255,255,0.15);
    border-top-color: var(--accent);
    border-radius: 50%;
    animation: spin 0.7s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  @keyframes shimmer {
    0% { transform: translateX(-100%); }
    100% { transform: translateX(100%); }
  }

  /* ===== Result ===== */
  .result {
    margin-top: 18px;
    padding: 14px 18px;
    border-radius: var(--radius-sm);
    font-size: 14px;
    font-weight: 500;
    display: none;
    animation: slideUp var(--transition) var(--easing);
    align-items: flex-start;
    gap: 10px;
  }
  .result.show { display: flex; }
  .result.success {
    background: var(--accent-soft);
    border: 1px solid rgba(34,197,94,0.25);
    color: #6ee7b7;
  }
  .result.error {
    background: var(--danger-soft);
    border: 1px solid rgba(239,68,68,0.25);
    color: #fca5a5;
  }
  .result-icon { font-size: 20px; flex-shrink: 0; margin-top: 1px; }
  .result-body { flex: 1; min-width: 0; }
  .result-msg { font-weight: 600; }
  .result-detail { margin-top: 4px; font-size: 12px; opacity: 0.7; line-height: 1.4; }
  .result-retry {
    display: inline-block; margin-top: 6px; font-size: 12px;
    color: var(--accent); cursor: pointer; font-weight: 600;
    text-decoration: underline; text-underline-offset: 2px;
    background: none; border: none; padding: 0;
    font-family: var(--font);
    transition: color var(--transition-fast);
  }
  .result-retry:hover { color: #4ade80; }

  @keyframes slideUp {
    from { opacity: 0; transform: translateY(10px); }
    to   { opacity: 1; transform: translateY(0); }
  }

  /* Success checkmark animation */
  .checkmark {
    width: 22px; height: 22px;
    border-radius: 50%;
    background: var(--accent);
    flex-shrink: 0;
    position: relative;
    animation: popIn 0.4s var(--easing);
  }
  .checkmark::after {
    content: '';
    position: absolute;
    left: 7px; top: 4px;
    width: 7px; height: 11px;
    border: solid #fff;
    border-width: 0 2px 2px 0;
    transform: rotate(45deg);
    animation: drawCheck 0.3s 0.1s var(--easing) both;
  }
  @keyframes popIn {
    0% { transform: scale(0); }
    60% { transform: scale(1.15); }
    100% { transform: scale(1); }
  }
  @keyframes drawCheck {
    from { clip-path: inset(0 100% 0 0); }
    to   { clip-path: inset(0 0 0 0); }
  }

  /* ===== History ===== */
  .history { margin-top: 28px; }
  .history-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 12px;
  }
  .history-header h3 {
    font-size: 13px;
    font-weight: 600;
    color: var(--foreground-muted);
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }
  .clear-btn {
    background: none; border: none;
    color: var(--foreground-muted);
    cursor: pointer; font-size: 12px;
    font-family: var(--font);
    padding: 4px 10px;
    border-radius: 6px;
    transition: all var(--transition-fast) var(--easing);
  }
  .clear-btn:hover { color: var(--foreground); background: var(--surface-hover); }
  .history-list {
    list-style: none;
    max-height: 220px;
    overflow-y: auto;
    scrollbar-width: thin;
    scrollbar-color: var(--border) transparent;
  }
  .history-list::-webkit-scrollbar { width: 4px; }
  .history-list::-webkit-scrollbar-track { background: transparent; }
  .history-list::-webkit-scrollbar-thumb {
    background: var(--border);
    border-radius: 4px;
  }
  .history-item {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 12px 14px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    margin-bottom: 6px;
    font-size: 13px;
    transition: all var(--transition-fast) var(--easing);
  }
  .history-item:hover { background: var(--surface-hover); }
  .history-item.ok { border-left: 3px solid var(--accent); }
  .history-item.fail { border-left: 3px solid var(--danger); }
  .history-left { display: flex; align-items: center; gap: 10px; }
  .history-steps {
    font-weight: 600;
    font-variant-numeric: tabular-nums;
    color: var(--foreground);
  }
  .history-time { color: var(--foreground-muted); font-size: 11px; }
  .history-badge {
    font-size: 11px; font-weight: 600;
    padding: 3px 10px; border-radius: 20px;
    letter-spacing: 0.3px;
  }
  .history-badge.ok { background: var(--accent-soft); color: #6ee7b7; }
  .history-badge.fail { background: var(--danger-soft); color: #fca5a5; }
  .history-empty {
    text-align: center; padding: 28px 0;
    color: var(--foreground-muted); font-size: 13px;
  }

  /* ===== Motion: reduced ===== */
  @media (prefers-reduced-motion: reduce) {
    *, *::before, *::after {
      animation-duration: 0.01ms !important;
      animation-iteration-count: 1 !important;
      transition-duration: 0.01ms !important;
    }
  }
</style>
</head>
<body>
<div class="bg-blobs">
  <div class="bg-blob"></div>
  <div class="bg-blob"></div>
  <div class="bg-blob"></div>
</div>
<div class="dot-grid"></div>
<div class="container">
  <div class="card">
    <!-- Logo -->
    <div class="logo">
      <div class="logo-icon">
        <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M19 17.8c1.5-2.3 2.2-5.1 1.7-8-.5-2.8-2.2-5.1-4.5-6.3-2.3-1.2-5-1.1-7.2.2"/>
          <ellipse cx="12" cy="16" rx="7" ry="3"/>
          <path d="M12 13v6"/>
          <path d="M12 13c-3.9 0-7-1.3-7-3s3.1-3 7-3 7 1.3 7 3-3.1 3-7 3"/>
        </svg>
      </div>
      <h1>ZeppLife Steps</h1>
      <p>微信运动 · 支付宝运动同步</p>
    </div>

    <!-- Account -->
    <div class="form-group">
      <label for="account">账号</label>
      <input type="text" id="account" placeholder="手机号或邮箱" autocomplete="username" inputmode="email">
    </div>

    <!-- Password -->
    <div class="form-group">
      <label for="password">密码</label>
      <input type="password" id="password" placeholder="ZeppLife 登录密码" autocomplete="current-password">
      <label class="save-toggle" for="saveCheck">
        <input type="checkbox" id="saveCheck" checked>
        <span>记住账号密码</span>
      </label>
    </div>

    <!-- Steps -->
    <div class="form-group">
      <label for="steps">目标步数</label>
      <div class="presets" id="presets">
        <button type="button" data-steps="18888">18,888</button>
        <button type="button" data-steps="25000">25,000</button>
        <button type="button" data-steps="32869">32,869</button>
        <button type="button" data-steps="random">🎲 随机</button>
      </div>
      <input type="number" id="steps" placeholder="输入步数" value="25000" min="1" max="98800" inputmode="numeric">
    </div>

    <!-- Submit -->
    <button class="btn-submit" id="submitBtn" onclick="submitSteps()">
      <span class="btn-label">提交步数</span>
      <span class="spinner">
        <span class="spinner-ring"></span>
        <span class="spinner-text">提交中...</span>
      </span>
    </button>

    <!-- Result -->
    <div class="result" id="result" role="alert" aria-live="polite">
      <span class="result-icon"></span>
      <div class="result-body">
        <div class="result-msg"></div>
        <div class="result-detail"></div>
      </div>
    </div>

    <!-- History -->
    <div class="history">
      <div class="history-header">
        <h3>提交记录</h3>
        <button class="clear-btn" onclick="clearHistory()" aria-label="清空历史记录">清空</button>
      </div>
      <ul class="history-list" id="historyList" role="list" aria-label="提交历史">
        <li class="history-empty">暂无记录</li>
      </ul>
    </div>
  </div>
</div>

<script>
const API = '/api/submit';
const STORAGE_KEY = 'zepp_credentials';

// ---- Presets ----
const presetButtons = document.querySelectorAll('#presets button');
const stepsInput = document.getElementById('steps');

function setSteps(v) {
  stepsInput.value = v;
  highlightPreset(v);
}
function randomSteps() {
  const v = Math.floor(Math.random() * (38000 - 15000 + 1)) + 15000;
  stepsInput.value = v;
  highlightPreset('random');
}
function highlightPreset(val) {
  presetButtons.forEach(b => {
    const ds = b.dataset.steps;
    if ((ds === 'random' && val === 'random') || Number(ds) === Number(val)) {
      b.classList.add('preset-active');
    } else {
      b.classList.remove('preset-active');
    }
  });
}

presetButtons.forEach(b => {
  b.addEventListener('click', () => {
    const ds = b.dataset.steps;
    if (ds === 'random') randomSteps();
    else setSteps(Number(ds));
  });
});

stepsInput.addEventListener('input', () => highlightPreset(stepsInput.value));

// ---- Credentials ----
function saveCredentials(account, password, steps) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ account, password, steps }));
  } catch(e) {}
}
function loadCredentials() {
  try {
    const data = JSON.parse(localStorage.getItem(STORAGE_KEY));
    if (data) {
      document.getElementById('account').value = data.account || '';
      document.getElementById('password').value = data.password || '';
      if (data.steps) {
        stepsInput.value = data.steps;
        highlightPreset(Number(data.steps));
      }
      document.getElementById('saveCheck').checked = true;
    }
  } catch(e) {}
}
function clearCredentials() {
  localStorage.removeItem(STORAGE_KEY);
  document.getElementById('account').value = '';
  document.getElementById('password').value = '';
  document.getElementById('saveCheck').checked = false;
}

// ---- History ----
function loadHistory() {
  try { return JSON.parse(localStorage.getItem('zepp_history') || '[]'); }
  catch { return []; }
}
function saveHistory(h) { localStorage.setItem('zepp_history', JSON.stringify(h)); }
function clearHistory() {
  localStorage.removeItem('zepp_history');
  renderHistory();
}

function renderHistory() {
  const list = document.getElementById('historyList');
  const history = loadHistory();
  if (!history.length) {
    list.innerHTML = '<li class="history-empty">暂无记录</li>';
    return;
  }
  list.innerHTML = history.slice().reverse().map(h => `
    <li class="history-item ${h.ok ? 'ok' : 'fail'}" role="listitem">
      <div class="history-left">
        <span class="history-steps">${h.steps.toLocaleString()}</span>
        <span class="history-time">${h.time}</span>
      </div>
      <span class="history-badge ${h.ok ? 'ok' : 'fail'}">
        ${h.ok ? '✓ 成功' : '✗ 失败'}
      </span>
    </li>
  `).join('');
}

// ---- Submit ----
let submitting = false;
let cooldownTimer = null;
let cooldownUntil = 0;

async function submitSteps() {
  if (submitting) return;
  const cooldownRemaining = Math.ceil((cooldownUntil - Date.now()) / 1000);
  if (cooldownRemaining > 0) {
    showResult(false, '请求过于频繁', `请等待 ${cooldownRemaining} 秒后再试`);
    return;
  }
  const account = document.getElementById('account').value.trim();
  const password = document.getElementById('password').value;
  const steps = parseInt(stepsInput.value, 10);
  const btn = document.getElementById('submitBtn');
  const result = document.getElementById('result');

  // Validate
  if (!account) { showResult(false, '请输入账号', '手机号或邮箱不能为空'); return; }
  if (!password) { showResult(false, '请输入密码', '密码不能为空'); return; }
  if (!steps || steps < 1 || steps > 98800) {
    showResult(false, '步数不合法', '请输入 1 ~ 98,800 之间的步数'); return;
  }

  // Set loading
  submitting = true;
  btn.classList.add('loading');
  btn.setAttribute('aria-busy', 'true');
  result.className = 'result';
  result.style.display = 'none';

  try {
    const resp = await fetch(API, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ account, password, steps })
    });
    const data = await resp.json();

    if (data.ok) {
      showResult(true,
        `步数提交成功`,
        `已同步 ${data.steps.toLocaleString()} 步到微信运动`
      );
      if (document.getElementById('saveCheck').checked) {
        saveCredentials(account, password, steps);
      }
      highlightPreset(steps);
    } else {
      const isRateLimit = data.error && data.error.includes('频繁');
      showResult(false,
        '提交失败',
        data.error || '未知错误',
        !isRateLimit
      );
      if (isRateLimit) {
        startCooldown(Number(data.retry_after) || 120);
      }
    }

    // Save history
    const history = loadHistory();
    history.push({
      steps, ok: data.ok,
      time: new Date().toLocaleString('zh-CN', { hour12: false }),
      error: data.error || ''
    });
    if (history.length > 50) history.splice(0, history.length - 50);
    saveHistory(history);
    renderHistory();
  } catch (e) {
    showResult(false,
      '网络错误',
      '无法连接到本地服务，请确认已启动 app.py',
      true
    );
  } finally {
    submitting = false;
    btn.classList.remove('loading');
    btn.setAttribute('aria-busy', 'false');
  }
}

function showResult(ok, msg, detail, showRetry) {
  const el = document.getElementById('result');
  const iconEl = el.querySelector('.result-icon');
  const msgEl = el.querySelector('.result-msg');
  const detailEl = el.querySelector('.result-detail');

  // 清除旧的倒计时
  if (el._retryTimer) { clearInterval(el._retryTimer); el._retryTimer = null; }

  el.className = 'result show ' + (ok ? 'success' : 'error');
  iconEl.innerHTML = ok
    ? '<span class="checkmark"></span>'
    : '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>';
  msgEl.textContent = msg;
  detailEl.textContent = detail;
  if (showRetry) {
    const retryButton = document.createElement('button');
    retryButton.className = 'result-retry';
    retryButton.textContent = '重试';
    retryButton.addEventListener('click', submitSteps);
    detailEl.append(' ', retryButton);
  }
  el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function startCooldown(seconds) {
  const detailEl = document.querySelector('.result-detail');
  const btn = document.getElementById('submitBtn');
  const label = btn.querySelector('.btn-label');
  cooldownUntil = Date.now() + seconds * 1000;

  const update = () => {
    const remaining = Math.ceil((cooldownUntil - Date.now()) / 1000);
    if (remaining <= 0) {
      clearInterval(cooldownTimer);
      cooldownTimer = null;
      cooldownUntil = 0;
      btn.disabled = false;
      label.textContent = '提交步数';
      detailEl.textContent = '现在可以重新提交';
    } else {
      btn.disabled = true;
      label.textContent = `${remaining} 秒后重试`;
      detailEl.textContent = `接口正在限流，请等待 ${remaining} 秒后手动重试`;
    }
  };
  clearInterval(cooldownTimer);
  update();
  cooldownTimer = setInterval(update, 1000);
}

// ---- Init ----
loadCredentials();
renderHistory();

// Enter to submit
document.addEventListener('keydown', e => {
  if (e.key === 'Enter' && document.activeElement && document.activeElement.tagName === 'INPUT') {
    e.preventDefault();
    submitSteps();
  }
});
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------


@app.route("/")
def index():
    return render_template_string(HTML_PAGE)


@app.route("/api/submit", methods=["POST"])
def api_submit():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"ok": False, "error": "请求数据为空"}), 400

    account = (data.get("account") or "").strip()
    password = data.get("password") or ""
    steps = data.get("steps")

    if not account or not password:
        return jsonify({"ok": False, "error": "账号和密码不能为空"}), 400
    try:
        steps = int(steps)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "步数格式不正确"}), 400
    if steps < 1 or steps > 98800:
        return jsonify({"ok": False, "error": "步数需在 1~98800 之间"}), 400

    log.info("收到请求: account=%s steps=%d", account, steps)
    result = zepp_submit(account, password, steps)
    return jsonify(result)


# ---------------------------------------------------------------------------
# 启动
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print()
    print("=" * 52)
    print("  👟 ZeppLife 刷步数 Web 服务")
    print("  打开浏览器访问: http://127.0.0.1:5000")
    print("=" * 52)
    print()
    app.run(host="127.0.0.1", port=5000, debug=False)
