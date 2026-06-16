const USER_AGENT = "MiFit/6.12.0 (MCE16; Android 16; Density/1.5)";
const APP_NAME = "com.xiaomi.hm.health";
const DEVICE_ID = "00:00:00:00:00:00";
const DATA_DEVICE_ID = "0000000000000000";
const API_USER = "https://api-user.huami.com";
const API_ACCOUNT = "https://account.huami.com";
const API_ACCOUNT_CN = "https://account-cn.huami.com";
const API_MIFIT_CN = "https://api-mifit-cn.huami.com";

const SESSION_SECONDS = 30 * 24 * 60 * 60;
const ACTION_COOLDOWN_SECONDS = 30 * 60;
const UPSTREAM_TIMEOUT_MS = 15000;
const SCHEDULE_CATCHUP_MINUTES = 180;
const STALE_RUN_SECONDS = 5 * 60;
const SECURITY_HEADERS = {
  "Content-Security-Policy": [
    "default-src 'self'",
    "script-src 'self' 'unsafe-inline' https://challenges.cloudflare.com",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data:",
    "connect-src 'self' https://challenges.cloudflare.com",
    "frame-src https://challenges.cloudflare.com",
    "base-uri 'none'",
    "frame-ancestors 'none'",
    "form-action 'self'"
  ].join("; "),
  "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
  "Referrer-Policy": "same-origin",
  "Strict-Transport-Security": "max-age=31536000; includeSubDomains; preload",
  "X-Content-Type-Options": "nosniff",
  "X-Frame-Options": "DENY"
};
const encoder = new TextEncoder();
const decoder = new TextDecoder();

class AppError extends Error {
  constructor(message, status = 400, options = {}) {
    super(message);
    this.name = "AppError";
    this.status = status;
    this.retryAfter = options.retryAfter || null;
  }
}

function json(data, status = 200, headers = {}) {
  return Response.json(data, {
    status,
    headers: {
      ...SECURITY_HEADERS,
      "Cache-Control": "no-store",
      ...headers
    }
  });
}

function withSecurityHeaders(response) {
  const next = new Response(response.body, response);
  for (const [key, value] of Object.entries(SECURITY_HEADERS)) {
    next.headers.set(key, value);
  }
  next.headers.set("Cache-Control", "public, max-age=0, must-revalidate");
  return next;
}

function bytesToBase64(bytes) {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

function base64ToBytes(value) {
  const binary = atob(value);
  return Uint8Array.from(binary, (char) => char.charCodeAt(0));
}

function randomBase64(length) {
  const bytes = new Uint8Array(length);
  crypto.getRandomValues(bytes);
  return bytesToBase64(bytes);
}

function randomBase64Url(length) {
  const bytes = new Uint8Array(length);
  crypto.getRandomValues(bytes);
  return bytesToBase64(bytes)
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/g, "");
}

function bytesToBase64Url(bytes) {
  return bytesToBase64(bytes)
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/g, "");
}

function base64UrlToBytes(value) {
  const base64 = String(value || "")
    .replace(/-/g, "+")
    .replace(/_/g, "/")
    .padEnd(Math.ceil(String(value || "").length / 4) * 4, "=");
  return base64ToBytes(base64);
}

async function sha256(value) {
  const digest = await crypto.subtle.digest("SHA-256", encoder.encode(value));
  return bytesToBase64(new Uint8Array(digest));
}

async function credentialKey(env) {
  if (!env.CREDENTIAL_ENCRYPTION_KEY) {
    throw new AppError("服务缺少凭据加密密钥", 500);
  }
  const raw = base64ToBytes(env.CREDENTIAL_ENCRYPTION_KEY);
  if (raw.length !== 32) {
    throw new AppError("凭据加密密钥格式无效", 500);
  }
  return crypto.subtle.importKey("raw", raw, "AES-GCM", false, [
    "encrypt",
    "decrypt"
  ]);
}

async function signingKey(env) {
  if (!env.CREDENTIAL_ENCRYPTION_KEY) {
    throw new AppError("服务缺少签名密钥", 500);
  }
  const raw = base64ToBytes(env.CREDENTIAL_ENCRYPTION_KEY);
  if (raw.length !== 32) {
    throw new AppError("签名密钥格式无效", 500);
  }
  return crypto.subtle.importKey(
    "raw",
    raw,
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign", "verify"]
  );
}

async function signValue(env, value) {
  const signature = await crypto.subtle.sign(
    "HMAC",
    await signingKey(env),
    encoder.encode(value)
  );
  return bytesToBase64Url(new Uint8Array(signature));
}

async function verifySignature(env, value, signature) {
  try {
    return await crypto.subtle.verify(
      "HMAC",
      await signingKey(env),
      base64UrlToBytes(signature),
      encoder.encode(value)
    );
  } catch {
    return false;
  }
}

async function encryptCredential(value, env) {
  const iv = new Uint8Array(12);
  crypto.getRandomValues(iv);
  const encrypted = await crypto.subtle.encrypt(
    { name: "AES-GCM", iv },
    await credentialKey(env),
    encoder.encode(value)
  );
  return `${bytesToBase64(iv)}.${bytesToBase64(new Uint8Array(encrypted))}`;
}

async function decryptCredential(value, env) {
  const [ivValue, encryptedValue] = String(value || "").split(".");
  if (!ivValue || !encryptedValue) {
    throw new AppError("保存的 Zepp 凭据无效", 500);
  }
  try {
    const decrypted = await crypto.subtle.decrypt(
      { name: "AES-GCM", iv: base64ToBytes(ivValue) },
      await credentialKey(env),
      base64ToBytes(encryptedValue)
    );
    return decoder.decode(decrypted);
  } catch {
    throw new AppError("无法解密 Zepp 凭据", 500);
  }
}

function cookieValue(request, name) {
  const cookie = request.headers.get("Cookie") || "";
  for (const item of cookie.split(";")) {
    const [key, ...parts] = item.trim().split("=");
    if (key === name) return decodeURIComponent(parts.join("="));
  }
  return null;
}

function sessionCookie(token) {
  return [
    `zepp_session=${encodeURIComponent(token)}`,
    "Path=/",
    `Max-Age=${SESSION_SECONDS}`,
    "HttpOnly",
    "Secure",
    "SameSite=Lax"
  ].join("; ");
}

function clearSessionCookie() {
  return "zepp_session=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Lax";
}

function assertSameOrigin(request) {
  if (!["POST", "PUT", "PATCH", "DELETE"].includes(request.method)) return;
  const origin = request.headers.get("Origin");
  if (origin && origin !== new URL(request.url).origin) {
    throw new AppError("请求来源无效", 403);
  }
}

async function parseJson(request) {
  try {
    return await request.json();
  } catch {
    throw new AppError("请求 JSON 无效");
  }
}

function turnstileConfigured(env) {
  return Boolean(env.TURNSTILE_SITE_KEY && env.TURNSTILE_SECRET_KEY);
}

async function createLocalCaptcha(env) {
  const left = 10 + Math.floor(Math.random() * 40);
  const right = 1 + Math.floor(Math.random() * 30);
  const expiresAt = Math.floor(Date.now() / 1000) + 5 * 60;
  const nonce = randomBase64Url(12);
  const payload = `${left}.${right}.${expiresAt}.${nonce}`;
  const signature = await signValue(env, payload);
  return {
    question: `${left} + ${right} = ?`,
    token: `${payload}.${signature}`,
    expires_at: expiresAt
  };
}

async function verifyLocalCaptcha(env, token, answer) {
  const parts = String(token || "").split(".");
  if (parts.length !== 5) {
    throw new AppError("本地验证码无效，请刷新后重试");
  }
  const [leftValue, rightValue, expiresValue, nonce, signature] = parts;
  const left = Number(leftValue);
  const right = Number(rightValue);
  const expiresAt = Number(expiresValue);
  const submitted = Number(answer);
  if (
    !Number.isInteger(left) ||
    !Number.isInteger(right) ||
    !Number.isInteger(expiresAt) ||
    !Number.isInteger(submitted) ||
    !nonce
  ) {
    throw new AppError("本地验证码无效，请刷新后重试");
  }
  if (expiresAt < Math.floor(Date.now() / 1000)) {
    throw new AppError("本地验证码已过期，请刷新后重试");
  }
  const payload = `${left}.${right}.${expiresAt}.${nonce}`;
  if (!(await verifySignature(env, payload, signature))) {
    throw new AppError("本地验证码签名无效，请刷新后重试", 403);
  }
  if (submitted !== left + right) {
    throw new AppError("本地验证码答案错误");
  }
}

async function verifyTurnstile(request, env, token) {
  if (!env.TURNSTILE_SITE_KEY && !env.TURNSTILE_SECRET_KEY) return;
  if (!env.TURNSTILE_SITE_KEY || !env.TURNSTILE_SECRET_KEY) {
    throw new AppError("Turnstile 防爬虫配置不完整", 500);
  }
  if (!token || typeof token !== "string") {
    throw new AppError("请先完成人机验证");
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), UPSTREAM_TIMEOUT_MS);
  let response;
  try {
    const form = new FormData();
    form.set("secret", env.TURNSTILE_SECRET_KEY);
    form.set("response", token);
    const ip = request.headers.get("CF-Connecting-IP");
    if (ip) form.set("remoteip", ip);
    response = await fetch(
      "https://challenges.cloudflare.com/turnstile/v0/siteverify",
      { method: "POST", body: form, signal: controller.signal }
    );
  } catch (error) {
    if (controller.signal.aborted) {
      throw new AppError("人机验证超时，请重试", 504);
    }
    throw new AppError(`人机验证请求失败：${error?.message || "未知错误"}`, 502);
  } finally {
    clearTimeout(timer);
  }

  const result = await response.json().catch(() => null);
  if (!response.ok || !result?.success) {
    throw new AppError("人机验证未通过，请刷新后重试", 403);
  }

  const hostname = result.hostname || "";
  const allowedHostnames = new Set([
    "steps.zhhcnl.com",
    "zepp-step-tool.zhangzhihao-worldcup-2026.workers.dev"
  ]);
  if (hostname && !allowedHostnames.has(hostname)) {
    throw new AppError("人机验证来源无效", 403);
  }
}

async function verifyLoginChallenge(request, env, data) {
  if (data.captchaToken || data.captchaAnswer) {
    await verifyLocalCaptcha(env, data.captchaToken, data.captchaAnswer);
    return;
  }
  await verifyTurnstile(request, env, data.turnstileToken);
}

async function currentUser(request, env, required = true) {
  const token = cookieValue(request, "zepp_session");
  if (!token) {
    if (required) throw new AppError("请先登录", 401);
    return null;
  }
  const tokenHash = await sha256(token);
  const now = Math.floor(Date.now() / 1000);
  const user = await env.DB.prepare(
    `SELECT users.id, profiles.zepp_account
     FROM sessions
     JOIN users ON users.id = sessions.user_id
     JOIN profiles ON profiles.user_id = users.id
     WHERE sessions.token_hash = ? AND sessions.expires_at > ?`
  ).bind(tokenHash, now).first();
  if (!user && required) throw new AppError("登录已过期，请重新登录", 401);
  return user || null;
}

async function createSession(userId, env) {
  const token = randomBase64(32);
  const tokenHash = await sha256(token);
  const now = Math.floor(Date.now() / 1000);
  await env.DB.prepare(
    "INSERT INTO sessions (token_hash, user_id, expires_at, created_at) VALUES (?, ?, ?, ?)"
  ).bind(tokenHash, userId, now + SESSION_SECONDS, now).run();
  return token;
}

async function enforceRateLimit(request, env, key, limit, windowSeconds) {
  const now = Math.floor(Date.now() / 1000);
  const window = Math.floor(now / windowSeconds);
  const ip = request.headers.get("CF-Connecting-IP") || "unknown";
  const bucketKey = key.startsWith("user:")
    ? `${key}:${window}`
    : `${ip}:${key}:${window}`;
  await env.DB.prepare(
    `INSERT INTO auth_rate_limits (bucket_key, attempts, expires_at)
     VALUES (?, 1, ?)
     ON CONFLICT(bucket_key) DO UPDATE SET attempts = attempts + 1`
  ).bind(bucketKey, (window + 1) * windowSeconds).run();
  const bucket = await env.DB.prepare(
    "SELECT attempts FROM auth_rate_limits WHERE bucket_key = ?"
  ).bind(bucketKey).first();
  if (Number(bucket?.attempts) > limit) {
    const retryAfter = (window + 1) * windowSeconds - now;
    throw new AppError("请求过于频繁，请稍后再试", 429, { retryAfter });
  }
}

function validateSteps(value, label = "步数") {
  const steps = Number(value);
  if (!Number.isInteger(steps) || steps < 1 || steps > 98000) {
    throw new AppError(`${label}需在 1～98,000 之间`);
  }
  return steps;
}

function cooldownMessage(action, seconds) {
  const minutes = Math.ceil(seconds / 60);
  return `${action}冷却中，请等待约 ${minutes} 分钟后再试`;
}

async function claimCooldown(env, userId, column, action) {
  const now = Math.floor(Date.now() / 1000);
  const until = now + ACTION_COOLDOWN_SECONDS;
  const result = await env.DB.prepare(
    `UPDATE profiles
     SET ${column} = ?
     WHERE user_id = ? AND ${column} <= ?`
  ).bind(until, userId, now).run();
  if (result.meta.changes) return until;

  const profile = await env.DB.prepare(
    `SELECT ${column} AS cooldown_until FROM profiles WHERE user_id = ?`
  ).bind(userId).first();
  const remaining = Math.max(1, Number(profile?.cooldown_until || 0) - now);
  throw new AppError(cooldownMessage(action, remaining), 429, {
    retryAfter: remaining
  });
}

function loginIdentity(account) {
  if (/^1\d{10}$/.test(account)) return [`+86${account}`, "huami_phone"];
  return [account, "huami"];
}

async function readUpstreamJson(response, action) {
  const text = await response.text();
  try {
    const body = JSON.parse(text);
    if (!body || Array.isArray(body) || typeof body !== "object") throw new Error();
    return body;
  } catch {
    throw new AppError(`${action}失败：服务器返回了无效响应`, 502);
  }
}

async function upstreamFetch(url, options = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), UPSTREAM_TIMEOUT_MS);
  try {
    return await fetch(url, {
      ...options,
      signal: controller.signal
    });
  } catch (error) {
    if (controller.signal.aborted) {
      throw new AppError("Zepp 请求超时，请稍后再试", 504);
    }
    throw new AppError(`Zepp 网络请求失败：${error?.message || "未知错误"}`, 502);
  } finally {
    clearTimeout(timer);
  }
}

async function authenticateZepp(account, password) {
  const [loginName, thirdName] = loginIdentity(account);
  const headers = {
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "User-Agent": USER_AGENT,
    "app_name": APP_NAME
  };
  const firstResponse = await upstreamFetch(
    `${API_USER}/registrations/${encodeURIComponent(loginName)}/tokens`,
    {
      method: "POST",
      headers,
      body: new URLSearchParams({
        client_id: "HuaMi",
        country_code: "CN",
        json_response: "true",
        name: loginName,
        password,
        redirect_uri: "https://s3-us-west-2.amazonaws.com/hm-registration/successsignin.html",
        state: "REDIRECTION",
        token: "access"
      })
    }
  );
  if (firstResponse.status === 429) {
    const parsed = Number(firstResponse.headers.get("Retry-After"));
    const retryAfter = Number.isFinite(parsed) && parsed > 0 ? parsed : 120;
    throw new AppError(
      `请求过于频繁，请等待 ${retryAfter} 秒后再试`,
      429,
      { retryAfter }
    );
  }
  if (!firstResponse.ok) {
    throw new AppError(`Zepp 登录失败 (HTTP ${firstResponse.status})`, 502);
  }
  const firstBody = await readUpstreamJson(firstResponse, "Zepp 登录");
  if (!firstBody.access) throw new AppError("Zepp 用户名或密码不正确");

  const secondResponse = await upstreamFetch(`${API_ACCOUNT}/v2/client/login`, {
    method: "POST",
    headers,
    body: new URLSearchParams({
      app_name: APP_NAME,
      country_code: "CN",
      code: firstBody.access,
      device_id: DEVICE_ID,
      device_model: "android_phone",
      app_version: "6.12.0",
      grant_type: "access_token",
      allow_registration: "false",
      source: APP_NAME,
      third_name: thirdName
    })
  });
  if (!secondResponse.ok) {
    throw new AppError(`Zepp 登录第二步失败 (HTTP ${secondResponse.status})`, 502);
  }
  const secondBody = await readUpstreamJson(secondResponse, "Zepp 登录");
  const loginToken = secondBody.token_info?.login_token;
  const userId = secondBody.token_info?.user_id;
  if (!loginToken || !userId) throw new AppError("Zepp 登录响应缺少 token", 502);

  const tokenUrl = new URL(`${API_ACCOUNT_CN}/v1/client/app_tokens`);
  tokenUrl.searchParams.set("login_token", loginToken);
  const tokenResponse = await upstreamFetch(tokenUrl, {
    headers: { "User-Agent": USER_AGENT, "app_name": APP_NAME }
  });
  if (!tokenResponse.ok) {
    throw new AppError(`获取 Zepp app_token 失败 (HTTP ${tokenResponse.status})`, 502);
  }
  const tokenBody = await readUpstreamJson(tokenResponse, "获取 Zepp app_token");
  const appToken = tokenBody.token_info?.app_token;
  if (!appToken) throw new AppError("Zepp 响应缺少 app_token", 502);
  return { appToken: String(appToken), userId: String(userId) };
}

function shanghaiParts(date = new Date()) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23"
  }).formatToParts(date);
  const values = Object.fromEntries(parts.map(({ type, value }) => [type, value]));
  return {
    date: `${values.year}-${values.month}-${values.day}`,
    hour: Number(values.hour),
    minute: Number(values.minute)
  };
}

function buildDataJson(date, steps) {
  return (
    "%5b%7b%22data_hr%22%3a%22" + "%5c%2fv7%2b".repeat(480) +
    `%22%2c%22date%22%3a%22${date}` +
    "%22%2c%22data%22%3a%5b%7b%22start%22%3a0%2c%22stop%22" +
    "%3a1439%2c%22value%22%3a%22" + "A".repeat(5760) +
    `%22%2c%22tz%22%3a32%2c%22did%22%3a%22${DATA_DEVICE_ID}` +
    "%22%2c%22src%22%3a24%7d%5d%2c%22summary%22%3a%22%7b%5c%22v" +
    "%5c%22%3a6%2c%5c%22slp%5c%22%3a%7b%5c%22st%5c%22%3a0%2c" +
    "%5c%22ed%5c%22%3a0%2c%5c%22dp%5c%22%3a0%2c%5c%22lt%5c%22" +
    "%3a0%2c%5c%22wk%5c%22%3a0%2c%5c%22usrSt%5c%22%3a-1440%2c" +
    "%5c%22usrEd%5c%22%3a-1440%2c%5c%22wc%5c%22%3a0%2c%5c%22is" +
    "%5c%22%3a0%2c%5c%22lb%5c%22%3a0%2c%5c%22to%5c%22%3a0%2c" +
    "%5c%22dt%5c%22%3a0%2c%5c%22rhr%5c%22%3a0%2c%5c%22ss%5c%22" +
    "%3a0%7d%2c%5c%22stp%5c%22%3a%7b%5c%22ttl%5c%22%3a" +
    String(steps) +
    "%2c%5c%22dis%5c%22%3a0%2c%5c%22cal%5c%22%3a0%2c%5c%22wk" +
    "%5c%22%3a0%2c%5c%22rn%5c%22%3a0%2c%5c%22runDist%5c%22%3a0" +
    "%2c%5c%22runCal%5c%22%3a0%2c%5c%22stage%5c%22%3a%5b%5d%7d" +
    "%2c%5c%22goal%5c%22%3a0%2c%5c%22tz%5c%22%3a%5c%2228800" +
    "%5c%22%7d%22%2c%22source%22%3a24%2c%22type%22%3a0%7d%5d"
  );
}

async function submitZeppSteps(account, password, steps) {
  const { appToken, userId } = await authenticateZepp(account, password);
  const timestamp = Math.floor(Date.now() / 1000);
  const { date } = shanghaiParts();
  const base = new URLSearchParams({
    userid: userId,
    last_sync_data_time: String(timestamp),
    device_type: "0",
    last_deviceid: DATA_DEVICE_ID
  }).toString();
  const url = new URL(`${API_MIFIT_CN}/v1/data/band_data.json`);
  url.searchParams.set("t", String(timestamp));
  const response = await upstreamFetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
      "User-Agent": USER_AGENT,
      "app_name": APP_NAME,
      "apptoken": appToken
    },
    body: `${base}&data_json=${buildDataJson(date, steps)}`
  });
  const body = await readUpstreamJson(response, "提交");
  if (!response.ok) throw new AppError(`提交失败 (HTTP ${response.status})`, 502);
  if (body.message !== "success") {
    throw new AppError(`提交失败：${body.message || body.error || "未知错误"}`, 502);
  }
  return { ok: true, steps, date, timestamp };
}

async function profileForUser(userId, env) {
  return env.DB.prepare(
    `SELECT zepp_account, schedule_enabled, schedule_hour, schedule_minute,
            min_steps, max_steps, last_run_date, last_status, last_message,
            last_run_started_at,
            manual_cooldown_until, settings_cooldown_until,
            zepp_password_enc IS NOT NULL AS has_zepp_password
     FROM profiles WHERE user_id = ?`
  ).bind(userId).first();
}

async function recordSubmission(env, userId, triggerType, steps, status, message) {
  await env.DB.prepare(
    `INSERT INTO submissions
     (user_id, trigger_type, steps, status, message, created_at)
     VALUES (?, ?, ?, ?, ?, ?)`
  ).bind(
    userId,
    triggerType,
    steps,
    status,
    String(message || "").slice(0, 500),
    Math.floor(Date.now() / 1000)
  ).run();
}

async function handleLogin(request, env) {
  await enforceRateLimit(request, env, "/api/auth/login", 8, 15 * 60);
  const data = await parseJson(request);
  await verifyLoginChallenge(request, env, data);
  const account = String(data.account || "").trim();
  const password = String(data.password || "");
  if (!account || account.length > 254) {
    throw new AppError("请输入有效的 Zepp Life 账号");
  }
  if (!password || password.length > 256) {
    throw new AppError("请输入有效的 Zepp Life 密码");
  }
  await authenticateZepp(account, password);
  const encryptedPassword = await encryptCredential(password, env);
  const now = Math.floor(Date.now() / 1000);
  let profile = await env.DB.prepare(
    "SELECT user_id FROM profiles WHERE zepp_account = ? COLLATE NOCASE"
  ).bind(account).first();
  let userId = profile?.user_id;

  if (userId) {
    await env.DB.prepare(
      "UPDATE profiles SET zepp_account = ?, zepp_password_enc = ?, updated_at = ? WHERE user_id = ?"
    ).bind(account, encryptedPassword, now, userId).run();
  } else {
    const internalName = `zepp_${await sha256(account.toLowerCase())}`;
    const result = await env.DB.prepare(
      `INSERT INTO users
       (username, password_hash, password_salt, created_at)
       VALUES (?, '', '', ?)`
    ).bind(internalName.slice(0, 64), now).run();
    userId = result.meta.last_row_id;
    await env.DB.prepare(
      `INSERT INTO profiles
       (user_id, zepp_account, zepp_password_enc, updated_at)
       VALUES (?, ?, ?, ?)`
    ).bind(userId, account, encryptedPassword, now).run();
  }
  await env.DB.prepare("DELETE FROM sessions WHERE user_id = ?").bind(userId).run();
  const token = await createSession(userId, env);
  return json(
    { ok: true, account },
    200,
    { "Set-Cookie": sessionCookie(token) }
  );
}

async function handleApi(request, env) {
  assertSameOrigin(request);
  const { pathname } = new URL(request.url);

  if (!["GET", "POST", "PUT"].includes(request.method)) {
    throw new AppError("请求方法不支持", 405);
  }

  if (request.method === "POST" && pathname === "/api/auth/login") {
    return handleLogin(request, env);
  }

  if (request.method === "GET" && pathname === "/api/security") {
    await enforceRateLimit(request, env, "/api/security", 60, 60);
    return json({
      ok: true,
      turnstile: {
        enabled: turnstileConfigured(env),
        site_key: env.TURNSTILE_SITE_KEY || null
      }
    });
  }

  if (request.method === "GET" && pathname === "/api/captcha") {
    await enforceRateLimit(request, env, "/api/captcha", 30, 60);
    return json({ ok: true, captcha: await createLocalCaptcha(env) });
  }

  if (request.method === "POST" && pathname === "/api/logout") {
    const token = cookieValue(request, "zepp_session");
    if (token) {
      await env.DB.prepare("DELETE FROM sessions WHERE token_hash = ?")
        .bind(await sha256(token)).run();
    }
    return json({ ok: true }, 200, { "Set-Cookie": clearSessionCookie() });
  }

  const user = await currentUser(request, env);
  await enforceRateLimit(request, env, `user:${user.id}:api`, 120, 60);

  if (request.method === "GET" && pathname === "/api/me") {
    const profile = await profileForUser(user.id, env);
    const history = await env.DB.prepare(
      `SELECT trigger_type, steps, status, message, created_at
       FROM submissions WHERE user_id = ?
       ORDER BY created_at DESC LIMIT 20`
    ).bind(user.id).all();
    return json({
      ok: true,
      user,
      profile: profile || {},
      history: history.results || []
    });
  }

  if (request.method === "PUT" && pathname === "/api/settings") {
    const data = await parseJson(request);
    const hour = Number(data.scheduleHour);
    const minute = Number(data.scheduleMinute);
    if (!Number.isInteger(hour) || hour < 0 || hour > 23 ||
        !Number.isInteger(minute) || minute < 0 || minute > 59) {
      throw new AppError("定时任务时间无效");
    }
    const minimum = validateSteps(data.minSteps, "随机最小步数");
    const maximum = validateSteps(data.maxSteps, "随机最大步数");
    if (minimum > maximum) throw new AppError("随机最小步数不能大于最大步数");
    const now = Math.floor(Date.now() / 1000);
    const cooldownUntil = await claimCooldown(
      env,
      user.id,
      "settings_cooldown_until",
      "保存设置"
    );
    await env.DB.prepare(
      `UPDATE profiles
       SET schedule_enabled = ?, schedule_hour = ?, schedule_minute = ?,
           min_steps = ?, max_steps = ?, updated_at = ?
       WHERE user_id = ?`
    ).bind(
      data.scheduleEnabled ? 1 : 0,
      hour,
      minute,
      minimum,
      maximum,
      now,
      user.id
    ).run();
    return json({ ok: true, cooldown_until: cooldownUntil });
  }

  if (request.method === "POST" && pathname === "/api/submit") {
    const data = await parseJson(request);
    const steps = validateSteps(data.steps);
    const profile = await env.DB.prepare(
      "SELECT zepp_account, zepp_password_enc FROM profiles WHERE user_id = ?"
    ).bind(user.id).first();
    if (!profile?.zepp_account || !profile?.zepp_password_enc) {
      throw new AppError("请先保存 Zepp 账号和密码");
    }
    const cooldownUntil = await claimCooldown(
      env,
      user.id,
      "manual_cooldown_until",
      "手动提交"
    );
    try {
      const result = await submitZeppSteps(
        profile.zepp_account,
        await decryptCredential(profile.zepp_password_enc, env),
        steps
      );
      await recordSubmission(env, user.id, "manual", steps, "success", "提交成功");
      return json({ ...result, cooldown_until: cooldownUntil });
    } catch (error) {
      await recordSubmission(env, user.id, "manual", steps, "failed", error.message);
      throw error;
    }
  }

  throw new AppError("接口不存在", 404);
}

async function runScheduledTasks(env) {
  const { date, hour, minute } = shanghaiParts();
  const now = Math.floor(Date.now() / 1000);
  const currentMinute = hour * 60 + minute;
  const earliestMinute = Math.max(0, currentMinute - SCHEDULE_CATCHUP_MINUTES);
  const staleBefore = now - STALE_RUN_SECONDS;
  await env.DB.prepare("DELETE FROM sessions WHERE expires_at <= ?")
    .bind(now).run();
  await env.DB.prepare("DELETE FROM auth_rate_limits WHERE expires_at <= ?")
    .bind(now).run();
  const due = await env.DB.prepare(
    `SELECT user_id, zepp_account, zepp_password_enc, min_steps, max_steps
     FROM profiles
     WHERE schedule_enabled = 1
       AND (schedule_hour * 60 + schedule_minute) <= ?
       AND (schedule_hour * 60 + schedule_minute) >= ?
       AND zepp_account IS NOT NULL
       AND zepp_password_enc IS NOT NULL
       AND (
         last_run_date IS NULL
         OR last_run_date <> ?
         OR (
           last_status = 'running'
           AND last_run_started_at < ?
         )
       )
     LIMIT 20`
  ).bind(currentMinute, earliestMinute, date, staleBefore).all();

  for (const profile of due.results || []) {
    const claim = await env.DB.prepare(
      `UPDATE profiles
       SET last_run_date = ?, last_status = 'running',
           last_message = '执行中', last_run_started_at = ?
       WHERE user_id = ?
         AND (
           last_run_date IS NULL
           OR last_run_date <> ?
           OR (
             last_status = 'running'
             AND last_run_started_at < ?
           )
         )`
    ).bind(date, now, profile.user_id, date, staleBefore).run();
    if (!claim.meta.changes) continue;

    const steps = Math.floor(
      Math.random() * (profile.max_steps - profile.min_steps + 1)
    ) + profile.min_steps;
    try {
      const password = await decryptCredential(profile.zepp_password_enc, env);
      await submitZeppSteps(profile.zepp_account, password, steps);
      await env.DB.prepare(
        "UPDATE profiles SET last_status = 'success', last_message = ? WHERE user_id = ?"
      ).bind(`已提交 ${steps.toLocaleString()} 步`, profile.user_id).run();
      await recordSubmission(
        env, profile.user_id, "scheduled", steps, "success", "提交成功"
      );
    } catch (error) {
      await env.DB.prepare(
        "UPDATE profiles SET last_status = 'failed', last_message = ? WHERE user_id = ?"
      ).bind(String(error.message).slice(0, 500), profile.user_id).run();
      await recordSubmission(
        env, profile.user_id, "scheduled", steps, "failed", error.message
      );
      console.error("scheduled submit failed", {
        userId: profile.user_id,
        message: error.message
      });
    }
  }
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (!["GET", "POST", "PUT"].includes(request.method)) {
      return json({ ok: false, error: "请求方法不支持" }, 405);
    }
    if (!url.pathname.startsWith("/api/")) {
      await enforceRateLimit(request, env, "static", 300, 60);
      return withSecurityHeaders(await env.ASSETS.fetch(request));
    }
    try {
      return await handleApi(request, env);
    } catch (error) {
      console.error("api request failed", {
        path: url.pathname,
        message: error.message
      });
      const status = error instanceof AppError ? error.status : 500;
      return json({
        ok: false,
        error: status === 500 ? "服务器内部错误" : error.message,
        retry_after: error.retryAfter || undefined
      }, status);
    }
  },

  async scheduled(_controller, env, ctx) {
    ctx.waitUntil(runScheduledTasks(env));
  }
};
