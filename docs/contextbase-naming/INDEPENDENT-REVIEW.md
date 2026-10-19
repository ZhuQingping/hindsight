# 独立审查记录

审查者：`/root/independent_naming_review`（独立只读审查 agent，非实施 agent）。实施仍由单持久 session 完成。本文件由实施者保存收到的独立结论及修复追踪；最终证据审查尚未通过。

初审/复查均为源码只读检查，未运行重型任务，也未用历史 PASS 代替新验收。

| Finding | 独立发现 | 处理与当前证据 |
|---|---|---|
| R1 | CLI configure 和打包 skill/prose 展示入口遗漏 | CLI generated DISPLAY_NAME；明确 prose 模板及既有 downstream skill/docs生成；源码复查已确认，最终制品待审 |
| R2 | 新归因提示使旧 usage regex 漏记 | 生成当前/历史 CREDIT_DISPLAY_NAMES；保留旧 transcript测试并增加双名称原文不变回归；unit04 Coding Agents1368PASS |
| R3 | legacy UI请求v1无法发现API-only display override | v1新增非秘密 X-Product-Display-Name 响应头，新UI检查；旧body及SDK签名不变；前端反例已过，原生组合待运行 |
| R4 | 单字符品牌产生NaN ANSI颜色 | 长度1时t=0；A/ContextBase/Atlas Grove实际brandWord测试通过 |
| R5 | generator将undefined/null/boolean slug转字符串通过regex，history类型未约束 | 严格类型/键集/trim/成员校验；非法输入在写输出前失败；round-trip反例已过 |
| R6 | prose模板误将历史AMB测试主体变成品牌变量 | 恢复基点的agentstratum主体；模板当前产品介绍才参数化，复查已确认 |
| R7 | sync脚本--root只传首级生成器，可能污染原工作区 | 包装脚本只接受无参数/--check；完整演练在fixture中调用fixture内脚本 |
| R8 | prettier新依赖导致CI品牌检查在npm ci前失败 | 检查移至npm ci后；release插件job也安装根依赖；锁已更新 |
| R10 | 单独修改manifest身份后重新生成ledger可被接受 | 生成前验证真实四类客户端身份/MCP注册键/marketplace/Cargo bin；反例要求普通生成和check失败且所有输出/ledger不写入；执行和复查待完成 |
| R9 | API实际测试发现display改名切分telemetry服务名 | 未修改旧worker断言；固定默认service identity，显式旧slug保持原行为；独立源码复查确认符合N02/N06，追加默认分支双名测试，执行待完成 |

最新独立源码复查结论：未发现新的未关闭 Must fix。该结论不代表 N12 完成；需最终冻结源码、N05实际build/runtime、N06/N09原生证据、打包安装与同源hash绑定后进行独立终审。
