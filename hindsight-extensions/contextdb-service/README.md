# ContextDB 独享实例服务

基于 Hindsight v1.0.0，增加工作空间、用户和 API Key 管理。记忆操作继续使用原生 REST/MCP 与内置 Worker。

**评审从[文档入口](docs/README.md)开始。** 详细设计、部署、运维及图表统一在[资料仓](https://github.com/ZhuQingping/ContextDB-Research/blob/main/hindsight/README.md)维护，代码仓不再保留阅读副本。

实现位于 `hindsight_ext_contextdb/`，部署材料位于 `deployment/`，命令位于 `scripts/`，自研回归测试物理集中在 `tests/{python,system,ui}`；UI与系统故事继续复用宿主工程的运行环境，不复制SDK或服务桩。当前边界和TODO以资料仓特性设计为准。

管理接口的机器可读定义保留在[schemas/](schemas/contextdb-control-plane.openapi.yaml)，由代码生成并由测试校验；变更接口时更新它。

扩展专用配置示例见 [contextdb.env.example](deployment/contextdb.env.example)；运行配置由部署脚本根据 `deployment/intent.example.json` 生成。

API 由扩展自己的 `hindsight_ext_contextdb.asgi:create_app` 启动，外层准入保护同时覆盖原生 REST/MCP；部署脚本已使用此入口。直接运行原生 API 命令且配置本扩展时会拒绝启动，避免漏装保护层。原生应用仍负责初始化、内置 Worker 和关闭流程。

## PG 部署辅助脚本

SQL 保留为可执行文件，README 说明用途；完整操作步骤见资料仓的[PG 准备与权限边界](https://github.com/ZhuQingping/ContextDB-Research/blob/main/hindsight/deployment/contextdb-service-integration-guide.md#pg-preparation)。不在 README 复制 SQL 正文。

| 脚本 | 用途与执行时机 |
| --- | --- |
| [prepare-pg.sql](deployment/prepare-pg.sql) | 首次部署前，由管控/PG 管理员创建专用服务账号、UTF8 数据库，并在目标库启用 vector、pg_trgm、btree_gin。要求数据库端已有插件安装文件和足够的管理权限；遇到同名角色或库即停止，不用于接管已有库。它不创建 ContextDB 管理表。 |
| [pg-role-boundary.sql](deployment/pg-role-boundary.sql) | 客户需要普通 SQL 账号直连 PG 时，由 PG 管理员针对 ctxdb_meta 和每个工作空间 schema 配置权限，防止该账号直接读写服务数据。角色、数据库和目标 schema 必须预先存在；新增空间也需按部署策略配置。 |

两个脚本均不由 API 启动或 `service.sh init` 自动执行。后者的权限示例不负责 API 工作空间授权，也无法限制真正的 PG 超级用户、服务对象所有者或底层主机管理员。仅通过 API 使用服务、未开放客户 SQL 账号时，无须执行该权限示例。

## 测试入口

在仓库根目录准备依赖后，按运行环境分别执行；不要把三类测试放进同一个pytest环境。

```sh
# 插件元数据/策略/部署测试；默认只收集 tests/python
cd hindsight-extensions/contextdb-service
uv run pytest -v
# 或明确指定，旧的 pytest tests/ 命令请改为这个入口
uv run pytest tests/python -v

# 系统故事物理在插件，仍使用原system-test依赖、SDK、server和模型桩
cd ../../hindsight-system-tests
uv run --frozen --group contextdb pytest -c ../hindsight-extensions/contextdb-service/pytest-system.ini ../hindsight-extensions/contextdb-service/tests/system -v

# 扩展专属UI测试由原Control Plane的同一Vitest配置收集
cd ..
npm test --workspace=hindsight-control-plane
npm run lint --workspace=hindsight-control-plane
```

`tests/python/support`保存合成身份、管理ASGI装配、生命周期double和PG资源owner；`tests/system/support`保存独立部署/客户端/UI进程owner。conftest仅提供pytest fixture包装，故障清理直接测试普通owner。原生词条、原生API和普通系统故事保留宿主位置；原生system conftest与插件系统配置只共用 `hindsight_system_tests.pytest_plugin` 中的模型替身、规则重置及未匹配/格式错误校验；原生服务器、客户端与Bank fixture保留原conftest，不复制测试框架。

生产UI故事需要同源码构建的standalone与ContextDB manifest。正式构建使用 `python -m hindsight_ext_contextdb build-ui --source-root <checkout>`；从system环境调用CLI时显式设置 `PYTHONPATH=<checkout>/hindsight-extensions/contextdb-service`。已有 `CONTEXTDB_UI_SERVER`/`CONTEXTDB_TEST_NODE_BIN`可选择隔离产物和Node。产物和源码一致性只在UI fixture启动前校验一次。普通本地无产物时仍可跳过；独立CI job直接运行112故事，再执行 `python scripts/check_production_ui.py <junit-report.xml>`，要求两个Worker参数项完整通过且零跳过；路径按当前工作目录调整。无需额外开关。

CP的TypeScript配置、ESLint根目录调用、Prettier、knip和CI触发范围均包含插件UI测试；不维护第二个Node项目、Vitest配置或依赖锁。`tests/contracts`的跨语言合同检查需要Node，单独在有Node的CI步骤运行，不属于默认插件Python收集。


### Bank配置读取的字段权限

`GET /v1/default/banks/{bank_id}/config`保留正常读取能力。自研ASGI传输层在原生认证/操作校验完成后，把`overrides`投影到已过滤`config`的可见字段集合，使用宿主公开响应模型校验JSON；GET、PATCH和DELETE配置响应使用同一路径。当前业务Key得到200和两个空对象，Admin保留允许配置的读写/重置；普通MCP `get_bank`读取基本信息不变。只处理配置响应，原生引擎、方法和存储均不修改，不重放权限钩子或新增授权查询。

实现位于插件`transport.py::_bank_config_json`和既有纯ASGI中间件；复用任务诊断的定点JSON缓冲机制，不引入BaseHTTPMiddleware、不缓冲Retain/MCP/SSE。回归位于插件`tests/python/test_transport.py`及`tests/system/test_114_contextdb_diagnostic_credentials.py::test_business_bank_config_hides_overrides_without_rejecting_reads`，覆盖空/部分字段、分块/压缩/错误响应、单次认证查询及双Worker真实SDK/MCP。


### 初始化与分块读取

实例初始化仅准备`ctxdb_meta`与管理员身份；原生业务/任务表随空间创建进入`ctxdb_ws_<bank_id>`，public保留扩展对象，不运行全量业务迁移。已有用户库不自动清理。系统fixture在全部故事结束后检查public无表。

原生`GET /v1/default/chunks/{chunk_id}`通过扩展transport复用宿主chunk codec与认证上下文定位空间，不改API/SDK；覆盖见`tests/system/test_116_contextdb_chunks.py`。管理UI去掉Key明文60秒及标签隐藏清理，仍保留明确关闭、离页/卸载/用户切换和迟到回调保护；真实浏览器视觉验收仍须另做。
