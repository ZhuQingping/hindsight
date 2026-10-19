# ContextBase 命名解耦交付结果

状态：`LOCAL_ACCEPTANCE_PASS / INDEPENDENT_REVIEW_CLOSED / DRAFT_PR_PENDING`。2026-10-19。代码实现、本地验收及独立源码/证据终审已完成，draft PR交付待完成；未合并main，未公开发行。

源码检查点 `c394b303cce8a5a0fe8013293882c340fb4daf5e`，5132文件hash `cff739b077e5037278ed5d94ff18c2f55e5476af339c9fc6207a2d937acbaea4`。从clean交接提交960983bb4建立独立分支，530a63064整合交付与5d350568源码均为祖先；双方成果完整继承，其他工作区未提交内容未修改。

默认产品展示为 **ContextBase**，部署slug默认contextbase。`brand/definition.json` 是品牌输入；Python/TypeScript/Rust适配、manifest展示字段、客户端文字和安装脚本从确定流程生成。旧v1合同保留，新增 `/product-config/v2`；部署展示配置与固定发行/协议身份分离。CLI、包、目录、环境变量和MCP注册继续采用明确的agentstratum兼容身份，详见[NAMING-MAP](NAMING-MAP.md)和[兼容说明](COMPATIBILITY.md)。

[二次改名演练](SECOND-RENAME-DRILL.md)实际将唯一品牌输入改为Atlas Grove/atlas-grove，完成原生API、SDK、CLI、Coding Agents、插件与production UI构建，真实页面和stdio客户端显示新名，再恢复ContextBase。手工生产组件/manifest/安装脚本修改清单为空；恢复fixture与原工作区各5132文件零漂移。该项已获独立审查确认。

## 本轮实际验证

| 检查 | 结果 |
|---|---|
| Frontend unit/type | 390 PASS，type PASS |
| Coding Agents unit/type/build | 1368 PASS / 6条件SKIP，type/build PASS |
| API scoped | 390 PASS / 1既有SKIP / 1真实LLM标记排除；本地ML相关用例本轮实际执行 |
| Claude Code | 226 PASS |
| Rust SDK/CLI | SDK编译与schema回归PASS；CLI普通153 PASS，25 live项在原生fixture另行全部PASS |
| SDK | 432旧声明guard、6 pytest检查、Go3消费者；当前源码重复生成0漂移 |
| 必需lint / blocking knip | PASS；knip含CI的files/dependencies/unlisted；advisory结果保留 |
| Production UI / Linux release | PASS；默认release profile、当前许可证、9项release进程测试PASS |
| 新包HTTPS安装 | 实际tarball8项/11subtests PASS；实际Linux ELF另经HTTPS安装/重装，字节hash相同并连接原生API |
| 独立原生API/MCP/浏览器/客户端 | 23组PASS，7个SDK黑盒故事PASS；均为本次源及制品 |

原生故事保留原有布局与会话、旧页签、真实下载/ZIP CRC/导入、61项分页搜索/返回、locale/query/hash、移动布局、错误诊断、远程连接和MCP ownership。旧页签实际Download返回409，新增下游文件请求/保存/重放均为0；不同展示名保持相同UI制品、固定CLI身份、endpoint凭证与数据。新增legacy UI模式也识别API-only展示覆盖并失败关闭。

UI编译制品825文件hash：`f7d19de328532e9318b176c6b63b15c7965d5fd0a02b548dec3494a63e9276b5`。实际Linux release CLI hash：`7b4e533e483646ad6f47a2969cb1a917a401a2ddca30538dd80721ca288bcbb6`。四类候选共12个记录文件，ZIP CRC、gzip/tar、许可证和SHA256SUMS核验通过；manifest位于主仓runs/contextbase-naming-20261019/four-client-candidates/MANIFEST.json。

## N01–N12 与证据

N01–N11本地限定范围通过；N12独立源码/证据终审通过，交付提交/PR状态待补核。逐项结果及原始日志路径见[VALIDATION.json](VALIDATION.json)，来源见[SOURCE-MAP.json](SOURCE-MAP.json)。独立发现、修复与证据审查见[INDEPENDENT-REVIEW.md](INDEPENDENT-REVIEW.md)。

源码检查点的547个变更文件中：473生成物、33适配/工作流手改、8初始文字模板、4品牌权威/清单、19测试、9交付文档、1锁文件。业务引擎、原生auth/migrations、会话认证、CLI连接/nullable PATCH、安装器ownership主体无功能diff。下一次改名只改品牌JSON（保留历史名称）并运行明确生成/构建/验收步骤，不逐页或逐插件修改业务代码。

截至工件汇总，24个串行重型执行累计2066秒（含12个失败尝试）。这不是人日估计；读写/审查可与重型执行重叠。纯锁等待未单独计时，记NOT_MEASURED；未运行与排队均未计PASS。

## 边界与保留记录

所有重型任务使用交接指定唯一runner/resource-heavy.lock，3GiB父限额、256pids、CPU affinity0–1；1.5核quota未在内核落实，实际CPU上界2核。owned PG独立512MiB/96pids。原预览按用户授权STOP正常停止；本轮API/UI/浏览器/PG全部清理，数据和失败记录保留在主仓runs。

失败包括旧展示断言、telemetry身份耦合、额外lint配置/格式问题及fixture依赖/HTTP跳转/MCP配置/Chrome socket路径等，均保留原FAIL记录和修复路径；详见PROGRESS与VALIDATION。没有把旧整合PASS或失败尝试转写为本轮通过。

其他平台真实二进制、真实第三方宿主会话/Claude冷依赖安装、真实模型质量、公共文档站全量build、远端CI完成、云发行与人工产品验收均未声称通过。多用户、多Key管理、Workspace schema隔离仍排除。
