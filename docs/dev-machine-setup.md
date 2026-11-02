# 开发机安装与启动指南

本文档记录在本开发机上从零安装、配置并启动 ContextBase（Hindsight）后端 API 与控制面 UI 的完整流程，包括过程中遇到的所有环境问题与解决办法。

> 适用环境：Linux（glibc），非 root 用户运行。本机实际地址 `29.7.104.118`（eth0）。

---

## 1. 前置条件

| 项 | 要求 | 本机情况 |
|---|---|---|
| Python | 3.11 | `/usr/bin/python3.11` |
| Node | 22.x | v22.23.4 |
| npm | 10.x | 10.9.9 |
| pip 镜像 | `http://mirrors.tools.huawei.com/pypi/simple/`（`/etc/pip.conf` 已配置） | 可达 |
| npm 镜像 | `http://mirrors.tools.huawei.com/npm/`（`~/.npmrc` 已配置） | 可达 |
| 非 root 用户 | `service`（uid 1000，HOME=`/home/service`，可写） | 存在 |
| LLM 网关 | `http://10.181.132.115:31943/v1`（OpenAI 兼容，仅 `/v1/chat/completions`） | 可达 |
| Embedding 服务 | `http://10.181.132.115:11434/v1`（Ollama，模型 `bge-m3`） | 可达（启动时偶有抖动） |

> **为什么用 pip 而不是 uv**：本机 DNS 不通（`/etc/resolv.conf` 的 `26.84.32.17/.18` 不可达），`uv` 无法访问 PyPI；而 pip 配置了可达的内部镜像。此外根 workspace 有一个 `contextbase-client` 源声明问题（见第 5 节），会导致 `uv` 解析失败。

---

## 2. 关键文件位置

```
/home/hindsight/
├── .env                              # 主配置（鉴权、LLM、embedding、UI）
├── hindsight-api-slim/               # 后端 API（Python，pip venv）
│   ├── .venv/                        # pip 安装的虚拟环境
│   └── hindsight_api/
├── contextbase-control-plane/         # 控制面 UI（Next.js）
│   └── .next/                        # 构建缓存（需 service 可写）
├── hindsight-clients/typescript/     # contextbase-client TS SDK（需先 build）
└── scripts/dev/
    ├── start-api-local.sh            # API 启动脚本（绑定 29.7.104.118）
    └── start-ui-local.sh             # UI 启动脚本（绑定 29.7.104.118）
```

---

## 3. 安装步骤

### 3.1 清理 CRLF 行尾（必做）

仓库里的 `.env`、`scripts/dev/*.sh` 都是 **CRLF 行尾**，bash 直接执行会报 `$'\r': command not found`。统一去掉：

```bash
cd /home/hindsight
tr -d '\r' < .env > .env.tmp && mv .env.tmp .env
for f in scripts/dev/*.sh; do
  [ -f "$f" ] && tr -d '\r' < "$f" > "$f.tmp" && mv "$f.tmp" "$f" && chmod +x "$f"
done
find scripts -name "*.sh" -exec sh -c 'tr -d "\r" < "$1" > "$1.tmp" && mv "$1.tmp" "$1" && chmod +x "$1"' _ {} \;
```

### 3.2 安装后端 API（pip + 嵌入式 pg0）

```bash
cd /home/hindsight/hindsight-api-slim
python3.11 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -e ".[embedded-db]"
```

`embedded-db` extra 会装上 `pg0-embedded`（嵌入式 PostgreSQL，无需外部 DB）。CLI 在 `.venv/bin/hindsight-api`。

### 3.3 安装控制面 UI 依赖（npm workspace）

```bash
cd /home/hindsight
npm install --workspace=contextbase-control-plane --ignore-scripts
```

> `--ignore-scripts` 跳过根 `package.json` 的 `prepare`（`scripts/setup-hooks.sh`），因为它需要 git 仓库（本机无 `.git`），不跳过会报 `fatal: not a git repository`。

### 3.4 构建 TS SDK `contextbase-client`（必做）

控制面 UI 依赖 `contextbase-client` 包（`hindsight-clients/typescript`，workspace 成员），其 `main` 指向 `./dist/index.js`，**默认没有构建产物**，否则 `/banks` 页会报 `Can't resolve 'contextbase-client'`：

```bash
cd /home/hindsight
npm run build -w contextbase-client     # 生成 dist/index.{js,mjs,d.ts}
```

---

## 4. 配置（`/home/hindsight/.env`）

### 4.1 鉴权（API + UI 反代）

启用内置 `ApiKeyTenantExtension`（无外部依赖），所有 API 请求需带 bearer key；控制面用同一 key 反代到 API：

```bash
HINDSIGHT_API_TENANT_EXTENSION=hindsight_api.extensions.builtin.tenant:ApiKeyTenantExtension
HINDSIGHT_API_TENANT_API_KEY=hindsight-local-dataplane-2026
CONTEXTBASE_CP_DATAPLANE_API_KEY=hindsight-local-dataplane-2026
```

### 4.2 数据库（嵌入式 pg0）

`HINDSIGHT_API_DATABASE_URL` 不设置 → 自动使用嵌入式 pg0（启动日志显示 `Database: pg0`，schema `public`）。迁移在启动时自动跑。

### 4.3 LLM / Embedding

```bash
HINDSIGHT_API_LLM_PROVIDER=openai
HINDSIGHT_API_LLM_MODEL=qwen3.7-max
HINDSIGHT_API_LLM_BASE_URL=http://10.181.132.115:31943/v1
HINDSIGHT_API_LLM_API_KEY=ollama

HINDSIGHT_API_EMBEDDINGS_PROVIDER=openai
HINDSIGHT_API_EMBEDDINGS_OPENAI_BASE_URL=http://10.181.132.115:11434/v1
HINDSIGHT_API_EMBEDDINGS_OPENAI_MODEL=bge-m3
HINDSIGHT_API_EMBEDDINGS_OPENAI_API_KEY=ollama
HINDSIGHT_API_EMBEDDINGS_OPENAI_DIMENSIONS=1024

HINDSIGHT_API_RERANKER_PROVIDER=rrf   # 透传，不下载模型
```

> 注意 `.env` 顶部有默认占位值（`gpt-4o-mini` 等），文件后面的本地覆盖段会覆盖它们（`source` 后出现的覆盖先出现的）。生效的是上面的本地值。

### 4.4 控制面 UI 登录

```bash
CONTEXTBASE_CP_AUTH_MODE=local
CONTEXTBASE_CP_ACCESS_KEY=hindsight-local-ui-2026         # UI 登录密码（独立于 dataplane key）
CONTEXTBASE_CP_PUBLIC_ORIGIN=http://29.7.104.118:9999     # 浏览器访问地址（同源校验基准）
CONTEXTBASE_CP_SESSION_DIR=/home/hindsight/.cp-sessions   # Linux 路径（原仓库默认是 Windows 的 D:/hindsight-sessions，必须改）
```

> `PUBLIC_ORIGIN` 必须等于浏览器实际访问的地址，否则登录 POST 会被同源校验拒绝（403 `Untrusted request origin`）。

---

## 5. 安装过程的坑与解法

### 5.1 uv 不可用 → 改用 pip

- 根 `pyproject.toml` 的 workspace 成员 `hindsight-all` / `hindsight-all-slim` 把 `contextbase-client`（它本身也是 workspace 成员 `hindsight-clients/python` 的 TS 对应包，这里指 TS 包 `hindsight-clients/typescript`）声明为 `contextbase-client = { path = "../hindsight-clients/python", editable = true }`，`uv` 认为这是错误声明（workspace 成员必须用 `{ workspace = true }`）会拒绝解析。
- 即便修复，`uv` 需访问 PyPI，本机 DNS 不通。
- 解法：直接用 pip（已配置内部镜像），绕开 uv。

### 5.2 嵌入式 pg0 必须非 root 运行

`initdb` 拒绝 root：

```
initdb: error: cannot be run as root
initdb: hint: Please log in (using, e.g., "su") as the (unprivileged) user that will own the server process.
```

解法：用 `service` 用户跑 API，并设 `HOME=/home/service`（pg0 把二进制和数据放在 `~/.local`）。

### 5.3 权限：service 用户读 root 拥有的文件

venv、`.env`、`node_modules`、控制面源码（特别是 `bin/cli.js` 默认 750）、`.next`、session 目录都是 root 拥有，`service` 默认读不了，会导致：

- API：venv 读不了 → 启动失败
- UI：`bin/cli.js` 读不了 → Turbopack 报 `Permission denied (os error 13)` 后 500
- UI：`.next` 不可写 → `EACCES mkdir .next/dev`
- UI：session 目录不可写 → 登录 503 `Session storage unavailable`

解法（一次性）：

```bash
cd /home/hindsight
chmod -R a+rX hindsight-api-slim/.venv
chmod a+r .env
chmod -R a+rX node_modules contextbase-control-plane hindsight-clients/typescript/dist
mkdir -p contextbase-control-plane/.next && chown -R service:servicegroup contextbase-control-plane/.next
mkdir -p .cp-sessions && chown -R service:servicegroup .cp-sessions && chmod 700 .cp-sessions
# 日志文件也要 service 可写
chown service:servicegroup hindsight-api.stdout.log hindsight-api.stderr.log ui.stdout.log ui.stderr.log
```

### 5.4 Turbopack 不稳定 → 用 webpack

此版本 `src/lib/auth/session.ts` 和 `instrumentation.ts` 在 Edge Runtime 里 `import` 了 `node:fs/promises` / `node:path`。在 `--turbopack` 下登录接口（`POST /api/auth/login`）会间歇性 500。改用 webpack（`next dev` 不加 `--turbopack`）后稳定（5/5 登录成功）。Edge 警告本身不致命。

### 5.5 登录请求体字段

UI 登录接口的 body 是 `{"key":"<ACCESS_KEY>"}`，**不是** `accessKey`；且必须带同源头：`Origin` + `Host` + `sec-fetch-site: same-origin`，否则 403。

### 5.6 别用 `pkill -f "next dev"` 杀进程

会匹配到 agent 自己的命令行把 shell 一起杀掉（exit 144）。按 pid 杀：

```bash
kill $(pgrep -f next-server | head -1)
```

### 5.7 绑定到网卡地址 29.7.104.118

默认绑定 `0.0.0.0`。要只绑 `29.7.104.118`：API 加 `--host 29.7.104.118`，UI 加 `-H 29.7.104.118`，并把 `.env` 里 `PUBLIC_ORIGIN` 改成 `http://29.7.104.118:9999`、UI 的 dataplane URL 改成 `http://29.7.104.118:8888`（绑定后 localhost 不再可达）。

---

## 6. 启动

启动脚本已写入 `scripts/dev/`（均以 `service` 用户、绑定 `29.7.104.118` 运行）。

### 6.1 启动 API

```bash
nohup sudo -u service bash /home/hindsight/scripts/dev/start-api-local.sh \
  > /home/hindsight/hindsight-api.stdout.log 2> /home/hindsight/hindsight-api.stderr.log &
```

`start-api-local.sh` 内容：

```bash
#!/bin/bash
set -e
ROOT=/home/hindsight
sudo -n -u service bash -c "
  set -a; source $ROOT/.env; set +a
  cd $ROOT/hindsight-api-slim
  export HOME=/home/service
  exec .venv/bin/hindsight-api --host 29.7.104.118 --port 8888
"
```

### 6.2 启动 UI

```bash
nohup sudo -u service bash /home/hindsight/scripts/dev/start-ui-local.sh \
  > /home/hindsight/ui.stdout.log 2> /home/hindsight/ui.stderr.log &
```

`start-ui-local.sh` 内容：

```bash
#!/bin/bash
set -e
ROOT=/home/hindsight
sudo -n -u service bash -c "
  set -a; source $ROOT/.env; set +a
  cd $ROOT/contextbase-control-plane
  export PATH=$ROOT/node_modules/.bin:\$PATH
  export PORT=9999 HINDSIGHT_CP_DATAPLANE_API_URL=http://29.7.104.118:8888
  exec next dev -H 29.7.104.118 -p 9999
"
```

> UI 用 webpack（`next dev` 不带 `--turbopack`）。日志里 `Using API key authentication` 表示已用 dataplane key 反代。

### 6.3 验证

```bash
# API 鉴权
curl http://29.7.104.118:8888/health                                    # 200
curl http://29.7.104.118:8888/v1/default/banks                         # 401（无 key）
curl -H "Authorization: Bearer hindsight-local-dataplane-2026" \
     http://29.7.104.118:8888/v1/default/banks                         # 200

# UI 登录 + 反代到鉴权 API
BASE=http://29.7.104.118:9999
curl -c /tmp/c.txt -X POST "$BASE/api/auth/login" -H "Content-Type: application/json" \
     -H "Origin: $BASE" -H "Host: 29.7.104.118:9999" -H "sec-fetch-site: same-origin" \
     -d '{"key":"hindsight-local-ui-2026"}'                             # {"success":true}
curl -b /tmp/c.txt "$BASE/api/banks"                                    # 返回 banks JSON
```

浏览器访问 `http://29.7.104.118:9999`，用 access key `hindsight-local-ui-2026` 登录。

---

## 7. 访问信息

| 服务 | 地址 | 说明 |
|---|---|---|
| API | `http://29.7.104.118:8888` | 鉴权：`Authorization: Bearer hindsight-local-dataplane-2026`；`/health` 无需鉴权 |
| 控制面 UI | `http://29.7.104.118:9999` | 登录密码 `hindsight-local-ui-2026` |
| MCP | `http://29.7.104.118:8888/mcp/` | 同样走 dataplane key 鉴权 |
| Metrics | `http://29.7.104.118:8888/metrics` | |

> 页面路由走 i18n（`/[locale]/...`），`/banks` 直接访问会 404，正确入口是 `/en/banks` 等；不影响鉴权与 `/api/*` 数据接口。

---

## 8. 关键密码 / Key 汇总

| 用途 | 值 |
|---|---|
| API dataplane 鉴权 | `hindsight-local-dataplane-2026` |
| 控制面 UI 登录 | `hindsight-local-ui-2026` |
| LLM / Embedding API key | `ollama`（网关不校验，占位即可） |

---

## 9. 重启 / 停止

```bash
# 停止
kill $(pgrep -f "hindsight-api --host" | head -1)
kill $(pgrep -f "next-server" | head -1)

# 启动（见第 6 节）
```

> 如修改了 `.env` 需重启两个服务才生效。`.next` 缓存偶尔会与正在运行的进程冲突（报 `directory was deleted`），停掉 UI 后 `rm -rf contextbase-control-plane/.next` 再启动即可。
