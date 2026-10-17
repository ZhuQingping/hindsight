# 代码审查

审查方式：同一持久实施 session 按仓库 `.claude/skills/code-review/SKILL.md` 自查；没有派生子代理，也不宣称外部独立审查。当前结论为静态审查完成、运行门槛受阻，详见末尾结论。

## 已发现并修复

- 草稿误删当前基线的原生 Gemini 模型配置。恢复类型、状态、保存、编辑器和两种维护语言的文案；保留新的分节导航并加入 Models 锚点。这些不是权限方案代码。
- 产品配置模块头注释仍提 hosted management。已改成原生 API/MCP 职责。
- 控制台 npm lint 仍调用 Next 16 已无的 next lint。改为现有 ESLint 配置入口；全仓 lint 另保留必需检查。
- 系统测试默认会启动固定共享 pg0。启动器新增可选 database_url，品牌测试可通过 HINDSIGHT_BRAND_TEST_DATABASE_URL 指定本任务 PG；不调用共享库清扫 fixture。
- lint 新增通用 LINT_SERIAL=1；保留默认并发模式，不加入访问管理专用检查。

## 静态审查要点

- API diff 仅服务命名、metrics/tracing 默认名称与非秘密 GET /product-config；MCP diff 仅 serverInfo 名称。engine、worker、alembic、授权扩展及 integrations 必须保持基线。
- ProductRuntime 位于 Theme/Features/Bank provider 外侧；实际页面翻译 provider 包围页面，BankProvider 不调用翻译 hook。登录页不列工作空间。品牌不写入资源、session 的 origin/basePath 绑定或 MCP 工具协议。
- proxy 使用 Next 16 的单一 proxy.ts、全动态 matcher。点号 bank ID 不作为静态资源豁免；受保护请求先验会话再校验品牌，写请求要求配置的 Host/Origin。退出与诊断不受数据服务品牌故障阻断。
- 原生文件下载只接受规范的 API 相对路径；对象存储返回绝对地址时使用 storage_key；不向外部 URL 发送服务凭证。归档响应保持 stream 与取消 signal。
- 旧页面 productFetch 从 HTML 读取原品牌并用于 JSON、multipart 与文件 fetch；不从可跨页签变化的 Cookie 取品牌。guard 错配时在业务处理前返回，不重发请求。
- 恢复的 Gemini UI 与原生敏感数据策略保留；删除的 memory-defense 项仅为原厂 Cloud 营销面板。Hook 未有可提取品牌补丁。

## 待完成

已完成 SDK 生成、unit/type/lint/build 与差异纯度检查；待完成原生 API/MCP/browser 全故事、vulture/knip 和结果闭合。

## 当前审查结论（2026-10-17）

`STATIC_REVIEW_COMPLETE / RUNTIME_GATES_BLOCKED / DRAFT_ONLY`。

- 已对实现提交 cbd42fcae、548 路径来源清单、全部手写新文件与变更、API/MCP 最小 diff、生成物结构及维护包装器进行了审查。分支基于当次实时复核的 origin/main；没有其他开发线提交或受保护后端改动。
- 已执行全仓 lint（ruff/ty/ESLint/Prettier）、前端 347 项、Python 品牌 11 项、tsc、TS SDK build 与 production build。首轮发现的语言目录问题已修复复测。未发现尚未处理的确定性 Must fix 源码缺陷。
- 独立原生启动、SDK 样例、登录、特殊 ID 接入页和三种 locale 页面已有实证；不能替代尚缺的双品牌/MCP/下载/旧页签/退出全故事。上述为**未闭合验收门槛**，不是 PASS。
- vulture/knip 尚未运行：共享锁由另一会话 READY 体验服务长期持有。人工引用检查和已通过 lint 不替代该步骤。不得将本记录描述成“全部审查通过”或“可合并”。
- 生成器原样输出的三个新增 Python/Go 文件有 EOF 空行；仅此类 whitespace 检查采用 core.whitespace=-blank-at-eof，保留规范生成物以避免 CI 重生成漂移。不是对生成源的手工修补。
- 未引入 SQL、新列表分页问题、并发原语、HTTP 中间件、模型提示词或包装器参数变更；因此没有借本分支扩张引擎、授权、数据库或模型质量范围。

允许推送供审查的 draft；保持 draft，恢复 RESULT.md 中的运行入口、修复实际失败并补交证据后，再由用户决定是否合并。

交付状态：已推送并创建 [Draft PR #5](https://github.com/RSIXDB/hindsight/pull/5)，未改为 ready，未合并。
