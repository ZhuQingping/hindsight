# ContextDB 节点 Agent 部署合同

本合同是节点自动化的文件与命令接口，不新增网络管理服务。人读顺序见 [集成指南](contextdb-service-integration-guide.md)。插件可用性、API/Worker 拓扑选型和产品边界见总体设计；这里明确如何执行。

## 1 输入格式

输入模型由 `hindsight_ext_contextdb.deployment.DeploymentConfig` 校验，拒绝未知字段和隐式拓扑。JSON Schema 从实际模型生成，避免文档与校验器独立漂移：

```bash
bash hindsight-extensions/contextdb-service/scripts/node-agent.sh schema > deployment.schema.json
bash hindsight-extensions/contextdb-service/scripts/node-agent.sh validate --config /srv/contextdb/input/intent.json
```

| JSON 字段 | 类型/规范 | 必填/默认 |
| --- | --- | --- |
| format | 整数1，部署输入格式；不是数据库版本 | 默认1 |
| instance_id、cloud_tenant_id | 1–128字符，ASCII 字母/数字/下划线/连字符；绑定数据库归属，不能重启时换值 | 必填 |
| topology | `merged`：API内运行原生 Worker；`split`：独立 Worker 容器 | **必填，无默认** |
| database_url_file | 绝对路径；0600普通文件，禁止符号链接；单行 `postgresql://user:encoded-password@host:port/database?...`，必须选择预建数据库 | 必填 |
| maas_api_key_file | 绝对路径；0600普通文件；单行 MaaS Key | 必填 |
| ui_password_file | 绝对路径；0600普通文件；单行至少12字符，不能使用 API Key 作为密码 | 必填 |
| api_port、ui_port | 整数1024–65535，不相等；程序监听端口 | 8888、9999 |
| ui_api_url | UI服务端可访问的 HTTP(S) API origin，无路径、查询串和内嵌凭据；Compose通常`http://api:8888` | 必填 |
| language | `english`、`chinese`、`multilingual`，影响部署验收，不能自动降级为英文 | 必填 |
| text_search | `native`、`pgroonga`、`pg_search`；本合同主动限制为已审视的首版路径，不代表上游只支持这些插件 | 必填 |
| pg_search_tokenizer | `jieba`、`chinese_compatible`、`lindera(chinese)`；仅pg_search允许，中/多语言pg_search必填；还需真实插件版本支持 | 默认null |
| worker_id | 稳定且部署内唯一的1–128字符标识，ASCII字母/数字/下划线/连字符；不要沿用随机容器主机名 | 必填 |
| db_pool_max | 每进程主池/读池各自最大连接数，2–100；多个进程和空间池需另计容量 | 默认10 |
| llm_model | 1–128字符，运维批准的模型；Embedding/Rerank固定，不提供任意环境变量透传 | `deepseek-v4.1-flash` |
| ca_bundle_file | 可选绝对路径；必须在各容器相同路径存在，另挂载只读CA；不会关闭证书校验 | 默认null |

`native + chinese/multilingual` 被拒绝。`pg_search` 的中文分词字段通过并不代表数据库实际可用，后续 preflight 还会验证。PGroonga 依赖 Groonga 系统库及相应许可处理；RDS 不开放时不得在节点端伪装已安装。

秘密文件的值不能包含换行/回车/NUL。路径可公开，值不写入日志。PG URL 建议使用 DNS 名称与 `sslmode=verify-full`，CA 路径在容器内有效；URI 用户名/密码必须百分号编码。校验只检查格式/文件，不连接 PG/MaaS，也不验证授权。

## 2 环境映射

`render` 生成 `api.env` 和 `ui.env`（0700目录内0600文件）；运行脚本通过 shell 读取，**这些不是 Docker env_file 格式**，不要交给 Docker 按另一种语法解析。

| 输出配置 | 来源/含义 |
| --- | --- |
| CONTEXTDB_INSTANCE_ID、CONTEXTDB_CLOUD_TENANT_ID | 归属字段；同一PG库必须匹配 |
| CONTEXTDB_VALIDATION_LANGUAGE | 选择 preflight 语言门槛 |
| HINDSIGHT_API_DATABASE_URL | 秘密文件PG URI；初始化、管理员离线轮换和运行时统一使用此连接 |
| HINDSIGHT_API_HOST、HINDSIGHT_CP_HOST | 固定`0.0.0.0`；外部访问由安全组/HTTPS入口控制 |
| HINDSIGHT_API_PORT、HINDSIGHT_CP_PORT | api_port、ui_port |
| HINDSIGHT_API_WORKER_ENABLED | merged=`true`，split=`false`，仅控制API内Worker |
| HINDSIGHT_API_WORKER_ID | worker_id；独立Worker读取同值，split时API不运行内置Worker |
| HINDSIGHT_API_WORKER_HTTP_PORT | 独立Worker健康/指标端口8889，不向客户发布 |
| HINDSIGHT_API_DB_POOL_MIN_SIZE/MAX_SIZE | 2/db_pool_max；READ_DB_POOL_MIN_SIZE/MAX_SIZE同值 |
| HINDSIGHT_API_TENANT_EXTENSION | `hindsight_ext_contextdb.tenant:ContextDBTenantExtension` |
| HINDSIGHT_API_OPERATION_VALIDATOR_EXTENSION | `hindsight_ext_contextdb.validator:ContextDBOperationValidator` |
| HINDSIGHT_API_HTTP_EXTENSION | `hindsight_ext_contextdb.http:ContextDBHttpExtension` |
| HINDSIGHT_API_MCP_EXTENSION | `hindsight_ext_contextdb.mcp:ContextDBMCPExtension`；MCP_ENABLED=`true`，不设置共享MCP_AUTH_TOKEN |
| HINDSIGHT_API_MIGRATION_ISOLATION | `false`，当前生命周期的进程隔离限制 |
| HINDSIGHT_API_RUN_MIGRATIONS_ON_STARTUP | `false`，阻止API启动不带工作空间身份的通用schema迁移；空间创建由受保护的生命周期流程显式迁移 |
| HINDSIGHT_API_LLM_TRACE_ENABLED / HINDSIGHT_API_AUDIT_LOG_ENABLED | 固定false；原生异步诊断正文写入尚无空间代次保护，不能单独开启 |
| HINDSIGHT_API_VECTOR_EXTENSION | `pgvector` |
| HINDSIGHT_API_TEXT_SEARCH_EXTENSION | text_search；pg_search时可附 TEXT_SEARCH_EXTENSION_PG_SEARCH_TOKENIZER |
| HINDSIGHT_API_LLM_PROVIDER/BASE_URL/MODEL/API_KEY | `openai` / `https://api.modelarts-maas.com/v2` / llm_model / MaaS秘密 |
| HINDSIGHT_API_EMBEDDINGS_PROVIDER | `openai` |
| HINDSIGHT_API_EMBEDDINGS_OPENAI_BASE_URL/MODEL/API_KEY | `https://api.modelarts-maas.com/v1` / `bge-m3` / MaaS秘密 |
| HINDSIGHT_API_RERANKER_PROVIDER | `siliconflow`，复用兼容请求适配 |
| HINDSIGHT_API_RERANKER_SILICONFLOW_BASE_URL/MODEL/API_KEY | `https://api.modelarts-maas.com/v1` / `bge-reranker-v2-m3` / MaaS秘密 |
| HINDSIGHT_API_LOG_LEVEL/LOG_FORMAT | `info` / `json` |
| HINDSIGHT_CP_CONTEXTDB_ENABLED | 固定true，启用本扩展UI及管理代理 |
| HINDSIGHT_CP_DATAPLANE_API_URL | ui_api_url，由UI服务端访问 |
| HINDSIGHT_CP_ACCESS_KEY | 首次从ui_password_file读取，prepare后以持久化ui-secrets.json为准 |
| SSL_CERT_FILE / NODE_EXTRA_CA_CERTS | 可选受信CA：API/Worker设置前者；UI同时设置两者，分别供启动前的Python HTTPS就绪探针及Node请求使用；同一路径需由部署方另行只读挂载，不关闭TLS校验 |

**不生成** `HINDSIGHT_API_EMBEDDINGS_OPENAI_DIMENSIONS`，因为 MaaS bge-m3 不支持请求指定维度；API初始化通过实际返回自动识别1024维。不存在通用的 `HINDSIGHT_API_EMBEDDINGS_DIMENSION` 配置，不要自行添加无效变量。

Rerank请求字段是 `query`、`documents`，由siliconflow适配生成；本轮MaaS实际调用拒绝历史示例的`input`字段，不要通过自制网关把错误请求隐藏掉。

初始化后由秘密文件注入：API/Worker获取 `CONTEXTDB_KEY_PEPPER`；UI获取 `HINDSIGHT_CP_ACCESS_KEY`、`HINDSIGHT_CP_DATAPLANE_API_KEY`。UI启动前清除PG/MaaS/pepper环境。Admin Key与普通Key统一查询PG中的摘要认证，界面密码不是API认证凭据。

## 3 状态机及具体命令

```text
PG/插件/网络准备完成
 → validate（只读文件）
 → render（写本地私有配置）
 → service.sh preflight（只读PG）
 → service.sh init（写秘密文件、迁移管理表、导入管理员、显式迁移原生public共享表）
 → api + ui [+ split worker]（前台，由外部supervisor监管）
 → 业务验收 → 运行
```

文件模板：[intent.example.json](../deployment/intent.example.json)。以下是非容器本机执行的合同，命令由能读取输入秘密、拥有 runtime 目录的同一个服务账号执行；若采用集成指南的 UID10001/0700 容器目录，主机 Agent 必须以该账号或管理权限执行，不能以无权读取的普通账号照抄。容器命令见集成指南。`CONTEXTDB_PYTHON`必须指向匹配源码安装的Python3.11–3.14环境；Node22.12+或24仅用于UI构建/运行。

```bash
cd /opt/contextdb/source
export CONTEXTDB_PYTHON="$PWD/.venv/bin/python"
export CONTEXTDB_DEPLOY_DIR=/srv/contextdb/runtime
AGENT="$PWD/hindsight-extensions/contextdb-service/scripts/node-agent.sh"
SERVICE="$PWD/hindsight-extensions/contextdb-service/scripts/service.sh"
bash "$AGENT" validate --config /srv/contextdb/input/intent.json
bash "$AGENT" render --config /srv/contextdb/input/intent.json --directory "$CONTEXTDB_DEPLOY_DIR"
bash "$SERVICE" preflight --language multilingual
bash "$SERVICE" init
# 后面每条是独立前台进程，由Agent/systemd/容器监管，不在同一shell顺序阻塞执行。
bash "$SERVICE" api
# 另一个监管单元：bash "$SERVICE" ui
# split另一个监管单元：bash "$SERVICE" worker
```

`service.sh preflight` 手动调用时显式传 `--language`；`init/api/worker` 会读取渲染的 `CONTEXTDB_VALIDATION_LANGUAGE`。非容器UI地址应在意图中设置为本机API地址，而非Compose的`api`DNS名。源码UI先执行 `python -m hindsight_ext_contextdb build-ui --source-root "$PWD"`，Dockerfile已在构建期完成此步骤；不能混用旧构建。

| 命令 | 成功/失败及重试规则 |
| --- | --- |
| schema | stdout JSON Schema，不含实际秘密 |
| validate/render | 成功退出0，stdout `{"ok":true,"command":"..."}`；输入/权限错误退出2，统一安全错误信息 |
| render重复执行 | 配置完全相同不修改文件；不同配置默认拒绝；停止受影响组件后用`--replace`明确更新；不覆盖三份初始化秘密，不能轮换UI密码 |
| preflight | 退出0通过，1有失败项；不运行迁移、不创建数据库 |
| init | 可重复执行并核对归属/凭据；失败时保留文件供同输入重试，不能删除秘密重新生成；同一实例串行初始化 |
| api/worker/ui | 前台进程，SIGTERM交给原生优雅关闭；退出由Agent记录并按退避重启；UI等待API ready最多60秒 |
| status | `--config ... --directory ... [--api-url http://127.0.0.1:8888]`；退出0 ready，1未ready，2配置错误；JSON返回健康/秘密校验及实例身份匹配结论，不输出响应体/凭据 |

配置生成是两个独立原子文件，不是跨文件事务。更新时必须先停止实例，渲染失败不能启动；使用相同意图修正后重跑。初始化仅一个控制者，禁止多节点同时生成同一目录的秘密。

`service.sh init`在管理表初始化之后，显式执行原生`python -m hindsight_api.admin.cli run-db-migration --schema public --embedding-dimension 1024`。该条命令局部禁用TENANT扩展，不做租户发现，只初始化共享任务表所在的public；不变更后续API/Worker扩展配置。该步失败不得启动API。

升级已有空间的原生业务表时，先停止全部API和Worker，再从`ctxdb_meta.workspaces.schema_name`逐个确定目标schema，按批准的升级步骤执行下面命令。不能不带`--schema`使用通用租户发现，也不能为省事把启动迁移改成true；否则旧启动请求可能误操作同名重建后的空间。必须由发行版本的升级手册列出具体目标和回退点。

逐空间升级的具体命令（全部写入者已停止，SCHEMA来自元数据且已审核；PG认证按同版私密api.env加载）：

```bash
set -a
source "$CONTEXTDB_DEPLOY_DIR/api.env"
set +a
: "${SCHEMA:?先从元数据确认本次目标schema}"
HINDSIGHT_API_TENANT_EXTENSION='' "$CONTEXTDB_PYTHON" -m hindsight_api.admin.cli run-db-migration \
  --schema "$SCHEMA" --embedding-dimension 1024
```

这里局部清除Tenant扩展，与public离线迁移相同；不把缺失pepper的裸CLI当成可运行的托管升级入口。完整逐schema循环及失败停止规则见[升级手册](contextdb-optimized-guide.md)。

## 4 容器交付边界

同一镜像提供API、Worker和UI，分别用 `service.sh api/worker/ui` 前台启动；不是一个容器里用shell后台进程拼装三个服务。`merged` 仅指原生API进程内运行Worker；`split` 用独立API与Worker容器，PG任务表仍为同一个源。

Compose示例提供只读运行期文件系统、只读秘密卷、临时目录、UI独立64MiB Next缓存tmpfs、日志轮转、独立一次性初始化和API/Worker健康检查。它不创建RDS/插件，不代替ECS Agent的实例调度，不证明云上HA。API与Worker分离不自动带来完整高可用，也不隔离PG和模型配额。

`CONTEXTDB_IMAGE`必须是本次构建镜像固定标签或发布摘要，不能用`latest`；部署记录保存镜像ID/摘要、源码提交/补丁、意图文件SHA256、非秘密验收结果。默认UID10001，输入/持久化目录要匹配该UID或使用批准的用户覆盖。不要通过chmod777解决权限问题。

`compose.yaml`的`${CONTEXTDB_API_PORT}`、`${CONTEXTDB_UI_PORT}`与渲染配置必须一致。持久化目录不属于容器可销毁层；`down`/升级不得删除秘密卷。扩展为多个Worker时每副本需要不同稳定worker_id和独立渲染配置，不能直接`--scale worker=2`共享固定ID；本示例仅一个Worker。

## 5 最小验收记录

1. 记录代码/镜像版本、PG版本/UTF8、实际插件版本、模型名、拓扑、端口，不记录Key/密码/连接URI。
2. 空库初始化与重复init均成功，管理员仅一个，秘密文件内容不变；重启后客户指定UI密码仍可登录。
3. API/UI可从允许的其他机器访问，UI后台地址在其容器内可达；业务Key不能作为UI密码登录。
4. 两空间隔离、受限Key越权失败，原生REST和MCP调用正常；中英文样本实际检索成功。
5. split验证独立Worker健康且异步retain最终完成；停止Worker后记录任务等待现象，再启动验证恢复；merged不同时启动额外Worker。
6. 真实MaaS三类调用成功并确认Embedding1024维；只检查`/health/ready`不够。
7. 备份/恢复数据库与原秘密，在独立测试环境验证；日志与诊断材料脱敏。

任何一项未执行都标为未验证，不能因为单元测试通过就标记RDS部署、容器HA、模型质量或恢复演练通过。

## 私有CA、文件挂载与升级补充

配置ca_bundle_file时，Agent本机状态检查也使用该CA；API/Worker和UI必须在同一绝对路径看到只读CA文件。为相应Compose服务添加volumes条目，例如 `/srv/contextdb/ca.pem:/srv/contextdb/ca.pem:ro`，不要把整个秘密目录挂到全部组件。当前运行服务文件按组件单独挂载；更新文件后使用 `docker compose ... up -d --force-recreate api ui`（split另含worker）重新建立挂载，保留原runtime目录。CA不得通过关闭证书校验替代。

首发管理元数据结构版本固定为1。migrate仅初始化新库，或核对已经采用当前结构的数据库；开发期试验结构不作为已发布版本，不自动升级或直接改号。已有试验库先保留数据和配置备份，再使用新的专用数据库验证；不能仅修改metadata_version冒充结构匹配。未来正式发布结构变更时，再从版本1增加有序迁移。

首版不支持原生 Webhook、持久 LLM Trace 和原生业务 Audit：非空 WEBHOOK_URL、缺省或开启的 LLM_TRACE_ENABLED、开启的 AUDIT_LOG_ENABLED 均拒绝。Admin/内部配置不能开启 audit_log_enabled，旧Bank开启审计或enabled Webhook时须先停用再升级。ContextDB管理审计audit_events和运行日志/指标不受影响；详见[功能边界及原因](contextdb-service-research-validation.md#4-删除重建保护与首版限制)。


数据库连接只配置 HINDSIGHT_API_DATABASE_URL；初始化、管理员离线轮换及API/Worker使用相同目标库和专用服务账号。管控预建数据库和安装插件，服务账号运行时须能创建空间schema、表和索引。不支持单独的bootstrap连接地址，遗留设置不能覆盖或替代此变量。
