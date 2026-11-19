# 历史证据与归档说明

本目录保存2026-11-19早期81题PG下推原型的已有证据。本次只复制和核对文件；六份SQL仅删除文件末尾空行，源哈希与归档哈希分别保留。没有重新运行模型、数据库或测试；不能将旧验证记录标为当前分支的新检查结果。

| 文件 | 说明 |
| --- | --- |
| `prototype-results.json`、`prototype-timings.json`、`prototype-trials.json` | 受控三路径实验、全部时延和开发轮次；主实验为05，high=1000、融合上限300 |
| `source-fusion-equivalence.json`、`candidate-order-audit.json` | 81题原始排名融合差分、79题共同并列规则核验 |
| `prototype-data-audit.json` | 源/克隆的数据摘要、行数及当时环境 |
| `prototype-explain-summary.json` | 去掉查询向量等字面量后的计划摘要 |
| `current-sql-counts.json`、`current-sql/` | 旧world-only高预算剖面的实际业务fetch及SQL；普通题2次、q047五次，不包含鉴权/配置/原文补全 |
| `locomo-baseline-summary.json`、`locomo-rerank-comparison.json` | 旧81题RRF/BGE成绩；不是下推成绩或当前全量成绩 |
| `source-contract-audit.json`、`latency-sensitivity.json` | 初始源码核验、旧单次请求的假设敏感性计算，后者不是新P95 |
| `original-verification.json`、`original-document-validation.json`、`original-code-review.md` | 历史验证与审查，内部路径和哈希保持原样；不是本次重跑 |
| `original-night-task.md`、`original-artifact-checksums.json` | 原任务范围和原归档清单；不能当作当前阶段启动授权 |
| `prototype/` | C/SQL/补丁的只读历史快照；不包含第二套可维护Python评测入口 |
| `import-manifest.json` | 本次导入来源与复制哈希；用于核对证据没有被改写 |

原始私有档案仍在本机研究目录 `.local-archive/recall-pushdown-20261119/`；包含冻结数据、查询向量、完整响应和实验执行源码。原实验Python驱动仍是历史证据，不迁移为另一套打榜维护版本。

本目录不包含数据库导出、凭据、原始记忆正文、完整prompt、查询向量、模型权重、编译产物或整个run目录。维护与执行入口见[专项主页](../README.md)和[打榜主入口](../../README.md)。
