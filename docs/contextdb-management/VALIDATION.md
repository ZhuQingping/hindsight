# ContextDB 验证入口

本文说明同版本源码的验证入口和范围。测试结果以对应提交的 GitHub Actions、
本次执行日志和 JUnit 为准；历史提交的结果不能作为当前版本通过的依据。

## 自动化检查

| 检查 | 当前入口 |
| --- | --- |
| 插件 Python、格式和类型检查 | `scripts/run-ci.sh python` |
| 插件 UI 单元、格式和 ESLint | `scripts/run-ci.sh ui` |
| 同源码生产 UI 和 manifest | `scripts/run-ci.sh build` |
| Key 合同、系统及生产 UI 故事 | `scripts/run-ci.sh system` |
| 真实浏览器 API Key 复制与粘贴 | `scripts/run-ci.sh browser` |

以上脚本位于
[hindsight-extensions/contextdb-service/scripts](../../hindsight-extensions/contextdb-service/scripts/)。
完整范围和平台矩阵以
[插件工作流](../../.github/workflows/contextdb-ci.yml)为准。

按需运行单类测试的命令见
[插件测试入口](../../hindsight-extensions/contextdb-service/README.md#测试入口)；
生产构建、报告和门禁说明见
[插件 CI](../../hindsight-extensions/contextdb-service/README.md#contextdb-service-extension-ci)。

## 本地预检

使用全新的临时 checkout，避免依赖安装和生产构建覆盖运行中的服务。
准备仓库 `.python-version` 指定的 Python、Node 24、uv 0.11.2 和 Chrome，
然后在临时 checkout 根目录依次执行：

```bash
(
  set -eu
  export CONTEXTDB_CI_ISOLATED=1
  contextdb_reports=$(mktemp -d)
  for suite in python ui build system browser; do
    bash hindsight-extensions/contextdb-service/scripts/run-ci.sh \
      "$suite" "$contextdb_reports"
  done
)
```

`ui` 必须在 SDK 和生产 UI 构建前运行，以检查未构建 SDK 时的测试依赖。
`system` 使用同源码构建的 standalone 和 manifest；不要复用另一版本的产物。
入口会清除继承的产品配置并禁用 dotenv，由 fixture 创建和清理测试资源。

## 验证边界

- 插件 Python、UI 测试不代替真实部署和业务身份验证。
- 系统故事使用模型替身，不证明外部模型可用性或实际召回质量。
- 生产 UI 报告必须包含 embedded-worker 和 standalone-worker 两种故事，
  且无失败、错误或跳过；`check_production_ui.py` 会核对专用报告。
- 浏览器复制测试验证实际复制、粘贴、焦点和选区，不覆盖全部视觉与设备组合。
- macOS/Windows UI Runner 通过，不等于对应平台的完整服务部署已经验收。
- 插件工作流通过，不替代原生 CI、完整仓库 lint、生产性能或云平台验收。
- 验证记录应包含源码提交、环境、命令、报告和未执行范围，不累计重复测试数。

部署后仍须按
[验证与交付](../../hindsight-extensions/contextdb-service/docs/deployment.md#7-验证与交付)
完成实例身份、管理操作，以及业务 Key 的写入、完成状态和 Recall 检查。
readiness 或 UI probe 成功不代表模型、Worker 和业务授权全部可用。
