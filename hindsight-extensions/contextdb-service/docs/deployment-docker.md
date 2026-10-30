# ContextDB Docker Compose 部署

适用于 Linux 容器交付，按顺序执行本页命令。先读[部署总览与共用配置](deployment.md)；宿主进程方式见[另一条指南](deployment-native.md)。原 Docker 操作从 deployment.md 移到此页，配置和权限规则仍只有一份。

所有命令在同一源码版本的仓库根目录、同一 Bash 会话执行。首次部署新实例使用独立 PG、目录和端口，不操作现有实例。macOS 的 Linux 虚拟机还需单独适配目录共享/UID等，不将本页视为已验证的 macOS Docker 配方。

## 1. 前提与支持范围

- 有 Linux 主机、Bash、sudo 权限、install、curl、Docker BuildKit、Docker Compose v2、Git 和可用的镜像/依赖下载网络；PG 准备机另需支持 `\getenv` 的 psql。Dockerfile 构建匹配的 Python 环境、Node 24 和 UI standalone；无需在宿主另行安装 Node/Python 服务环境。
- 先满足[共用 PG、模型及支持范围](deployment.md#1-前提与支持范围)，不使用现有客户库试运行初始化。
- 从容器网络可以连接 PG 与 MaaS。数据库 URL 中的 `127.0.0.1` 指容器自身，不是宿主 PG。
- 本示例选择默认端口 8888/9999、私有持久目录 `/srv/contextdb/runtime` 和容器 UID/GID 10001。使用独立测试主机或先确认这些路径、端口未被现有部署占用；不要把新实例指向在用的部署目录。
- 生产入口的 TLS、访问限制、反向代理、数据库备份由运营方提供。本例 HTTP origin 仅用于本机试用，不能直接作为公网交付配置。

<a id="pg-preparation"></a>

## 2. 准备 PG 与私密输入

PG 和三个私密输入的内容、角色及权限见[共用准备说明](deployment.md#pg-preparation)。由 PG 管理员准备后，先在宿主私密文件中保存 database-url、maas-key 和 ui-password；下面把它们复制为渲染输入。

接着在同一个 Bash 会话设置以下变量；源路径替换为实际私密文件路径，不把文件内容放到聊天、版本库或普通日志中。

```bash
export CONTEXTDB_DATABASE_URL_SOURCE=/absolute/private/database-url
export CONTEXTDB_MAAS_KEY_SOURCE=/absolute/private/maas-key
export CONTEXTDB_UI_PASSWORD_SOURCE=/absolute/private/ui-password
export CONTEXTDB_DEPLOY_DIR=/srv/contextdb/runtime
export CONTEXTDB_UID=10001
export CONTEXTDB_GID=10001
export CONTEXTDB_API_PORT=8888
export CONTEXTDB_UI_PORT=9999
sudo install -d -m 0700 -o 10001 -g 10001 \
  /srv/contextdb /srv/contextdb/input "$CONTEXTDB_DEPLOY_DIR"
sudo install -m 0600 -o 10001 -g 10001 "$CONTEXTDB_DATABASE_URL_SOURCE" /srv/contextdb/input/database-url
sudo install -m 0600 -o 10001 -g 10001 "$CONTEXTDB_MAAS_KEY_SOURCE" /srv/contextdb/input/maas-key
sudo install -m 0600 -o 10001 -g 10001 "$CONTEXTDB_UI_PASSWORD_SOURCE" /srv/contextdb/input/ui-password
```

不要复制其他实例的秘密文件来创建新实例。已有实例缺失秘密时，恢复该实例的匹配备份，不能补生 pepper 以维持旧 Key。

## 3. 从同一源码构建镜像

仍在仓库根目录、同一 Bash 会话执行。下面使用当前提交 SHA 标记本机镜像，部署时保留镜像 ID 或已批准的 registry digest；生产构建还应给 Dockerfile 的 `NODE_IMAGE` 提供经批准的基础镜像 digest。

```bash
export CONTEXTDB_SOURCE_REVISION="$(git rev-parse HEAD)"
export CONTEXTDB_IMAGE="contextdb-service:${CONTEXTDB_SOURCE_REVISION}"
export CONTEXTDB_COMPOSE_FILE="$PWD/hindsight-extensions/contextdb-service/deployment/compose.yaml"
docker build \
  -f hindsight-extensions/contextdb-service/deployment/Dockerfile \
  --build-arg SOURCE_REVISION="$CONTEXTDB_SOURCE_REVISION" \
  -t "$CONTEXTDB_IMAGE" .
```

该 Dockerfile 复制本仓库扩展并构建匹配 UI，不能替换为默认社区镜像。仅安装 `hindsight_ext_contextdb` 或设置四个扩展变量仍不等于完成初始化与受保护启动。

## 4. 配置意图、校验与渲染

先复制[意图示例](../deployment/intent.example.json)：

```bash
sudo install -m 0600 -o 10001 -g 10001 \
  hindsight-extensions/contextdb-service/deployment/intent.example.json /srv/contextdb/intent.json
sudoedit /srv/contextdb/intent.json
```

完整字段规则见[共用 intent 说明](deployment.md#4-配置意图校验与渲染)。以下是本容器示例需要核对的路径和端口：

| 项目 | 本例值 |
| --- | --- |
| 三个输入路径 | `/srv/contextdb/input/database-url`、`maas-key`、`ui-password`，与渲染挂载一致 |
| api/ui 端口 | 8888/9999，与 Compose 端口变量一致 |
| `ui_api_url` | `http://127.0.0.1:8888`，同容器内访问 |
| `ui_public_origin` | 浏览器真实 origin，远程部署不要照抄 localhost，公网使用 TLS 入口 |
| `ui_session_dir` | `/var/lib/contextdb/ui-sessions`，运行容器内路径 |
| 实例/归属/worker 标识 | 改为本实例身份，不通过改 ID 接管已有库 |
| 可选 CA | 若设置，校验、初始化、运行和 status 容器均须同路径额外挂载；本例不含这些挂载 |

用镜像内 Python 校验并渲染。只读输入目录，仅在渲染时允许写运行配置：

```bash
docker run --rm --user 10001:10001 \
  --mount type=bind,src=/srv/contextdb/input,dst=/srv/contextdb/input,readonly \
  --mount type=bind,src=/srv/contextdb/intent.json,dst=/srv/contextdb/intent.json,readonly \
  --entrypoint /app/.venv/bin/python "$CONTEXTDB_IMAGE" \
  -m hindsight_ext_contextdb.deployment validate --config /srv/contextdb/intent.json

docker run --rm --user 10001:10001 \
  --mount type=bind,src=/srv/contextdb/input,dst=/srv/contextdb/input,readonly \
  --mount type=bind,src=/srv/contextdb/intent.json,dst=/srv/contextdb/intent.json,readonly \
  --mount "type=bind,src=$CONTEXTDB_DEPLOY_DIR,dst=/var/lib/contextdb" \
  --entrypoint /app/.venv/bin/python "$CONTEXTDB_IMAGE" \
  -m hindsight_ext_contextdb.deployment render \
  --config /srv/contextdb/intent.json --directory /var/lib/contextdb
```

成功输出 `ok:true`。渲染生成私有 `api.env`、`ui.env` 和会话目录；尚未创建数据库管理表或 Admin Key。无 `ok:true` 时先修复输入，不进入初始化。

## 5. 插件配置与容器加载

四个扩展变量、秘密/别名优先级和公开连接设置统一见[共用配置](deployment.md#plugin-configuration)。render 后四项自动出现在 api.env，无需在 intent 或 ui.env 重复填写。公开端点按实际需要补入宿主 `/srv/contextdb/runtime/ui.env`，由有权限的部署账号编辑。

<a id="docker-plugin-loading"></a>

| 环节 | 容器路径与动作 |
| --- | --- |
| 镜像代码 | Dockerfile 复制插件至 `/app/hindsight-extensions/contextdb-service` 并设置 PYTHONPATH |
| 实例配置 | 宿主 `/srv/contextdb/runtime/api.env` 由 Compose 只读挂载为 `/var/lib/contextdb/api.env` |
| 初始化 | initialize 挂载完整运行目录为可写，以准备秘密文件 |
| 启动 | ENTRYPOINT 执行 service.sh，API 分支导出 api.env，再启动专用 ASGI |

容器运行后可只输出四项扩展类路径检查挂载：

```bash
docker compose -p contextdb-example -f "$CONTEXTDB_COMPOSE_FILE" exec -T hindsight \
  awk -F= '/^HINDSIGHT_API_(TENANT_EXTENSION|OPERATION_VALIDATOR_EXTENSION|HTTP_EXTENSION|MCP_EXTENSION)=/ {print}' \
  /var/lib/contextdb/api.env
```

首次部署时先执行下方第6节启动，再执行本检查。宿主检查需拥有宿主文件权限；docker inspect Config.Env 和另开的 docker exec env 不完整反映 API 进程从启动脚本继承的变量，运行验证还需第7节。

## 6. 离线初始化，再启动

以下仍在仓库根目录、沿用前面的 Bash 变量。`-p contextdb-example` 将本例 Compose 资源命名与其他项目区分；它不能替代 PG、目录和端口的隔离。

```bash
docker compose -p contextdb-example -f "$CONTEXTDB_COMPOSE_FILE" \
  --profile initialize run --rm initialize
```

初始化职责与失败边界见[共用说明](deployment.md#6-离线初始化再启动)。失败时不要进入启动步骤。

初始化成功后启动单容器 API（含 Worker）与 UI：

```bash
docker compose -p contextdb-example -f "$CONTEXTDB_COMPOSE_FILE" up -d hindsight
docker compose -p contextdb-example -f "$CONTEXTDB_COMPOSE_FILE" ps
```

脚本使用扩展 `hindsight_ext_contextdb.asgi:create_app` 和四个扩展槽，API 启动自动迁移关闭；UI 等待 API readiness。不要用原生 `hindsight-api` 命令旁路启动，也不要另外启动第二个 Worker 来改变当前 merged 部署形态。

## 7. 验证与交付

先检查 API readiness（默认端口）：

```bash
curl --fail --show-error http://127.0.0.1:8888/health/ready
```

预期为 healthy、database connected；Compose healthcheck 还探测 UI，但两者均不证明模型和后台任务成功。配置了远程 UI origin 后，用 `127.0.0.1` 默认 Host 直接访问 UI 可能返回 421，应使用配置的浏览器 origin；Compose 使用专用 UI probe，不能通过关闭 Host 校验解决。

还可以用镜像内的部署 status 命令核对 Admin 身份与实例归属，无需把凭据打印到终端。这里复用本例容器网络命名空间，配置只读挂载；status 不读取原始 MaaS/数据库输入内容：

```bash
CONTEXTDB_RUNTIME_ID="$(docker compose -p contextdb-example -f "$CONTEXTDB_COMPOSE_FILE" ps -q hindsight)"
docker run --rm --user 10001:10001 --network "container:$CONTEXTDB_RUNTIME_ID" \
  --mount type=bind,src=/srv/contextdb/intent.json,dst=/srv/contextdb/intent.json,readonly \
  --mount "type=bind,src=$CONTEXTDB_DEPLOY_DIR,dst=/var/lib/contextdb,readonly" \
  --entrypoint /app/.venv/bin/python "$CONTEXTDB_IMAGE" \
  -m hindsight_ext_contextdb.deployment status \
  --config /srv/contextdb/intent.json --directory /var/lib/contextdb \
  --api-url http://127.0.0.1:8888
```

预期 `ready:true`、`secrets_present:true`。该命令只核对 API、身份与持久秘密，不校验模型/Worker 执行。

最后按[管理员操作](../README.md#admin-quickstart)登录配置的 UI origin，创建测试空间、用户和读写业务 Key，再按[客户接入](../README.md#business-quickstart)做一次 Retain→完成→Recall；使用只读 Key 验证读取权限。异步写入需等 operation 状态完成，不能只看 HTTP 接受成功。观察与知识生成也不是 readiness 的一部分，知识为空不代表部署失败。

向业务用户仅交付对外端点、bank_id 和业务 Key；向管理员交付 UI 地址与密码。记录本次源码提交、镜像 digest、配置版本、验证时间和结果；不将本轮静态文档核对当作这些运行验证。

## 8. 停止、重启与版本更新

操作前阻止新业务并按已有部署流程等待在途请求和后台工作结束；本插件没有额外的全局执行排空屏障。然后只操作本例 Compose 项目：

```bash
docker compose -p contextdb-example -f "$CONTEXTDB_COMPOSE_FILE" stop hindsight
# 配置无变化的普通恢复：复用同一镜像、配置及秘密，不重跑 init 或 render。
docker compose -p contextdb-example -f "$CONTEXTDB_COMPOSE_FILE" start hindsight
```

修改环境文件后，应在维护流程中重建容器使挂载配置被重新加载；单容器 merged 模式会一起影响 API/UI。先按需停止、修改/渲染并恢复人工配置，再 `up -d --force-recreate hindsight`，重做身份和业务验证。源码宿主或分组件部署则按实际受影响组件重启，不能据此要求每次 UI 配置变更都重启 PG。

更新、备份、迁移和恢复约束统一见[共用更新说明](deployment.md#8-停止重启与版本更新)。
