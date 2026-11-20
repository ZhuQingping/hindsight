# Rebase、提交与验证记录

日期：2026-11-20。用户明确授权整合并提交当前设计和实现；并行研发保持暂停。本次没有推送。

## 1. 分支与提交边界

- 开发分支：`codex/beam1m-recall-perf-20261120`，工作区 `.worktrees/beam1m-recall-perf-20261120`。
- 整合目标：新获取的 `zhuqingping/memory-benchmark`，提交 `18be05bde`。
- 第一版：原 `05d2894c5` 保留在原保护分支/干净工作区；在当前分支重放为 `b682cd693`。
- 本轮特性：BEAM 兼容、P3 库内函数优化、对应测试、设计与历史证据合为一个特性提交；完整提交说明保存在 [commit-message.txt](commit-message.txt)，最终提交号以本分支 `git log -1` 为准。
- 保留 rebase 前备份分支 `codex/beam1m-before-rebase-20261120`。
- 主工作区 `memory-benchmark` 的其他未提交文件没有覆盖、暂存或提交。PG 主干仓没有本轮改动和提交。

## 2. 集成验证结果

| 检查 | 结果 |
| --- | --- |
| Rebase | 首版和本轮共两项提交，均无冲突 |
| 下推单元测试 | 33 通过 |
| Recall Profile 测试 | 32 通过；私有 full1540 历史重放 1 项因未提供路径跳过 |
| 默认请求，关闭/开启下推 | 同一冻结 BEAM 上新增 40 次真实 loopback HTTP 请求，20 题响应一致 |
| 与历史原始源码比较 | 20 题响应哈希一致，模型输入哈希一致，每题 300 对 |
| 候选调用与补查 | 开启组 20/20 命中下推，每题候选入口 1 次，模型后候选补查 0 次 |
| 冻结数据 | 七张记忆表行数与哈希不变 |
| 夜间测量的选定源码 | 选定文件哈希与测量时一致 |
| 要求的全仓 lint | 已运行；仅原有 `http.py:5886` F841 阻塞。其余检查通过，formatter 的无关文件变动已排除 |

混合收集 API 与 benchmark 两套测试时曾遇到 pytest fixture 作用域错误；分别按各自测试入口执行后通过。失败日志没有删除。原有 F841 在夜间基线位于第 5846 行；本次没有修改该无关逻辑。

安全结果与源码哈希见 [rebase-validation.json](evidence/rebase-validation.json)。私有原始响应及完整日志未提交。

## 3. 性能与运行范围

本次仅做集成/等价验证，使用固定查询向量和 RRF passthrough；捕获并核对实际准备的模型输入。没有重跑 120 次真实 BGE，也没有新增性能统计。因此报告中的 52.29/51.94 ms 及约 56 秒仍是夜间原型的历史测量，不能标作本次整合后的新结果。

新增的 `recall_profile=locomo` 属于另一项 opt-in 功能，可能额外读取文档日期；未纳入本轮一次候选调用契约。已验证的为默认 Profile，不能泛化到所有 Profile。

未重启 LoCoMo 或常驻实验 API，未重新部署服务。临时验证进程只读取独立 BEAM PG；本次提交不代表现有常驻进程已经加载新代码。多路并行、图任务并发恢复和动态剪枝依旧没有实现。

证据字段说明：`evidence/source-manifest.json` 的 `uncommitted: true` 描述夜间测量快照当时的状态；当前提交状态以 Git 为准，整合后源码哈希在 `evidence/rebase-validation.json`。历史性能和哈希未被覆盖。
