# ContextDB 独享版：管控与节点部署指南

本指南用于管控、ECS 节点 Agent 与 Hindsight 开发人员联调。字段规范及自动化入口见 [部署合同](contextdb-deployment-contract.md)。必须使用同一次构建的 ContextDB API、扩展和 UI；上游通用镜像不包含本仓新增功能。

## 1 谁负责什么

| 责任方 | 负责的输入与操作 |
| --- | --- |
| 华为云管控 | 创建 ECS/RDS、网络及证书；预建 PG 数据库和服务账号；安装数据库端插件；申请 MaaS Key；接收客户指定的 UI 密码；下发部署意图及秘密文件 |
| 节点 Agent | 校验并渲染配置；拉取指定镜像；执行一次初始化；监管 API/UI/Worker，处理重启和日志采集。使用现有本机命令，不增加实例管理 HTTP 服务 |
| Hindsight 服务 | 初始化管理表；创建工作空间 schema/业务表；提供业务 REST/MCP、UI 和工作空间/用户/Key 管理 |
| 浏览器/业务应用 | 浏览器使用 UI 密码；业务使用授权 Key。二者都不需要 PG 密码、MaaS Key 或后台 Admin Key |

数据库不存在时，外部 PG 部署会失败；Hindsight 不会替管控创建数据库或 RDS。实例启动与工作空间初始化是不同步骤：启动完成后，由管理员在 UI 创建空间，也可调用管理 REST 接口验证。

## 2 PG 需要提供什么

| 输入 | 要求 |
| --- | --- |
| 地址、端口 | API 和 Worker 容器均可访问的 PG 地址，通常 5432；容器里的 `127.0.0.1` 指容器自身 |
| database | 预建 UTF8 专用数据库；一独享实例一数据库；不要复用已有应用库 |
| user/password | 专用 LOGIN 角色，拥有该数据库和服务 schema，允许建 schema、表、索引及执行迁移；不授予 SUPERUSER、CREATEDB、CREATEROLE、BYPASSRLS |
| TLS | 生产连接使用 `sslmode=verify-full` 和受信 CA；主机名必须匹配证书。密码在 URI 中必须百分号编码 |
| 基础插件 | 目标数据库中启用 `vector`、`pg_trgm`、`btree_gin`；安装文件存在不等于已在目标库启用 |
| 全文插件 | 明确选择一个后端。英文可用 native；本仓当前中英文路径可用 PGroonga，或经实际版本/分词器验收的 pg_search。参见设计文档全文候选方案 |
| 可观测性 | `pg_stat_statements` 可选。需要共享预加载时由 PG 运维安排，节点初始化不擅自修改实例参数或重启数据库 |

### 新库准备命令

由 PG 管理员执行。命令只创建新对象，遇到已有同名库/角色就停止，不接管、不删除旧库。

```bash
export REPO=/opt/contextdb/source
export PGADMIN_URL='postgresql://provisioner@pg.example.internal:5432/postgres?sslmode=verify-full'
read -r -s -p '新服务账号密码: ' CONTEXTDB_NEW_DB_PASSWORD
printf '\n'
export CONTEXTDB_NEW_DB_PASSWORD
psql -X "$PGADMIN_URL" -v ON_ERROR_STOP=1 \
  -v service_role=contextdb_service -v service_db=contextdb \
  -f "$REPO/hindsight-extensions/contextdb-service/deployment/prepare-pg.sql"
unset CONTEXTDB_NEW_DB_PASSWORD
```

`provisioner` 的 PG 认证通过受保护的 `.pgpass`/平台秘密注入处理，不在命令行写密码。RDS 先通过平台支持的扩展列表安装基础插件。如果选择 PGroonga，确认其服务端安装完成后，由有权限的数据库管理员执行：

```bash
psql -X 'postgresql://provisioner@pg.example.internal:5432/contextdb?sslmode=verify-full' \
  -v ON_ERROR_STOP=1 -c 'CREATE EXTENSION pgroonga;'
```

**华为云 RDS 未开放的插件不能在 ECS 上编译后替 RDS 安装。** 必须由 RDS 产品能力支持，或改用自建 PG/另行完成全文适配。本轮不承诺未经验证的 native+中文分词器等价替代。选择不满足语言要求的后端时，校验应失败。

### 客户自带 PG 的隔离边界

客户普通 SQL 账号不要拥有服务数据库、服务角色或 `ctxdb_meta`、`ctxdb_ws_*` schema，不授予这些表的 SELECT/DML/DDL，不允许 SET ROLE 为服务角色。服务账户不交付给业务使用；不要把工作空间权限映射成数据库超级权限。

客户若拥有同一 PG 的超级用户、数据库所有者或底层主机控制权，就能修改/删除服务数据，**不能保证元数据不被破坏**。这属于部署信任边界；备份、变更约束和检测只能帮助恢复，不能替代权限隔离。禁止为“保护元数据”错误地承诺能阻止 root。

## 3 下发配置与第一次启动

节点需要容器运行时及 Compose v2。先构建本分支镜像（构建机需要访问 Python/npm/基础镜像仓库）；发布时记录镜像摘要，Agent 只拉取批准的摘要。

```bash
cd /opt/contextdb/source
REV=$(git rev-parse HEAD)
docker build --build-arg SOURCE_REVISION="$REV" \
  -f hindsight-extensions/contextdb-service/deployment/Dockerfile \
  -t "contextdb:$REV" .
docker image inspect "contextdb:$REV" --format '{{.Id}}'
export CONTEXTDB_IMAGE="contextdb:$REV"
```

若直接拉取已发布镜像而不在节点构建，先将 `CONTEXTDB_IMAGE` 设为批准的镜像摘要；后续两条渲染路径和 Compose 使用同一个值。

Dockerfile 支持 `NODE_IMAGE` 构建参数；正式发布应固定批准的 Node24 基础镜像摘要。源码脏树构建仅用于开发，不能用 HEAD 标签冒充已提交发布版本；记录实际源码补丁及构建输出。源码构建失败应交付错误证据，不继续使用旧上游镜像。

管控下发以下文件，权限由 Agent 设置。`database-url` 包含完整 PG URI，`maas-key` 包含 MaaS Key，`ui-password` 包含用户指定密码，均为单行；不要把值放入 Git、工单或命令行参数。

```text
/srv/contextdb/input/intent.json       非秘密部署意图
/srv/contextdb/input/database-url      0600，PG URI
/srv/contextdb/input/maas-key          0600，MaaS Key
/srv/contextdb/input/ui-password       0600，独立 UI 密码，至少12字符
/srv/contextdb/runtime/                0700，必须持久化备份
```

Linux节点以镜像默认UID10001运行时，Agent可用管理员权限执行以下目录准备，再将收到的三个秘密文件设为0600、属主10001。不要用chmod777或在容器中临时生成后丢失：

```bash
sudo install -d -m 0700 -o 10001 -g 10001 /srv/contextdb/input /srv/contextdb/runtime
sudo chown 10001:10001 /srv/contextdb/input/database-url /srv/contextdb/input/maas-key /srv/contextdb/input/ui-password
sudo chmod 0600 /srv/contextdb/input/database-url /srv/contextdb/input/maas-key /srv/contextdb/input/ui-password
```

从 [意图模板](../deployment/intent.example.json) 复制 `intent.json`，修改实例、租户、秘密文件路径、端口和明确的拓扑选择。示例 `ui_api_url=http://api:8888` 是 **UI 容器服务端**访问 API 的地址，不是浏览器地址。

```bash
cd /opt/contextdb/source
export CONTEXTDB_PYTHON="$PWD/.venv/bin/python"
AGENT="$PWD/hindsight-extensions/contextdb-service/scripts/node-agent.sh"
sudo bash "$AGENT" validate --config /srv/contextdb/input/intent.json
sudo bash "$AGENT" render --config /srv/contextdb/input/intent.json \
  --directory /srv/contextdb/runtime
sudo chown 10001:10001 /srv/contextdb/runtime/api.env /srv/contextdb/runtime/ui.env
```

以上主机渲染分支由具备管理权限的节点Agent执行，render后必须将0600配置文件属主设为容器UID10001；仅chown目录不够。每次 --replace 原子替换后也要核对属主。实际采用其他非root UID时，两处统一替换。

节点没有 Python 依赖时，可用同版镜像运行渲染器。输入挂载只读，输出持久化目录可写；镜像默认 UID10001，需要提前给目录和输入文件设置对应所有者，或者使用批准的 UID/GID 覆盖。`--user` 不改变文件权限检查要求。

```bash
docker run --rm --entrypoint /app/.venv/bin/python \
  -v /srv/contextdb/input:/srv/contextdb/input:ro \
  -v /srv/contextdb/runtime:/var/lib/contextdb:rw \
  "$CONTEXTDB_IMAGE" -m hindsight_ext_contextdb.deployment render \
  --config /srv/contextdb/input/intent.json --directory /var/lib/contextdb
```

渲染只生成私有 `api.env`、`ui.env`，尚未修改 PG。随后初始化会写 PG，生成并持久保存后台 Admin Key、pepper 和 UI 秘密；重复初始化核对既有凭据，不重新生成。

```bash
export CONTEXTDB_DEPLOY_DIR=/srv/contextdb/runtime
export CONTEXTDB_API_PORT=8888 CONTEXTDB_UI_PORT=9999
COMPOSE=/opt/contextdb/source/hindsight-extensions/contextdb-service/deployment/compose.yaml
docker compose -p contextdb -f "$COMPOSE" --profile initialize run --rm initialize
# intent.topology=merged 时：
docker compose -p contextdb -f "$COMPOSE" up -d api ui
# intent.topology=split 时，只执行下面一条，不能与 merged 配置混用：
# docker compose -p contextdb -f "$COMPOSE" --profile split up -d api worker ui
docker compose -p contextdb -f "$COMPOSE" ps
curl -fsS http://127.0.0.1:8888/health/ready
```

上述命令展示两种启动方式，**实施时按 intent.topology 二选一**。split 配置遗漏 Worker，API 仍可能 ready，但异步记忆任务无人处理；启动验收必须实际 retain 并检查任务完成。merged 配置再启动独立 Worker 会增加并发和连接消耗，不能视为同一配置。

默认监听 `0.0.0.0`，API8888、UI9999，允许其他机器通过 ECS 地址访问。安全组、负载均衡、HTTPS 和鉴权由部署层配置；不要把“外部可达”实现为关闭验证。端口改动必须同时修改 intent 的 `api_port/ui_port`、`ui_api_url` 和 Compose 发布端口变量；容器内部监听与外部映射需一致。

## 4 模型、凭据与重启

| 项目 | 首版配置 |
| --- | --- |
| LLM | OpenAI 兼容适配，`https://api.modelarts-maas.com/v2`，`deepseek-v4.1-flash`；运维字段 `llm_model` 可在评测批准后调整，客户 UI 不暴露 |
| Embedding | OpenAI 兼容适配，`https://api.modelarts-maas.com/v1`，`bge-m3`；运行初始化探测实际1024维，**不发送 dimensions** |
| Rerank | 复用 siliconflow 适配，`https://api.modelarts-maas.com/v1`，`bge-reranker-v2-m3` |
| UI 密码 | 客户指定；`prepare` 首次复制到 `ui-secrets.json`，后续保持不变；不是 PG 密码或业务 Key |
| Admin Key | 离线生成，写 `admin-key.json`，数据库只存 HMAC；UI 后台从 `ui-secrets.json` 获取。用户浏览器不接触此 Key |
| Pepper | `api-secrets.json`；只给 API/Worker，不能丢失或随重启重生成 |

当前使用用户已有验证路径 `/v2`、`/v1`，不要未经验证就自动替换成另一个 MaaS 网关路径。Key 和模型要在目标区域及账号确实可调用；API ready 不能证明模型调用、维数和效果正确。

本轮真实协议探测中，MaaS `/v1/rerank` 要求查询字段为 `query`，历史示例的 `input` 返回400。复用的 siliconflow 适配发送 `query` 和 `documents`；不要照搬旧手写请求。

重启使用原 `runtime` 目录；不要重新生成秘密、删目录或重新创建数据库。普通渲染不能修改已持久化的 UI 密码。Admin Key/pepper 轮换需要专门维护步骤，不能通过覆盖环境文件实现。升级前备份服务数据库和秘密，停止写入后按同版迁移/恢复流程执行。

配置固定`HINDSIGHT_API_RUN_MIGRATIONS_ON_STARTUP=false`。新空间由管理生命周期显式初始化业务schema；已有空间升级要停止API/Worker后，针对元数据记录的各个schema执行原生迁移，不让API启动自行遍历或创建schema。此项是同名删除重建的安全要求，不能改回默认true。

API/Worker运行期只挂载api.env和api-secrets.json；UI只挂载ui.env和ui-secrets.json，均只读；仅初始化容器获得整个runtime可写目录。UI另有64MiB临时Next缓存，重启可丢弃，不作为持久数据备份。备份应同时包含数据库和这组秘密，并加密保管。只备份其中一项无法保证恢复可用。

## 5 Agent 的验收与失败处理

```bash
sudo bash "$AGENT" status --config /srv/contextdb/input/intent.json \
  --directory /srv/contextdb/runtime --api-url http://127.0.0.1:8888
docker compose -p contextdb -f "$COMPOSE" logs --tail=200 api worker ui
docker compose -p contextdb -f "$COMPOSE" stop
```

status校验私密文件格式与权限、API健康正文，并用后台Admin Key检查实例/租户身份与输入配置匹配；不证明Worker、MaaS或工作空间业务正常。完整验收还需登录 UI、创建两个空间、创建受限 Key、retain/recall/reflect、REST/MCP 越权验证及重启复验。日志含业务输入和故障细节，必须脱敏后对外分享；不收集 `docker compose config`、`docker inspect` 全量环境或 env/秘密文件原文。

证书代理环境使用受信 CA：容器内挂载相同绝对路径的 CA 文件，intent 设置 `ca_bundle_file`，API 使用 `SSL_CERT_FILE`，UI 使用 `NODE_EXTRA_CA_CERTS`。API的CA文件应是包含公共根证书和企业CA的完整信任包，避免替换后无法验证MaaS证书。Compose 示例没有自动挂载 CA 或配置代理；按企业网络显式补充只读证书卷及 `HTTPS_PROXY/NO_PROXY`，构建期也需要相应受信配置。禁止 `verify=false`、`NODE_TLS_REJECT_UNAUTHORIZED=0` 或 monkey patch 关闭 TLS 校验。

## 私有CA、文件挂载与升级补充

配置ca_bundle_file时，Agent本机状态检查也使用该CA；API/Worker和UI必须在同一绝对路径看到只读CA文件。为相应Compose服务添加volumes条目，例如 `/srv/contextdb/ca.pem:/srv/contextdb/ca.pem:ro`，不要把整个秘密目录挂到全部组件。当前运行服务文件按组件单独挂载；更新文件后使用 `docker compose ... up -d --force-recreate api ui`（split另含worker）重新建立挂载，保留原runtime目录。CA不得通过关闭证书校验替代。

首发管理元数据结构版本固定为1。migrate仅初始化新库，或核对已经采用当前结构的数据库；开发期试验结构不作为已发布版本，不自动升级或直接改号。已有试验库先保留数据和配置备份，再使用新的专用数据库验证；不能仅修改metadata_version冒充结构匹配。未来正式发布结构变更时，再从版本1增加有序迁移。

首版服务化推荐 API、Worker、UI 同 ECS 分容器，合并模式保留给小规格和本地验证；这是运维及资源隔离选择，不是已取得生产吞吐优胜结论。完整依据见[补充调研](contextdb-service-research-validation.md)。

渲染器固定关闭原生持久 LLM Trace/Audit，并禁止原生 Webhook；不能通过临时export打开这些未受代次保护的写入。ContextDB管理审计继续保留，详情见[首版限制](contextdb-service-research-validation.md#4-删除重建保护与首版限制)。

源码镜像构建使用BuildKit。依赖安装通过锁文件固定；Docker构建关闭npm安装时的隐式audit/fund网络请求以保证构建职责明确，发行流水线须单独执行批准的依赖/镜像安全扫描，不能把安装成功当成安全扫描通过。


数据库连接只配置 HINDSIGHT_API_DATABASE_URL；初始化、管理员离线轮换及API/Worker使用相同目标库和专用服务账号。管控预建数据库和安装插件，服务账号运行时须能创建空间schema、表和索引。不支持单独的bootstrap连接地址，遗留设置不能覆盖或替代此变量。
