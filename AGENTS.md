# Adaptive Room Harness Project Agents

本项目默认启用 `adaptive-room-harness` 顾问聊天室策略，用来持续试用、调试和自迭代 room 本身。

核心定位：

- 主 Codex 会话始终是 owner / decider / implementer / verifier。
- room 只提供顾问意见、反对意见、拆解建议和 review 结果，不替代主 Codex 决策。
- room 必须节省主流程时间，而不是拖慢任务。
- 小改动、直接问答、明确的一步实现、常规进度推进、普通小提交，不启动 room。
- 一个长任务里默认最多一次前置讨论和一次高价值 final review；除非真正卡住或用户显式要求，不要频繁重复唤醒。
- DeepSeek / Qwen 等低成本参谋默认是非阻断顾问：慢、失败、或不可用时记录为弱信号，不应阻断主 Codex 继续推进。自动/默认唤醒 `quick-deliberation` 时用 `ROOM_ADVISOR_TIMEOUT_SECONDS=120` 做讨论型短超时保护；只跑 `quick-advisors` 独立意见时可用 `45`；用户显式要求拉起 room 时，不设置该变量，让本轮完整跑完。

默认触发：

- 前置讨论：架构、设计、复杂重构、多模块改动、产品/开发体验取舍不清时，默认使用轻量 `quick-deliberation`，让 DS/Qwen 先表态、再互评、再收敛；只需要低延迟独立意见时才用 `quick-advisors`；只有确实需要额外 codebase-grounded Codex 子会话时，才使用 `advisory-trio`。
- 过程监督：测试反复失败、bug 不清楚、主 Codex 没有明显下一步诊断动作时，使用 `debug-recovery`。
- 后置 review：当用户要求实质 review，或准备 release、对外展示、开源发布、重大提交，显式唤醒 room，使用 `final-review`；普通小提交或已被近期 room 覆盖的改动可以跳过。

Review 默认流：

- 对非平凡且有真实风险的代码、文档、配置、发布流程改动做 review 时，优先运行 `final-review`。
- 小到一两行文案、格式、注释等低风险改动可以跳过 room。
- 常规提交 / push 不自动等同于必须 room；只有高风险、公开发布、或用户明确要求时才唤醒。
- room 的 review 结果是参考意见；主 Codex 仍需自己判断、验证、决定是否修改。

默认命令模板：

```bash
.venv/bin/room play \
  --workspace "<工作区根目录>" \
  --task "<当前任务摘要>" \
  --profile quick-deliberation
```

自动唤醒时可加短超时保护：

```bash
ROOM_ADVISOR_TIMEOUT_SECONDS=120 .venv/bin/room play \
  --workspace "<工作区根目录>" \
  --task "<当前任务摘要>" \
  --profile quick-deliberation
```

更多细节以 `~/.codex/skills/adaptive-room-harness/SKILL.md` 为准。使用 room 后，在最终回复或工作记录里简短说明：使用的 profile、采纳的一条建议、忽略的一条弱建议、以及本次是否值得。
