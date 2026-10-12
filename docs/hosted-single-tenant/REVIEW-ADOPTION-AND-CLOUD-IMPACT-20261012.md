# 外部审查采纳与 Cloud 研究对目标的影响

日期：2026-10-12。核对基线 `d55551f1ea24b952f60969bc36897dbb42943a0c`。本轮先分析，再修订目标表述、开发计划、案例和工作流；没有产品实现、Cloud账户访问、模型调用、PR移植或云资源操作。

输入为[另一会话总审查](REVIEW-SUMMARY-AND-REUSE-20261012.md)及[Cloud研究结论](../cloud-vs-oss-20261012/FINDINGS-AND-ARCHITECTURE.md)。输入原文保留不改；它们当前在工作区中未跟踪，不因本轮引用就宣称已经Git归档。本报告及其证据清单保存足以继续执行的判断、来源版本和摘要；细节可在原始工作区按输入路径或固定上游SHA核对。

## 1. 总体决定

**保留单租托管目标、原生能力、管控agent、管理API和两个UI。采纳审查对实现与验收边界的修订，使用Cloud研究补充真实反例，不转向复刻Cloud。**

目标表述增加三项明确要求：

1. 正式hosted部署必须确实加载授权扩展并拒绝错误认证配置，不能将隔离bootstrap的可启动状态当公测就绪。
2. 对外展示与验收区分受理、转换、入库、派生、父任务控制记录与实际子执行；成功状态不能被扩大解释为全部数据完成、全部工作停止或来源彻底撤回。
3. 兼容合同来自固定当前OSS与实际调用链；Cloud文档/前端/接口是参考和反例来源，不能自动成为本服务的承诺。

这些是既定托管能力的正确性要求，不新增组织成员体系、计费、Sources、Governance、GDPR产品、多租或集群。

尚未接受的新目标是“删除来源后任何派生内容都立即消失且绝不参与回答”“取消聚合父任务即停止全部子任务并回滚”。本轮将其纳入本地复现和已知行为报告，未自行改变原生核心语义。若本地复现后拟承诺更强保证，需提出独立最小方案和产品取舍；身份越权、未授权bank写入等缺口则必须修复，不能当作可接受的原生限制放行。

## 2. 输入证据可信度

| 核对 | 结果 | 限制 |
| --- | --- | --- |
| Cloud归档 | manifest中15份证据及5份文档/图的SHA256和字节数均匹配 | 证明档案内部完整，不等于本轮重新执行Cloud或验证全部研究结论 |
| 契约比较 | Cloud0.10.2共111个operation、OSS0.10.3共99个、共同96个；3个核心请求DTO相同 | 不等于全部API/BFF/运行行为一致；核心版本不同 |
| 本地源码适用性 | 研究基线a9eeed77与当前基线在API、UI、extensions、公开OpenAPI四范围无差异 | 静态机制仍适用，本地同条件运行对照仍NOT_RUN |
| 生命周期摘录 | 删除delta、配对Reflect、文件阶段、父子取消及MCP错误在归档中有具体响应/时间线 | 各结论限定于原报告测试组合，不外推全部刷新模式或所有任务 |
| 上游复用 | 已核GitHub PR状态、固定head和本地merge祖先关系 | 未cherry-pick、未运行旧PR测试，移植冲突和耗时UNKNOWN |

Cloud原研究325个HTTP操作、77个MCP定义是覆盖清单，不是325种功能或本项目验收范围。前端REA还原出的状态和字段标STATIC_FRONTEND；未开通功能的正常服务端路径、私有存储/队列/拓扑仍UNKNOWN。

## 3. R01—R14逐项裁决

“修订接受”指保留问题与工作目标，但收窄不能被证据支持的实现假设。14项均有合理作用：10项接受，4项修订接受；具体责任绑定到原任务，不新增顶层项目。

| ID | 裁决 | 计划落点与验收 |
| --- | --- | --- |
| R01 | 修订接受 | D00/D02固定基础镜像、uv等构建工具、平台/target/build args及UI锁定安装，记录OS包和digest，B04检查输入漂移。SDK阶段已是npm ci，不能笼统说全仓无锁；系统包也可能漂移，不承诺尚未证明的字节级重建一致 |
| R02 | 接受 | D01区分BOOTSTRAP与HOSTED配置；D06/K06验证缺tenant/validator、旧MCP token冲突、免认证开关、授权存储失败不放行业务。MCP空session GET probe的200不视为业务授权 |
| R03 | 接受 | D06负责扩展代码/独立迁移进入最终镜像，K07用镜像跑授权；每新模块首次交付即有lint/type/test入口，D13再统一检查CI覆盖，不把检查推迟到最后 |
| R04 | 修订接受 | D07预留MemoryEngine/importer独占最小补点。S08检查操作挂靠bank，S09检查归档内部行归属，保留合法历史/组件选择格式；不预先强制所有归档必须恰有一条banks行。拒绝前无业务对象、operation或第三方记录变更，正常拒绝审计可以保留 |
| R05 | 接受 | D01/D06明确同请求policy、store唯一生命周期所有者、扩展独立Alembic树；D07明确空scope/无限制、可信internal、bank删除重建及transfer不复制key。不能依赖未被API调用的validator startup hook |
| R06 | 接受 | D01数据身份指纹；D08/F09区分普通参数、同资源凭证轮换和数据身份变化。有数据时同维度换模型、PG/schema/bucket变化默认拒绝；地址文本变化不自动等于换资源，按已登记资源身份核对 |
| R07 | 修订接受 | D02固定进程拓扑，D08/F10核对HTTP排空、worker排空、取消/归还、wrapper、容器各层有界预算；不机械相加不相关计时器。原wrapper与poller均30秒，main另有HTTP graceful 5秒，后者不自动等于lifespan总上限 |
| R08 | 接受 | D02/B05提供隔离TLS代理fixture；D10接会话，D12/U04验可信/伪造代理头、后端直连、退出/Cookie、MCP/stream/文件；不改宿主全局信任或路由 |
| R09 | 接受 | C02启动依赖改D01，最终验收依赖保留D14+C01；按身份/agent/资源管理/观测子项核对模块接口和平台样例，任一子项缺条件不拦其他就绪子项 |
| R10 | 接受 | D06/K02/K05只验认证停用/期限和scope元数据事务；业务scope修改后下一请求的允许/拒绝归D07/S10，再由D12复验，避免D06隐含依赖后继D07 |
| R11 | 接受 | D07拆审计/扩展/最小核心补点，D08拆配置重启/升级/释放恢复；每段固定候选、独占写集和案例，父任务最终门不减少 |
| R12 | 接受 | D11/N01分retain+配置开启consolidation、显式MM创建刷新、显式知识页创建刷新；分别记录触发与终态，不新增retain自动创建知识页算法 |
| R13 | 修订接受 | 内部条件增加负责人/样例/可用时间待回填字段，仍保留真实UNKNOWN；D13/O04准备有出处的规格/连接池/并发/日志/磁盘默认值，C01在目标规格验证，不能填造负责人或容量承诺 |
| R14 | 接受 | D02/B06固定SDK文本写入→对应操作终态→recall校验的小故事，stub明确标注；M1按实际构建、补点和接口差异重估投入 |

R04的当前链路：`submit_bank_import_async`解析后验证tenant、tag scope和target create，然后在URL挂靠bank下存对象/操作；tag scope检查不等于bank gate。`parse_bank_archive`接受bank/directive/webhook等行，importer仅在source与target不同条件下重写bank_id。故target合法不能推出所有实际写入合法。此为源码支持的静态风险；修复前先在隔离环境建立反例，运行复现仍NOT_RUN。

## 4. 上游参考方式

第一来源是当前已合入实现；旧PR仅供特定机制借鉴。先登记 `来源固定SHA → 合同差异 → 当前落点 → 测试`，实际移植必须使用当前仓库类型、异步HTTP、生命周期与测试规范。

| 来源 | 决定 |
| --- | --- |
| 454/2395/2646/4970 | 合入提交均为当前祖先；直接复用read/write/create/list_scope等能力，不重复cherry-pick |
| 3675/static-keys | 已合入；优先借安全错误、非秘密key ID、HTTP/MCP一致认证及打包测试结构；不采用静态env权威和每用户schema |
| [2262](https://github.com/vectorize-io/hindsight/pull/2262)，head `3992b981d649fd3831b9e1bd6d23026f2a54c95e` | 当前closed/unmerged；借同请求policy、权限事务替换、空scope拒绝、配置完整性与测试。舍弃Supabase组织体系、可逆key/reveal、5秒跨请求正缓存、创建者自动授权及旧操作清单。创建expires_at链不完整、internal可能缺token均须按现合同处理 |
| [855](https://github.com/vectorize-io/hindsight/pull/855)，head `b55c8f9d99f9ebd5ed54d885232c394936b76eff` | closed/unmerged；不作为基础，key到schema与本项目边界不同，当前static-keys更合适 |
| [3184](https://github.com/vectorize-io/hindsight/pull/3184)，head `c964a6cab02a3a446b513d3e290f3fe99fe7e73a` | closed/unmerged；可借会话篡改/过期案例，不采用客户输入dataplane key登录或重写全部UI代理 |
| [2363](https://github.com/vectorize-io/hindsight/pull/2363)，head `442ce5aa1ae484c47a3cb5e11e7552c413ea6a95` | closed/unmerged；借局部配置校验，不引入通用auth-profile/provider registry |
| 3095/5072等旧修复方向 | 先检查当前已由3969/4127/5240等合入的差额；退役410接口不恢复，MCP透传修复不重复移植 |

不以旧PR整体CI成功证明当前应用到worker及派生终态已经通过。也不推断没有证据的PR关闭原因。具体移植冲突、开发耗时、运行兼容仍UNKNOWN/NOT_RUN。

## 5. Cloud研究采纳矩阵

| 发现 | 当前用途 | 明确不作的外推 |
| --- | --- | --- |
| 核心DTO相同，96共同operation | D11/N10验证REST/SDK参数、MM detail、异步导出与退役410；保持原生协议 | 不复制Cloud私有`/api/...` BFF路径为公开合同，也不推断所有实现相同 |
| 删除唯一来源后delta MM保留正文、引用空、is_stale=false，配对Reflect仍使用旧内容 | D11/N06复现并分别检查事实/Observation/MM正文/引用/最终答案；D12评估实际用户结果，文档/UI不得宣称fresh等于撤回完成 | 不把该MM delta结果外推知识页/full/自动刷新；不在本轮自行重写派生撤回系统 |
| 父Retain取消后子仍processing且随后出现文档 | D08/D11/N07核对父/子及实际副作用，D09/D10正确表达取消范围 | 不补写原研究没查询的子终态，不承诺整批回滚或额外执行中计费取消 |
| 文件转换完成与下游retain入库存在窗口 | D11/N08、D12验实际文档版本/摘要和检索；UI区分阶段，缺乏公开血缘时标未知，不猜parent关系 | 不用研究中的约5秒写固定sleep，不把旧document存在当本次上传已入库 |
| MCP 200/isError=false仍含业务error | D07/D11/N09两入口分别解析协议、包装、业务error和异步终态 | 不凭transport成功判授权或业务通过，不擅改原生MCP协议 |
| 最后key撤销只有DELETE200/revoked_at，后续probe是已删bank404 | D06/D07撤销测试保留已知存在资源，以失效key和有效控制key配对，含旧MCP session下一请求 | 404不能证明即时撤销；此前成功案例不替代本阶段传播验证 |
| 列表/详情/统计不一致 | D11/N11加同名删除重建、返回ID读取、列表/详情/统计刷新配对 | 不据此认定副本、缓存根因或物理幽灵数据；列表空不等于物理清空 |
| 特定nullable response_schema两次500 | D11/N10增加有界兼容案例，记录输入/模型/错误；若复现再归因 | 不推断全部nullable或结构化输出不支持 |
| 范围/期限委派、组织配置继承等 | 借服务器端权限收窄及配置继承意识；已有原生层次配置继续复用 | 首版不加子key自助委派、组织成员、套餐/账单、Sources/Governance/GDPR产品 |
| 多入口、异步任务、GCS导出、worker=false等 | 理解逻辑职责，改进部署探针和文档描述 | 不推断Kubernetes、多副本、分片、HA；GCS成功不证明OBS兼容；Inference DNS失败不证明内部模型不能用 |

## 6. 对开发模式的优化

保留一个主控、最多三个有界子agent、独立worktree、单重运行槽、固定候选和独立review。补充三条执行规则：

- 从外部研究引入的反例先由只读审查/测试角色说明条件与预期，再由作者实现或复现；严格区分“已归档Cloud现象”“当前源码推断”“本地复现”。
- D07/D08每个子交付独立候选；C02每次只派一个条件就绪的适配子项，同一父任务仍最多一个active attempt。子项有进展不代表父任务DONE，公共合同变化只使受影响消费者证据STALE。
- 首次新包就有可执行检查与最小测试，不等D13兜底；M1复盘真实构建耗时、必要核心补点和内部差异，再调整后续粒度，不按agent数量猜工期。

所有源审查与Cloud原档保留。历史planning-v3收据不回写；本次作为新的计划候选单独审查。产品attempt仍为0、所有产品质量轴仍NOT_RUN；当前下一步仍为D00隔离准备，用户本轮要求先分析，因此没有启动产品开发。
