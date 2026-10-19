# 实际二次改名演练

本次完整链结果为 PASS（构建与消费者/恢复分段证据），输入源码 `c394b303cce8a5a0fe8013293882c340fb4daf5e`。此前失败未改写为PASS。

手工输入只修改 `brand/definition.json` 的 display_name（ContextBase → Atlas Grove）与 deployment_slug（contextbase → atlas-grove）。兼容身份、历史名称、业务源码不手改；手工生产组件、manifest、安装脚本改动清单为 **空**。

| 阶段 | 实际证据（runs/contextbase-naming-20261019/ 下） |
|---|---|
| 两份品牌输入 | drill-03-resume-b/ContextBase.json、Atlas-Grove.json |
| 显式生成及完整检查 | drill-03/generate.log、check.log |
| 从fixture原生API重生成OpenAPI/Python/TS/Go | drill-03/sdk-atlas/；日志、源/adapter/JAR/spec hashes齐全 |
| 432旧声明及Go消费者 | drill-03/sdk-compatibility.log、go-sdk.log |
| 实际Python API v1/v2及固定header | drill-03/api-consumer.log |
| Rust CLI build及Atlas Grove help | drill-03/cli-build.log、cli-help.log；另在private HOME复核 |
| Coding Agents ESM/DTS/type及三插件包 | drill-03/coding-build.log、coding-types.log、package.log、candidates/ |
| Production UI真实构建 | drill-03/ui-production-build.log（exit0） |
| 实际UI默认页面与两个stdio客户端initialize | drill-03-resume-b/ui-login.html、mcp-artifact-consumers.log（均Atlas Grove） |
| 恢复ContextBase并再生SDK | drill-03-resume-b/restore.log、restore-check.log、sdk-restore/ |
| 完整源hash绑定 | drill-03-resume-b/source-binding.json；原workspace与恢复fixture各5132文件零漂移 |

流程复用仓库 `sync-product-brand.sh`、现有OpenAPI/SDK生成脚本、普通包构建与production构建。唯一runner提供执行边界；Java适配器只替代Docker生成器的载体，保留7.10.0 JAR hash及仓库后处理，不复制其他分支SDK。

构建依赖复制到fixture内，Rust target独立；目录与日志均在主仓runs下。没有改变Next filesystem root、编译配置或业务断言以适应fixture。

保留失败：drill-01缺workspace tsup依赖；drill-02的跨fixture依赖symlink被Turbopack正确拒绝；drill-03构建已成功但HTTP探针未跟随locale跳转；首次resume的MCP探针遗漏必需宿主标识。修正均限fixture/harness；最后的resume-b完成真实消费者和恢复。原FAILED结果、panic/traceback和原始日志仍在。

本项证明品牌输入→生成→真实构建/消费者→恢复的可重复流程。第三方真实宿主会话、其他平台二进制、公开发行不属于该证明。
