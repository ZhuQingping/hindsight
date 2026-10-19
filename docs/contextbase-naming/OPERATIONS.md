# 复核与后续改名流程

工作区：主仓`.local/product-brand-ui/contextbase-naming-worktree`；分支`product/contextbase-naming-20261019`；产品源码检查点c394b303c。日志、工具版本与实际import来源、原生PG数据、失败fixture、工件统一位于主仓`.local/product-brand-ui/runs/contextbase-naming-20261019`。

所有重型动作继续使用 `/home/cimon/code/hindsight/.local/hosted-single-tenant/development/runs/m2-access-ui-delivery/run-bounded.py` 和同目录resource-heavy.lock。先核对锁归属、实际cwd和输入源；不复制新锁，不抢停。指定`--cwd`为新工作区、`--log`为未占用的新run文件。原预览已按本轮明确授权正常停止，数据保留。

## 下一次产品改名

1. 编辑brand/definition.json的展示名/部署slug，并在historical_display_names保留旧归因名称。固定发行/协议映射本轮没有迁移；改动identity需另立明确兼容合同。
2. 执行`bash scripts/sync-product-brand.sh`，然后同脚本`--check`。它覆盖语言适配、manifest展示、安装脚本、客户端prose和既有skill/docs生成链；身份漂移在首次写入前失败。
3. 在**无部署命名覆盖**的生成环境中，从当前API生成OpenAPI，再运行现有SDK生成流程。例如清除进程中的contextdb_name/product_display_name后运行`uv run --project hindsight-dev generate-openapi`，再运行`scripts/generate-clients.sh`。不要让开发机部署覆盖把接口元数据生成成另一名称。
4. 运行相关lint/type/unit、blocking knip（files/dependencies/unlisted）、客户端与production UI构建、归档/校验和与实际安装、原生API/MCP/浏览器回归。测试数据可指定演练品牌；不人工编辑生产组件、manifest或安装脚本。
5. 复核生成固定点与恢复hash，独立审查后提交。公开发行与主干合并另行决定。

本轮API/SDK生成执行的是当前仓库原生生成器及其后处理；本地adapter用已核验7.10.0 Java JAR替代Docker载体，并将Rust/Go编译单列到同一共享runner。frozen脚本、适配差异及hash位于api-generation-01/02与drill-03/sdk-atlas、drill-03-resume-b/sdk-restore。没有复制旧SDK或改权限模型。

`scripts/generate-openapi.sh` 还会构建整个原有公共文档站；该完整站点build不属于本轮产品候选证明。本轮验证其原生spec生成入口及coding-agents文档同步链；完整站点保持NOT_RUN。

## 本轮证据入口

- source-checkpoint.json：5132源文件及总hash；SOURCE-MAP.json给出手改/生成/模板/测试分类。
- unit-04、unit-05：最新有效各套unit/type/build；前序失败保留。
- lint-03、final-01：lint后立即品牌固定点、破坏性身份反例、CI一致knip、重复SDK生成、新包安装、冻结源UI构建。
- drill-03 + drill-03-resume-b：完整二次改名的构建、实际消费者及恢复；不是只测格式函数。
- release-01、four-client-candidates：真实Linux优化二进制、许可证、四类候选及校验和。
- runtime-03：23组原生场景、7 SDK故事、CLI live25、真实release HTTPS安装/重装、825文件UI制品hash及全部cleanup。

每轮目录的harness.py是冻结证据副本。复跑应核对当前根目录入口脚本的R/W/venv/工具链/候选路径，再使用新输出目录；不要直接在嵌套run目录执行一个依赖`__file__.parent`的证据副本而测错工作区。Chrome需要短Unix socket路径：本轮只给Chrome子进程建立私有/tmp挂载，底层文件仍在runtime-03/chrome-tmp。

所有测试资源均为本轮拥有的fixture；实际第三方宿主安装会话和云资源保持NOT_RUN。结束时API/UI/Chrome退出，PG停止；数据、配置、容器和失败日志保留。只有用户明确授权才启动长驻体验服务。
