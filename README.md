# ZeppLife 步数提交工具

通过 Zepp Life（原小米运动）的 Huami API 提交当天步数，并由 Zepp Life
同步至已绑定的微信运动、支付宝运动等第三方平台。

项目提供两种使用方式：

- Web 页面：适合本地手动操作，支持快捷步数、提交历史和限流倒计时。
- 命令行：适合脚本、定时任务和多账号批量处理。

> 本项目调用的是未公开保证兼容性的接口。接口参数、域名和风控规则可能随时变化。

## 功能

- 支持手机号和邮箱账号。
- 支持固定步数、随机步数和多账号配置。
- Web 与 CLI 共用同一套 API 客户端，避免行为不一致。
- Web 端缓存登录 Token，一小时内重复提交时减少登录请求。
- 缓存 Token 失效后自动重新登录一次。
- 识别 `HTTP 429` 限流，并根据 `Retry-After` 显示等待时间。
- NTP 获取时间失败时自动退回本机系统时间。
- 对步数范围、随机区间、JSON 响应和配置文件进行校验。
- 提供不访问真实 Huami API 的单元测试。

## 工作流程

一次完整提交包含以下步骤：

1. 使用 Zepp Life 账号和密码获取登录授权码。
2. 用授权码换取 `login_token` 和用户 ID。
3. 用 `login_token` 换取 `app_token`。
4. 构造当天的运动数据并提交至 `/v1/data/band_data.json`。
5. Zepp Life 将数据同步至已绑定的第三方平台。

```text
Web / CLI
    |
    v
ZeppClient
    |
    +-- 登录账号
    +-- 获取 app_token
    +-- 提交当天步数
    |
    v
Zepp Life -> 微信运动 / 支付宝运动
```

## 使用前准备

1. 安装 Zepp Life App。
2. 注册 Zepp Life 账号，支持中国大陆手机号或邮箱。
3. 在 App 中进入“我的 -> 第三方接入”。
4. 完成微信、支付宝等目标平台的绑定。

如果没有完成第三方绑定，Huami API 即使返回提交成功，目标平台也不会同步。

## 环境要求

- Python 3.10 或更高版本。
- 能够访问 Huami API 的网络。
- 本机日期、时间和时区基本正确。

主要依赖：

| 依赖 | 用途 |
| --- | --- |
| Flask 3.x | Web 服务 |
| Requests 2.x | HTTP 请求与连接复用 |

## 安装

```bash
cd /path/to/zepp_step_tool
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Windows PowerShell 激活虚拟环境：

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## 快速开始

### Web 页面

```bash
source .venv/bin/activate
python app.py
```

浏览器访问：

```text
http://127.0.0.1:5000
```

Web 服务默认只监听本机地址 `127.0.0.1`，不会直接暴露给局域网或公网。

页面支持：

- 输入手机号或邮箱账号。
- 选择预设步数或生成随机步数。
- 提交 `1` 至 `98,800` 之间的步数。
- 显示最近 50 条本地提交记录。
- 遇到接口限流时禁用按钮并显示倒计时。

### 命令行

提交固定步数：

```bash
python zepp_step.py \
  --user user@example.com \
  --password 'your_password' \
  --steps 25000
```

手机号不需要添加 `+86`：

```bash
python zepp_step.py -u 13800138000 -p 'your_password' -s 25000
```

使用随机步数：

```bash
python zepp_step.py \
  -u user@example.com \
  -p 'your_password' \
  --random 20000 35000
```

如果没有提供 `--steps` 或 `--random`，程序会在 `20,000` 至 `35,000`
之间随机生成步数。

显示详细请求日志：

```bash
python zepp_step.py \
  -u user@example.com \
  -p 'your_password' \
  -s 25000 \
  --verbose
```

查看全部参数：

```bash
python zepp_step.py --help
```

## 多账号配置

复制示例配置：

```bash
cp config.example.json config.json
```

配置格式：

```json
{
  "accounts": [
    {
      "user": "13800138000",
      "password": "your_password",
      "steps": null
    },
    {
      "user": "user2@example.com",
      "password": "your_password",
      "steps": [20000, 35000]
    },
    {
      "user": "13900139000",
      "password": "your_password",
      "steps": 30000
    }
  ]
}
```

`steps` 支持以下形式：

| 值 | 行为 |
| --- | --- |
| `null` | 使用命令行全局步数；未指定时使用默认随机范围 |
| `[20000, 35000]` | 为该账号生成指定范围内的随机步数 |
| `30000` | 为该账号提交固定步数 |

执行多账号任务：

```bash
python zepp_step.py --config config.json --delay 120
```

`--delay` 是账号之间的等待秒数。建议设置较长间隔，减少触发 Huami
登录限流的概率。

配置项同时兼容以下别名：

- 账号：`user` 或 `account`
- 密码：`password` 或 `pwd`

## Cloudflare Workers 部署

项目的 `worker/` 目录提供了可独立部署的 Cloudflare Workers 版本：

当前线上地址：

```text
https://steps.zhhcnl.com
```

```text
worker/
├── migrations/           # D1 数据库迁移
├── public/index.html     # 注册、登录和用户控制台
├── src/index.js          # 认证、加密、Huami API 和调度器
├── package.json
└── wrangler.jsonc
```

Workers 版本具有以下特点：

- 静态页面与 API 部署在同一个 Worker。
- 用户直接使用自己的 Zepp Life 账号和密码登录，无需注册站点账号。
- 每次重新登录都会向 Zepp Life 验证凭据。
- Zepp 密码使用 AES-256-GCM 加密后存入 D1。
- 登录态使用 `Secure`、`HttpOnly`、`SameSite=Lax` Cookie。
- 每位用户只能读取和修改自己的 Zepp 配置与提交记录。
- 每位用户可独立开关定时任务、设置北京时间及随机步数范围。
- Cron 每分钟运行一次，只处理当前分钟到期且当天尚未执行的用户。
- 手动提交与保存定时设置分别具有 30 分钟持久化冷却，刷新页面无法绕过。
- 登录入口支持 Cloudflare Turnstile 人机验证，配置密钥后自动启用。

安装依赖并登录：

```bash
cd worker
npm install
npx wrangler login
```

创建 D1 数据库：

```bash
npx wrangler d1 create zepp-step-users --location=apac
```

将命令输出的 `database_id` 写入 `wrangler.jsonc`，然后设置加密 Secret：

```bash
npx wrangler secret put CREDENTIAL_ENCRYPTION_KEY
```

`CREDENTIAL_ENCRYPTION_KEY` 必须是 32 字节随机值的 Base64 编码，例如：

```bash
openssl rand -base64 32
```

启用 Turnstile 防爬虫：

1. 在 Cloudflare 控制台创建 Turnstile widget。
2. Hostname 填写 `steps.zhhcnl.com`，如需保留 Workers 默认域名测试，可额外加入 `zepp-step-tool.zhangzhihao-worldcup-2026.workers.dev`。
3. 将站点密钥写入 `worker/wrangler.jsonc`：

```json
{
  "vars": {
    "TURNSTILE_SITE_KEY": "你的 site key"
  }
}
```

4. 将 secret key 写入 Worker Secret：

```bash
npx wrangler secret put TURNSTILE_SECRET_KEY
```

两个值都配置后，登录页会自动显示 Turnstile，并且 `/api/auth/login` 会在服务端校验 token。

应用数据库迁移并部署：

```bash
npx wrangler d1 migrations apply zepp-step-users --remote
npm run deploy
```

调度器配置位于 `worker/wrangler.jsonc`：

```json
{
  "triggers": {
    "crons": ["* * * * *"]
  },
  "routes": [
    {
      "pattern": "steps.zhhcnl.com",
      "custom_domain": true
    }
  ]
}
```

Cloudflare 每分钟唤醒一次调度器。Worker 使用 `Asia/Shanghai` 时区匹配用户保存的
小时和分钟，因此用户页面中填写的时间均为北京时间。命中后会在该用户设置的最小值
与最大值之间生成包含边界的随机整数，同一天只执行一次。

更换 `CREDENTIAL_ENCRYPTION_KEY` 会导致已有 Zepp 密码无法解密。需要轮换密钥时，
应先设计数据重加密流程，不要直接覆盖。

查看实时日志：

```bash
cd worker
npm run tail
```

查看已配置的 Secret 名称：

```bash
npx wrangler secret list
```

Secret 的值不会通过该命令显示。修改 Zepp 密码后，只需在网页中重新保存
Zepp 设置，无需修改 Worker Secret。

## 参数说明

| 参数 | 说明 |
| --- | --- |
| `-u`, `--user` | Zepp Life 手机号或邮箱 |
| `-c`, `--config` | 多账号 JSON 配置文件 |
| `-p`, `--password` | Zepp Life 密码 |
| `-s`, `--steps` | 固定目标步数，范围为 `1` 至 `98,800` |
| `--random MIN MAX` | 随机步数范围 |
| `--delay SECONDS` | 多账号之间的等待时间 |
| `-v`, `--verbose` | 输出 DEBUG 日志 |

`--user` 与 `--config` 必须且只能选择一个。

命令行退出码：

| 退出码 | 含义 |
| --- | --- |
| `0` | 全部提交成功 |
| `1` | 登录、Token 获取、提交或账号配置失败 |
| `2` | 命令行参数不合法 |

## Web 数据与缓存

### 浏览器本地存储

勾选“记住账号密码”后，页面会将账号、密码和步数保存在浏览器
`localStorage` 中。提交历史也保存在 `localStorage` 中，不会写入项目文件。

需要注意：

- `localStorage` 不是加密存储。
- 能够访问该浏览器用户数据的人可能读取其中的密码。
- 不建议在共享电脑或不可信设备上启用此功能。
- 清空提交历史不会自动清除已保存的账号密码。

### 服务端 Token 缓存

Web 服务会在内存中缓存 `login_token`、`app_token` 和用户 ID，默认有效期为
一小时。缓存不会写入磁盘，停止 Flask 服务后即被清除。

缓存 Token 被服务器判定失效时，Web 服务会清除缓存并自动重新登录一次。

## 限流说明

Huami 登录接口可能返回 `HTTP 429`。这不是页面故障，而是服务端拒绝过于频繁
的登录请求。

遇到限流时：

1. 停止重复点击或反复运行命令。
2. 至少等待响应提示的时间后再试。
3. 如果等待后仍然返回 `429`，建议暂停数小时。
4. 多账号运行时增大 `--delay`。

持续重试可能延长限制时间。Web 页面在限流期间只显示倒计时，不会自动再次提交。

## 定时运行

### Cron

建议使用虚拟环境中的 Python 绝对路径，不依赖交互式 shell 的 `source`：

```cron
# 每天 09:00 执行一次
0 9 * * * cd /path/to/zepp_step_tool && .venv/bin/python zepp_step.py -c config.json --delay 120 >> step.log 2>&1
```

不建议在一天内高频执行定时任务。每次 CLI 运行都需要重新登录，频率过高容易触发
`HTTP 429`。

### 后台运行 Web 服务

```bash
mkdir -p logs
nohup .venv/bin/python app.py > logs/app.log 2>&1 &
```

当前项目使用 Flask 开发服务器，适合本机个人使用，不适合直接作为公网生产服务。

## 测试

运行全部单元测试：

```bash
source .venv/bin/activate
python -m unittest -v
```

当前测试覆盖：

- Web API 对非法 JSON 和步数范围的校验。
- Web API 对合法请求的调用参数。
- 邮箱和手机号登录参数。
- 密码中 `&`、`+` 等特殊字符的表单编码。
- `HTTP 429` 等待时间解析。
- 步数数据载荷构造。
- 防止 `data_json` 被重复 URL 编码。
- Token 失效识别。
- 成功提交结果解析。

测试使用 Mock，不会登录真实账号，也不会修改真实步数。

## 常见问题

### 提交成功，但微信或支付宝没有更新

- 确认 Zepp Life App 已绑定目标平台。
- 打开 Zepp Life App，等待其完成同步。
- 等待几分钟后重新查看目标平台。
- 当天步数通常只能向更大的数值更新。

### 返回“用户名或密码不正确”

- 手机号只填写 11 位数字，不要手动添加 `+86`。
- 邮箱填写完整地址。
- 检查密码大小写和特殊字符。
- 先在 Zepp Life App 中确认账号能够正常登录。

### 返回 `HTTP 429`

账号或当前网络出口触发了登录限流。停止尝试并等待，不要连续重试。

### 返回 `HTTP 400`

通常表示提交载荷与当前接口要求不兼容。先确认正在使用最新代码，再使用
`--verbose` 查看失败发生在哪一步。

### NTP 请求超时

程序会自动使用本机系统时间继续提交。请确认本机日期、时间和时区正确。

### Web 页面无法打开

确认终端出现：

```text
Running on http://127.0.0.1:5000
```

检查端口占用：

```bash
lsof -nP -iTCP:5000 -sTCP:LISTEN
```

macOS 的 AirPlay Receiver 可能占用 `5000` 端口。

### 如何判断 CLI 是否成功

成功时日志包含：

```text
步数提交成功
```

同时进程退出码为 `0`。仅登录成功不代表步数已经提交成功，必须以最后一个提交请求
的响应为准。

## 安全建议

- 建议使用专用 Zepp Life 账号。
- 不要在公开聊天、截图、日志或代码仓库中暴露真实密码。
- 命令行中的密码可能被 shell 历史或系统进程列表记录。
- `config.json` 包含明文密码，不要提交到 Git。
- 如果密码已经泄露，应立即在 Zepp Life 中修改。
- 不要将当前 Flask 开发服务器直接暴露到公网。

建议在项目的 `.gitignore` 中排除：

```gitignore
.venv/
__pycache__/
*.pyc
config.json
logs/
```

## 项目结构

```text
zepp_step_tool/
├── app.py                 # Flask Web 服务和内嵌页面
├── zepp_step.py           # 命令行入口
├── zepp_client.py         # Web 与 CLI 共用的 Huami API 客户端
├── worker/                # Cloudflare Workers 版本
├── config.example.json    # 多账号配置示例
├── requirements.txt       # Python 依赖
├── test_app.py            # Web API 测试
├── test_zepp_client.py    # API 客户端测试
└── README.md
```

## 使用限制

- 本地 Python 版本可提交 `1` 至 `98,800`；Cloudflare Workers 页面限制为
  `1` 至 `98,000`。
- 当天数据通常只能向更高步数更新。
- 第三方平台同步可能存在延迟。
- Huami API 可能因地区、账号状态、风控或接口升级而不可用。
- 项目不保证提交的数据一定被所有第三方平台接受。

## 免责声明

本项目仅用于技术学习和个人研究。修改运动数据可能违反 Zepp Life、微信、支付宝
或其他平台的服务协议，也可能触发账号限制。使用者应自行评估风险并承担相应责任。
