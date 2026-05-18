# IntentMux Task Master 使用说明

Task Master 在本仓库中的定位是项目级任务数据库和依赖规划层，不替代
Codex/Retinue/Superpowers 执行代码。

## 本地命令

项目已经固定 `task-master-ai` 版本，优先使用本地依赖：

```bash
pnpm exec task-master --help
pnpm exec task-master models
pnpm run taskmaster -- list
```

也可以使用脚本：

```bash
pnpm run taskmaster --help
pnpm run taskmaster:models
```

## 会调用模型的命令

以下命令会调用 Task Master 配置的 AI provider，当前配置为
`codex-cli` + `gpt-5.5`，会消耗 Codex 额度：

```bash
pnpm run taskmaster:parse-prd
pnpm run taskmaster -- parse-prd --input=.taskmaster/docs/intentmux-roadmap.prd.md --num-tasks=12
pnpm run taskmaster -- analyze-complexity --research
pnpm run taskmaster -- expand --all --research
pnpm run taskmaster -- research "..."
```

运行这些命令前应先确认：

- 当前 Codex CLI 版本支持 `gpt-5.5`；
- Task Master 的 `codex-cli` adapter 能用同一个 Codex 登录态调用成功；
- 用户同意消耗 Codex 额度。

## 当前已知问题

本机直接运行 `codex exec -m gpt-5.5` 可以成功，但 Task Master 0.43.1
的 `codex-cli` adapter 在 `parse-prd` 中曾返回：

```text
The 'gpt-5.5' model requires a newer version of Codex.
```

因此在确认 adapter 问题前，Task Master 可以先用于：

- 保存中文 PRD；
- 管理任务文件；
- 查看配置；
- 作为外部规划框架的项目域骨架。

不要反复运行 `parse-prd` 来试错，避免空耗 Codex 额度。

## 项目边界

- `.taskmaster/docs/intentmux-roadmap.prd.md` 是中文可审计 PRD。
- `docs/PROJECT_CONTROL.md` 仍是人类快速审计的项目控制面。
- `.taskmaster/templates/` 保留 Task Master 初始化自带模板，避免偏离上游标准项目形态。
- `.env`、真实 provider key、运行时日志、prompt review log、本机路径不进入 git。
- Task Master 生成的任务不是事实证据；代码、测试、日志和运行状态仍需实查。
