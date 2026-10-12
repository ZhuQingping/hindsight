# 开发计划独立审查记录

2026-10-12。对象仅为单租托管开发计划、协作规则、模板及初始状态；没有产品实现diff，不构成产品代码review或运行验收。

## 候选与审查者

- planning-v1：`c4300058d60eee8cb894a31b982df22094a3dc04`，清单 [candidate-v1.json](candidate-v1.json)。结论 CHANGES_REQUESTED。
- planning-v2：`73f8b7328`，清单 [candidate-v2.json](candidate-v2.json)。中间修订，不宣称独立通过。
- planning-v3：`5d5d8a3078fd361e34d1e1d4c6a40aa68af4fa2d`，清单 [candidate-v3.json](candidate-v3.json)。两名独立审查者均 PASS_PLAN_ONLY，剩余 must-fix=0。
- 文件作者：主控 `/root`。只读审查者：`/root/quality_review_plan`、`/root/continuity_design`；他们没有编辑候选文件。`/root/delivery_breakdown` 提供工作包与并发建议，不计为最终独立通过票。

上述agent通过本会话实际spawn/followup执行并返回结果；它们的角色是规划/静态审查，不是已启动的产品开发attempt。正式产品派发将执行新工作流的DISPATCHING/ACK/ACTIVE协议。

## 发现与处置

| 发现 | 级别 | 已完成修订 |
| --- | --- | --- |
| D00/D01使用后继产品才能通过的运行case，形成隐含验收循环 | Must fix | 新增P00/P01开发前置case，保留B/A/K真实运行case给后继实现 |
| spawn后才登记，可能出现未登记写入者 | Must fix | 先持久DISPATCHING与资源，spawn后补ID；ACK前只读，ACTIVE落盘后明确许可 |
| D09可先开发页面，但真实验收依赖没有结构化表示 | Must fix | 启动依赖D04、验收依赖D05/D08；fixture不能令任务VERIFIED/DONE |
| C02发布前检查要求已经执行V19邀请公测 | Must fix | C02仅V01—V18及发布准备；V19单列release_gate、绑定用户发布决定及执行证据 |
| 初始台账纳入manifest，录入结果后hash变化可能自引用 | Should fix | 候选固定在不可变Git提交；审查receipt另存，实时台账更新不回写历史候选 |
| 恢复标记、主控自执行身份未明确 | Should fix | INTERRUPTED/reconciliation_required、QUARANTINED及CONTROLLER attempt明确 |
| 外部依赖只有任务级映射，HTTPS遗漏C01 | Should fix | case级依赖映射，identity-gateway包含C01的C-V13 |

两名审查者最终均核验：11个manifest文件hash匹配固定提交；17任务的启动+验收图无环且无悬空引用；初始唯一READY为D00；上述修订成立；产品attempt=0、所有产品质量轴NOT_RUN，没有虚报完成。

主控额外静态检查见 [validation-v3.json](validation-v3.json)：案例注册、图、前置/发布门、78个相对链接及Markdown空白/围栏检查通过。后续本审查文件/台账/接续页的审计更新可另有链接数量，不回写该固定候选的检查数。

## 证据边界与历史重建

候选清单中的review_status=PENDING是封版当时状态；最终结论以本记录为准，不修改旧清单。START-HERE及实时台账在审查后更新是审计状态更新；工作流、开发计划和模板内容仍对应已审候选。可通过 `git show <候选提交>:<清单中的路径>` 重建历史文件并校验SHA256，不要求当前台账永远保持初始hash。

实际产品测试、开发agent失联/恢复演练、产品管控agent故障恢复、浏览器验收和真实云验收均 **NOT_RUN**。本次不运行会安装依赖/修改代码的全仓lint；交付是Markdown/JSON，执行了对应静态验证。应用实现阶段仍必须遵守仓库lint、测试和code-review要求。
