# ContextDB 团队集成验证记录

**最新为SEC-01插件内修复，见第10章；第8章为a05适配，第9章为首次PR提交检查。** 第1～7章保留此前0e283e923及文档恢复的历史证据和当时命令；其中旧测试路径/CONTEXTDB_REQUIRE_UI_TESTS不再是当前入口，不能将旧计数与本轮相加。

## 1. 固定输入与环境

- 日期：2026-10-20；本机macOS/Apple Silicon；Node v23.11.0（CI固定Node 24）；原生API Python 3.11，扩展独立环境Python 3.12。
- 团队基线：`57bbfd2d39685091ce65a4742e43c6efbcb4c78e`；本轮通过 `git ls-remote team_repo refs/heads/main` 再次确认远端main仍指向该提交。
- 功能来源：`ddf5c360001f1db46f925b1822803ac9bff1119e`。
- 分支：`feature/contextdb-management`，工作目录 `integration/rsixdb-contextdb`。
- PG由测试临时创建：唯一实例名、空闲端口、临时数据目录；使用结束仅停止自己创建的实例，不连接当前部署数据库。初轮原生迁移夹具尝试复用固定测试实例时遭遇PG认证失败，后续已改为私有实例，不删除旧实例或修改其角色。
- 系统故事使用真实API/Worker/生产UI和发布SDK；LLM/embedding/reranker使用确定性stub。不同Worker模式是兼容验证，首发部署仍为API内置Worker。

## 2. 命令与结果

下表记录本次实际执行结果，以最终完整轮为准。日志和JUnit位于本机 `/tmp/contextdb-integration-*`，不入Git。

| 状态 | 命令/范围 | 结果 |
| --- | --- | --- |
| PASS | UI：`npx vitest run --maxWorkers 4` | 70文件、522通过 |
| PASS | `python -m hindsight_ext_contextdb build-ui --source-root .`（PYTHONPATH指向扩展目录） | 生产构建、standalone和源码/bundle指纹通过 |
| PASS | UI：`npx tsc --noEmit` | 通过 |
| PASS | 扩展：`verify_integration.py extension`（命令见下） | 342通过、无跳过（包含非超级用户源码重复初始化、规范化Host及Compose实际健康命令） |
| PASS | 扩展Ruff及ty | 通过 |
| PASS | `./scripts/hooks/lint.sh` | 通过；无关embed格式化未纳入提交 |
| REVIEWED | `./scripts/hooks/check-unused.sh` | 已审阅提示，不作为测试结果 |
| PASS | UI：`npx knip@5 --include files,dependencies --no-progress` | 通过 |
| PASS | `bash scripts/sync-product-brand.sh --check` | 通过 |
| PASS | 扩展 `scripts/generate_openapi.py --check` | 通过，管理契约未变 |
| PASS | 13个现有图内容渲染、19目标品牌往返 | 通过；这些检查不覆盖MDX无效图引用 |
| KNOWN FAILURE | 文档skill生成 / 完整提交钩子 | 团队基线既有问题，[Issue #14](https://github.com/RSIXDB/hindsight/issues/14)；本分支保留基线，不纳入修复，不标记为通过 |
| INTERRUPTED | 原生API初轮大范围扫描 | 运行至5964通过后中止旧快照：28失败、29错误、37跳过、2预期失败；用于定位，不能计为通过 |
| PASS | 适配后的原生Worker/HTTP/品牌/provider针对回归 | 已完成17、184、70及23项分组通过；后续以完整轮为准 |
| PASS | 原生迁移/向量专用PG回归 | 23通过 |
| PASS | 适配后的原生API非真实LLM/集成/slow/Oracle完整轮：`verify_integration.py api` | 10858通过、186条件跳过、5既有预期失败，0失败/错误（420.49秒） |
| PASS | 全量system故事：`verify_integration.py system` | 414通过、2条件跳过、11子测试通过，0失败/错误（991.48秒） |
| PASS | 适配后故障/生产UI故事（强制存在UI构建） | 6通过（两种Worker模式，包含退出后旧Cookie重放被拒绝） |

扩展首轮跳过的是需要显式管理连接的真实源码部署测试；随后使用专用PG提供该连接，全量329项均通过，无跳过；加入Compose实际健康命令回归后，该轮全量330项通过、无跳过（100.16秒）；补齐Host规范化矩阵后的最终全量342项通过、无跳过（23.70秒）。

## 3. 可复现的测试隔离

仓库内提供受控包装脚本：先安装根目录、扩展和system依赖，再从根目录执行下列命令。脚本只停止自己创建的PG，extension模式同时为离线部署测试提供专用管理连接；system模式强制生产UI存在。

```sh
.venv/bin/python hindsight-extensions/contextdb-service/scripts/verify_integration.py extension
.venv/bin/python hindsight-extensions/contextdb-service/scripts/verify_integration.py system
HF_HUB_OFFLINE=1 .venv/bin/python hindsight-extensions/contextdb-service/scripts/verify_integration.py api
```

`HF_HUB_OFFLINE=1` 只适用于本机已缓存所需模型时；干净环境需先准备模型。原生纯单测还需uv.lock中的可选Oracle驱动（本轮使用oracledb 3.4.2），不需要连接Oracle服务。


原生API测试的标准选择与CI非LLM路径一致，并排除本机未提供环境的integration/slow/Oracle：

```sh
cd hindsight-api-slim
uv run --frozen pytest tests -n 4 -m 'not hs_llm_mat and not hs_llm_core and not integration and not slow and not oracle' --tb=short
```

运行前由测试包装脚本创建专用PG并注入 `HINDSIGHT_API_DATABASE_URL`，同时设置 `PYTHON_DOTENV_DISABLED=1` 及 `HINDSIGHT_TEST_PRIVATE_DATABASE=1`。后者由测试夹具为每个xdist Worker创建独立PG并在结束时停止，隔离跨Worker的索引DDL；不改变默认开发/CI共享PG行为。不应把开发者当前服务的连接串直接交给该全量测试。

系统故事：先安装 `hindsight-system-tests` 的contextdb分组、构建同版生产UI，再以 `HINDSIGHT_SYSTEM_TEST_DATABASE_URL` 指向专用原生测试PG；ContextDB故事自行创建PG。启动器清理HINDSIGHT/CONTEXTBASE/历史AGENTSTRATUM的API变量，只使用测试显式配置。

```sh
cd hindsight-system-tests
CONTEXTDB_REQUIRE_UI_TESTS=1 uv run --frozen --group contextdb pytest tests -v --tb=short
```

## 4. 失败定位与重测规则

首次UI测试暴露旧导航mock、移植来的外部模板链接/翻译键和文案基线差异，已修正后全量通过。首次全量运行的原生Worker测试及新增MCP故障故事仍断言原始内部错误，已按团队已存在的脱敏契约适配。代理测试已隔离大小写环境变量。另适配团队品牌相关banner/Codex请求/metrics及hook的公共配置变量。原有真实LLM事实抽取分析/输出比率测试补上hs_llm_core分类；Docker/S3测试补上integration分类，仍保留在对应有条件的测试路径，不属于本次非外部依赖回归。dotenv测试显式解除托管关闭标志后验证.env读取。原生初轮在夹具/测试适配后主动中止旧收集快照，再用最终测试代码从头执行完整轮。保留原失败日志 `/tmp/contextdb-integration-api-initial.log`；适配后重测结果单独记录，不将旧失败隐藏为通过。

后续共享PG完整轮在3058通过后发现一次并发索引DDL死锁而中止，保留 `/tmp/contextdb-integration-api-shared-pg.log`；该索引用例独立通过后，改用每Worker私有PG。首个私有PG完整轮在2258通过后遇到异步锁跨事件循环错误而中止，保留 `/tmp/contextdb-integration-api-worker-private-initial.log`。定位到团队原有方言单例中的索引锁：竞争后绑定旧用例循环。测试夹具现逐用例重建该单例，仍保留用例内部共享，不修改运行代码或添加自动重试。大批次模块独立3项通过；最终以无重试完整轮为准。

系统故事初轮为411通过、3失败、2跳过及11个通过的子测试。两个MCP故障用例和一个reflect故障用例仍期待内部错误原文，均已按团队脱敏契约适配，保留 `/tmp/contextdb-integration-system-initial.log` 后从头重跑。

原生私有PG大范围轮在73%以后另发现4个旧断言：metrics仍查找hindsight前缀、公开品牌dotenv测试未解除PYTHON_DOTENV_DISABLED、retain视觉能力错误仍要求内部变量名、XAI OAuth凭据目录仍期待.hindsight而非.contextbase。已按相同团队契约适配；对应两个模块16通过/1条件跳过，视觉模块9通过。该完整轮最终10854通过、4失败、186跳过、5预期失败，无错误（537.37秒）；保留 `/tmp/contextdb-integration-api-private-complete-initial.log` 与同名XML，随后从头验证最终测试快照。

文档钩子在团队基线的图引用处失败：概览页指向不存在的what-contextbase-does.json，真实共享资产仍叫what-hindsight-does.json。该问题已在独立快照复现并由 [Issue #14](https://github.com/RSIXDB/hindsight/issues/14) 跟踪。按用户要求，相关修复已从本分支移除；109个文件恢复团队基线。该问题与管理功能无代码依赖，但文档生成钩子及相关CI检查仍会受影响。13个现有JSON图的渲染通过不能证明MDX引用有效。

原生完整轮保留已有条件跳过和预期失败，未以新增skip/xfail处理失败。主要跳过项为迁移形态矩阵中111项本身无CONCURRENTLY DDL、22项缺少Oracle服务，以及未提供真实provider密钥/benchmark端点等；最终数量以上表完整轮为准。显式marker排除的外部依赖路径另见第5章，不计作通过。

system最终全量的两个跳过分别为本地E5 ONNX模型未提供，以及Coding Agents实际HTTPS安装用的构建tarball未提供。新增60项ContextDB故事全部通过，无失败或跳过；生产UI验收启用强制构建校验，覆盖两种Worker模式。

## 5. 未执行范围

NOT RUN：真实LLM/模型质量评测、外部服务集成、Oracle、目标ECS/RDS、Linux容器镜像构建/漏洞扫描、生产压测、CLI/Rust/Go等未改动独立产品全量。此次“存量回归”指上表实际执行的UI、API非外部依赖和system范围，不声称整个monorepo所有平台与产品矩阵通过。

本机通过只说明列出的配置与行为完成验证；生产发布与专家批准均未执行。本次任务只产生本地分支及提交，不推送或部署。

## 6. 排除无关文档修复后的核验

本分支直接基于固定团队基线，仅保留一个功能提交。移除文档修复后，对照移除前备份逐文件核对：该修复涉及的109个文件均与团队基线一致；除本目录内四份说明文档外，管理功能、原生适配、全部测试、CI及部署文件的内容与已验证版本完全一致。上表功能测试沿用该相同代码的实际结果，本次未重复运行完整测试。

另核对生产UI源码/bundle指纹、差异空白及评审文档链接。此次仅提交历史与说明修订，使用单次命令 `git -c core.hooksPath=/dev/null commit --amend`，避免触发已明确延期处理的文档生成问题；未修改仓库钩子或持久Git配置。完整提交钩子及相关文档CI仍列为Issue #14的已知基线失败。


## 7. 完整设计恢复与当前资料核对

按用户要求，以资料仓 `23fc841dd8cff0d4efce9b3d4f5b3375f27ea24c` 的原始完整设计为底稿，保留各业务/技术章节、两张原图及可编辑源文件，直接在相应章节补齐团队适配和缺口。没有采用资料仓工作树的后续未提交实现说明，没有修改该工作树。撤下本轮自行新增的角色任务及重复拆分文档；所有读者使用同一份DESIGN。

本轮只有资料变化，HEAD仍为 `0e283e923a4de59be68629d43dd5fcbfb84ee248`；运行代码及测试未改，第2章完整功能测试没有重跑。来源版本的独立检视、Node22/24和MaaS/全文小样本验证不作为当前团队分支新通过项。

本机历史JUnit重新核对：UI522；扩展342；system416个testcase含414通过、2跳过，suite tests=427另外包含11个通过subtest；原生API的191个skipped元素含5个xfail，普通skip186、pass10858。原始日志/XML仍位于/tmp，不作为永久远程证据；第三方应获取脱敏工件或在隔离环境复跑。文档核验不等于独立代码批准。

SEC-01已合入DESIGN第5.1.1节，状态OPEN；完整业务Bearer+PG端到端复现仍未执行。本轮仅核对静态响应过滤路径，未修复运行代码，也没有扩大到Issue #14或Issue #3。

本轮资料检查（RUN/PASS）：原始64个主题章节均保留（两项流程标题由“目标”更新为“当前实现”）；2张SVG和2份drawio与固定来源字节一致；45个相对文件/章节链接有效；第5.4节13项管理方法/路径与OpenAPI一致；代码记录中14对显式测试symbol可定位；Markdown围栏/表格结构及git diff --check通过。Mermaid/SVG未做浏览器视觉验收，未重新运行功能测试。工作树差异限定在本目录与扩展文档入口，未修改运行代码、测试、提交历史或资料仓既有未提交改动。


## 8. a05b808最新实现的团队适配与验收

### 8.1 本轮固定输入和范围

2026-10-20在同一集成目录，将来源 `ddf5c360001f1db46f925b1822803ac9bff1119e` → `a05b80885883b36f879abdb2ce8a9c8f63b0922c` 的113文件增量应用到团队集成工作树；不是用来源目录覆盖团队代码。团队基线仍为 `57bbfd2d39685091ce65a4742e43c6efbcb4c78e`，验收执行时集成HEAD为 `0e283e923a4de59be68629d43dd5fcbfb84ee248`，适配位于未提交工作树。本章保留该验收时点；后续按用户要求amend送审，见第9章。

当前完整设计直接吸收资料仓固定快照 `5f9993c2c1d9eb68a83decdb99590f4dfe7d76dd` 中与最新实现有关的说明，并在同一设计内保留团队差异；没有另建按读者角色拆分的设计。PLAN按用户意见移除。

运行范围与第5章限制一致：真实进程/PG/Worker和生产UI，模型使用确定性stub。所有数据库为任务创建的专用实例；没有清理或连接用户当前部署数据库。产物位于本机 `/tmp/contextdb-refresh-a05b80885/`，属于临时复核证据，第三方仍需留存脱敏工件或复跑。下表仅记录本轮实际结果，不能和历史章节相加。

### 8.2 当前结果

| 状态 | 验证范围 | 本轮实际结果 / 工件 |
| --- | --- | --- |
| PASS | UI完整Vitest | 74文件、593通过、无跳过；ui.log / ui.xml |
| PASS | 插件Python完整轮 | 359通过、无跳过，含真实非超级用户部署及21项UI健康探测；extension.log / extension.xml |
| PASS | Python/TypeScript Key响应合同 | 1通过；contracts.log / contracts.xml |
| PASS | ContextDB系统完整轮 | 61通过、无跳过，涵盖两种Worker和生产UI；contextdb-system.log / contextdb-system.xml |
| PASS | 独立生产UI门禁 | 2通过、59未选择，双Worker JUnit门禁通过；production-ui.log / production-ui.xml；这2项已包含在61项中，不重复累加 |
| PASS | 原生系统完整轮 | 354通过、2既有条件跳过、11子测试通过；native-system.log / native-system.xml |
| PASS | 原生dotenv/MCP路由/瞬时提取失败定向回归 | 19通过、1既有条件跳过、11283未选择；native-focused.log / native-focused.xml |
| PASS | 原生API非外部依赖完整重跑 | 10857通过、186条件跳过、5既有预期失败，0失败/错误（376.86秒）；api-final.log / api-final.xml |
| PASS | TypeScript类型检查 | npx tsc --noEmit --project hindsight-control-plane/tsconfig.json；tsc-initial.log |
| PASS | 正式生产UI构建及源码/bundle指纹 | build-ui成功，最终重新核对指纹一致；ui-build.log |
| PASS | 根目录lint | 最后测试夹具修改后再次通过；lint-final.log。工具触及的3个无关embed格式化文件已恢复 |
| PASS | UI未使用文件/依赖检查 | knip退出0，保留3项忽略配置提示；knip.log |
| PASS | 产品品牌同步检查 | brand.log |
| PASS | 管理OpenAPI检查 | 管理契约未变，openapi-final.log |
| KNOWN FAILURE | 完整文档生成/提交钩子 | Issue #14基线问题继续独立跟踪；本轮没有将其修复或标成通过 |
| NOT RUN | 远端GitHub CI、独立专家批准、目标生产环境 | 本机验证不替代远端门禁或发布批准 |

原生系统的2个条件跳过仍为E5 ONNX模型缺失及Coding Agents真实安装tarball未提供。原生系统和ContextDB系统合计415通过、2条件跳过、11子测试通过；跨语言合同与独立UI门禁分别报告，不制造额外系统故事计数。原生API仍显式排除hs_llm_mat、hs_llm_core、integration、slow、oracle；没有将未运行范围称为通过。

### 8.3 可复跑的当前入口

从集成仓库根目录执行。先同步根目录、插件、system及Node依赖；API的可选Oracle驱动按uv.lock安装（本机3.4.2，仅满足单测导入，不访问Oracle服务）。本机已缓存模型时设置HF_HUB_OFFLINE=1；干净环境应先准备模型。

UI实际执行进入工作区使用其Vitest配置，以下为本轮使用的完整测试和类型检查入口：

```sh
(cd hindsight-control-plane && npx vitest run --maxWorkers 4)
npx tsc --noEmit --project hindsight-control-plane/tsconfig.json
PYTHONPATH=hindsight-extensions/contextdb-service hindsight-extensions/contextdb-service/.venv/bin/python -m hindsight_ext_contextdb build-ui --source-root .
.venv/bin/python hindsight-extensions/contextdb-service/scripts/verify_integration.py extension
.venv/bin/python hindsight-extensions/contextdb-service/scripts/verify_integration.py contracts
.venv/bin/python hindsight-extensions/contextdb-service/scripts/verify_integration.py contextdb-system
.venv/bin/python hindsight-extensions/contextdb-service/scripts/verify_integration.py system
HF_HUB_OFFLINE=1 .venv/bin/python hindsight-extensions/contextdb-service/scripts/verify_integration.py api -- --junitxml=/tmp/contextdb-api.xml
```

与旧入口的区别：system现在只执行原生故事；contextdb-system显式执行插件tests/system，启动前要求生产UI存在。extension明确选择tests/python，包含从旧集成迁入的21项test_ui_probe；contracts使用system环境验证跨语言合同。包装器注入插件/system/API的PYTHONPATH，为每轮创建私有PG并清理自身资源；API另按xdist Worker隔离PG。不要把生产连接串直接交给测试。

独立生产UI报告和强制门禁：

```sh
.venv/bin/python hindsight-extensions/contextdb-service/scripts/verify_integration.py contextdb-system -- -k test_ui_workspace_user_key_and_native_permission_flow --junitxml=/tmp/contextdb-production-ui.xml
hindsight-system-tests/.venv/bin/python hindsight-extensions/contextdb-service/scripts/check_production_ui.py /tmp/contextdb-production-ui.xml
```

门禁必须读取实际完整的双Worker UI用例报告，拒绝文件缺失、用例缺失和跳过。CI新建专用job执行合同、正式构建、双Worker UI和always门禁；普通system job不再重复构建UI或使用旧CONTEXTDB_REQUIRE_UI_TESTS变量。本机仅走读CI接线、执行同一门禁，远端CI尚未运行。

### 8.4 失败定位、适配与重测

首轮原生API完整执行实际为10856通过、1失败、186跳过、5预期失败及1个teardown错误（461.93秒），证据保留为api.log / api.xml，不能作为通过结果。

失败一为dotenv启用路径：来源将托管dotenv禁用测试迁入插件，增量合并使原生加载器测试失去旧集成中的显式环境清理；受控验收全局设置PYTHON_DOTENV_DISABLED=1，因此预期加载.env的断言失败。只在该原生测试恢复monkeypatch.delenv，保留原有覆盖优先级断言，没有修改运行时策略。

错误二为MCP路由用例teardown：默认poller领取此前测试故意遗留在同Worker PG中的8个pending任务，与memory fixture关闭竞争；该路由用例本身已通过。仅在MCP路由模块用局部autouse fixture关闭两套前缀的后台poller，仍使用同步memory处理请求；专门Worker测试及61项真实系统故事不受影响。没有修改生产Worker关闭逻辑，也没有把此隔离改动称为解决通用后台退出问题。

两项适配后定向19通过、1既有跳过，再从头执行原生API完整重跑，最终10857通过、186条件跳过、5既有预期失败，0失败/错误。相对此前0e283e923轮少1个原生通过项，是托管dotenv用例按来源迁入插件，并非删除覆盖；本轮插件计数包含迁入测试。中间一次错误选择参数触发的广泛收集被主动停止，仅清理该次自有资源；dotenv.log不作为验收证据。未用新增skip/xfail或自动重试掩盖这两项问题。

插件第一次338项通过后发现旧集成独有test_ui_probe未随来源增量移动，默认tests/python收集遗漏21项；已迁移并修正路径，最终359项全部通过。产品productFetch测试同样迁入插件tests/ui；最终UI593项全部通过。旧目录删除对应新目录迁移，不代表删减测试范围。

### 8.5 最终差异与开放项

核对最新来源：共享数据库检查、授权/Repository/validator/migrations/入口及7个新UI组件共13个关键实现文件与a05b808逐字节一致；其余文件保留必要团队产品、会话和部署适配。原生hindsight-api-slim/hindsight_api相对团队基线零差异；管理schema.sql与OpenAPI没有契约变化。四处合并冲突及T18～T21测试追踪见CODE-REVIEW第10章。

完整原设计章节保留；当前架构图仅将过时标签“管理操作、准入与审计”修正为“管理成功变更审计”，同步SVG及drawio，不声称沿用第7章历史时点的字节一致性。资料链接/章节、测试symbol、图XML和空白检查另作静态核验，不替代图的浏览器视觉验收。本轮最终复核13个关键实现字节一致、18个相对文件链接有效、Markdown表格/围栏及4份图XML有效；工作树暂存区为空，原目录仅保留既有verification/未跟踪目录。

SEC-01仍为OPEN：静态路径和离线响应组装探针显示原生Bank配置config/overrides字段过滤不一致；业务Key的配置可见范围还需确认产品策略，不能仅凭现有空字段规则定性为敏感信息泄漏；没有新增完整业务Bearer+PG端到端复现，没有在本轮修复，不声称所有运行配置对客户不可见。删除仍要求先停止访问并确认实际已接受执行结束；超时、取消或空任务列表不是执行停止证明。Issue #14和原生敏感日志Issue #3继续独立跟踪。本轮不扩大为原生运行时整改或生产发布。


## 9. amend送审的提交前检查（2026-10-20）

用户明确要求将当前代码和完整资料amend为一个提交，推送 `RSIXDB/hindsight` 并创建PR检视。目标为 `feature/contextdb-management` → `main`；检查时远端main仍为57bbfd2d39685091ce65a4742e43c6efbcb4c78e，目标功能分支尚不存在，没有覆盖他人远端分支的需要。提交后以PR当前head及GitHub实际检查状态为准，不将“创建PR”写成“已批准/已合入”。

本轮提交整理只刷新文档和提交说明；运行代码及测试文件与第8章最终通过快照逐文件SHA-256核对一致，没有再修改行为。因此不重复完整重跑万余项API测试，直接复核实际JUnit和构建指纹，并按项目规定再次执行lint和送审自检。

| 状态 | 检查 | 实际结果 |
| --- | --- | --- |
| RUN / PASS | 最终根目录lint | /tmp/contextdb-pr-final-lint.log：All lints passed；3个无关embed格式化改动与执行前/HEAD逐字节核对后恢复，不纳入提交 |
| RUN / REVIEWED | check-unused.sh | /tmp/contextdb-pr-unused.log：审阅vulture/knip建议，不把脚本退出0当作“无任何提示”；未新增需阻止本次送审的项；阻断式knip已见第8章通过记录 |
| RUN / PASS | 第8章实际JUnit复核 | UI593、插件359、合同1、ContextDB系统61、原生系统354及API10857通过，0失败/错误；原生系统2skip、API186skip和5xfail保留；独立生产UI2项不重复计数 |
| RUN / PASS | 生产UI源码/bundle校验 | 使用实际verify_ui_build重新校验同版正式构建，指纹有效 |
| RUN / PASS | 分支与代码范围 | 团队基线上单一功能提交；原生运行目录零差异；最新来源13个关键实现一致；日志、环境、依赖和构建产物不入提交 |
| RUN / PASS | 完整资料核对 | 64个原始主题章节保留，同一份DESIGN和CODE-REVIEW；37个相对链接/锚点有效，表格/围栏及4份图XML/差异空白检查通过；PLAN.md删除 |
| REVIEWED / KNOWN FAILURE | 标准文档生成钩子 | Issue #14仍OPEN，当前两处无效Figure引用及缺失资产未变；此前在固定团队基线独立复现。本轮不在提交目录执行会清理/重建文档的失败生成器 |
| NOT RUN | 远端CI、独立专家批准、目标环境验收 | 本机检查不替代；创建PR后由远端和审阅者核对 |

由于Issue #14已由用户明确要求独立跟踪，amend使用单次 `git -c core.hooksPath=/dev/null commit --amend --file <提交说明文件>`，独立执行lint和自检；不修改持久Git配置，不恢复无关文档补丁。完整文档生成及相关CI仍是已知失败，不能把该单次提交例外表述成标准全钩子通过。

提交说明保留原集成提交的详细功能/部署/认证/边界描述，刷新Source-Commit为a05b808、保留上一来源ddf5c360，并补齐共享检查、MCP目录投影、UI响应与状态归属、测试归组、CI门禁、本轮实际结果、完整文档和开放项。文档正文不包含自身amend哈希，避免为更新自引用反复改写提交。

SEC-01表述同步为配置响应字段过滤不一致，详见DESIGN第5.1.1节：当前空字段限制来自插件实现；产品是否应允许业务Key查看本空间部分配置尚待确认，不能直接定性为任意敏感信息泄漏。保持OPEN，未新增修复、跳过或未经证明的安全保证。资料仓原始设计/检视已有其他未提交修改，本轮不覆盖；统一在本PR完整设计与检视记录内补齐团队分支说明。


## 10. SEC-01插件内过滤修复（2026-10-20）

### 10.1 范围与修复边界

按用户要求，先在原代码仓a05b80885工作树完成并验证，再同步到团队bc38b0624工作树。原生MemoryEngine修改及4项新增原生测试已全部撤回；本轮仅涉及插件transport.py、插件test_transport.py、已有test_114系统故事及同版资料。此前原生方案的96项结果不作为当前插件实现验收。原生运行目录相对各自基线零差异；不覆盖其他用户工作，不修改资料仓已有未提交修改。

保持字段权限：配置GET仍为200，当前业务Key的config/overrides均为空；不新增403策略。插件只对原生配置GET/PATCH/DELETE成功JSON做字段投影，复用宿主公开响应模型和已过滤config键；不重放权限钩子、不新增SQL、不写回存储。与原有任务诊断共享定点ASGI缓冲；分块、编码、长度、错误状态及无关路径均有回归。

### 10.2 实际命令与结果

工件位于本机 `/tmp/contextdb-sec01-plugin-6moaycnb/`。原始未修复的真实探针另见 `/tmp/contextdb-sec01-live-sv1kzm5y/`，原生实现尝试仅作为诊断历史，不属于最终代码。临时PG和API/Worker均由测试自己创建及清理，不访问当前部署库。

| 状态 | 范围 | 实际结果 / 工件 |
| --- | --- | --- |
| PASS | 原仓插件transport与diagnostics针对回归 | 52通过，无跳过；source-plugin-target.log/xml |
| PASS | 原仓插件Python完整轮 | 350通过，无跳过；source-python-full.log/xml |
| PASS | 原仓ContextDB系统完整轮 | 63通过，无跳过，含原生默认兼容及双Worker生产UI；source-system-full.log/xml |
| PASS | 原仓根lint | /tmp/contextdb-sec01-plugin-source-lint.log，All lints passed |
| PASS | 集成插件Python完整轮 | 375通过，无跳过；integration-python-full.log/xml |
| PASS | 集成ContextDB系统完整轮 | 63通过，无跳过，含原生默认兼容及双Worker生产UI；integration-system-full.log/xml |
| PASS | 集成根lint | /tmp/contextdb-sec01-plugin-integration-lint.log，All lints passed；3个无关embed格式化文件已恢复HEAD |

本轮外部受控包装器run_acceptance.py复用仓库verify_integration的PG所有权逻辑，显式指向原仓源码根；锁定Python工具环境来自本机已有集成环境，原仓插件/API/system通过PYTHONPATH和测试工作目录选定，不用集成运行代码冒充原仓结果。原仓完整轮结束后才同步实现并执行集成完整轮；两个完整系统轮不并行，避免默认原生兼容夹具的确定性PG实例名冲突。插件Python与系统各自使用独立PG，可并行执行。

集成可复跑命令：

```sh
.venv/bin/python hindsight-extensions/contextdb-service/scripts/verify_integration.py extension
.venv/bin/python hindsight-extensions/contextdb-service/scripts/verify_integration.py contextdb-system
./scripts/hooks/lint.sh
```

新增16项插件测试：4项字段可见性（包括默认值不冒充override）、4项GET/PATCH/DELETE与分块/gzip协商、4项非法成功响应、3项原生错误保留、1项无关路径不误过滤。认证查询计数保持一次。已有诊断投影一起运行，确认复用缓冲逻辑不改变其安全行为。新增1个系统故事按两种Worker运行，已包含在63项中，不重复累加；使用真实管理签Key、发布SDK/MCP，无伪造内核/数据库响应。

### 10.3 最终自检与提交说明

检查两仓插件实现和测试文件一致、原生运行差异为空、改动限定在自研目录及同版管理资料、无临时日志/环境/构建产物进入Git。所有读者仍使用同一份完整DESIGN和CODE-REVIEW；PLAN.md保持删除。

团队提交说明以最终功能、权限、UI/部署和实际验证为主，删除迁移/冲突过程、历史patch及重复来源字段。原始实现来源集中记录仓库URL、分支contextdb/v1.0.0及基准提交a05b80885883b36f879abdb2ce8a9c8f63b0922c；该公开提交是功能来源基准，不冒称包含本轮尚未提交的插件修复。正文按约72～80英文字符换行，不拆URL或完整标识。

Issue #14是团队基线文档生成问题，与本特性无关，PR单列“基线检查说明”。按既有用户范围决定不恢复该无关修复；完整文档钩子仍不标通过。根lint和代码自检独立执行，amend仅单次禁用已知失败钩子，不改变持久Git配置。独立专家批准、目标ECS/RDS、真实模型质量及全平台CI不由本机结果替代。


本轮最终结果：原仓350项插件Python、63项完整ContextDB系统，集成375项插件Python、63项完整ContextDB系统，全部无失败/错误/跳过；原仓52项针对回归包含在350项内，不重复累加。两份系统JUnit均包含新增双Worker配置故事、双Worker生产UI及普通原生默认兼容。两仓根lint通过，原生运行目录及本轮原生测试差异均为空；插件实现与修改的两份插件测试逐字节一致。源仓保留本地未提交修复；团队分支将相同实现amend送审，来源a05在提交说明中标明为修复前公开功能基准。
