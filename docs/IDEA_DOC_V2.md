# Council Harness v2：自适应协作聊天室与参谋议会

## 0. 一句话定位

**Council Harness 是一个以主 Agent 为责任中心的本地优先协作聊天室。它可以按需接入 agent、subagent、workflow、工具、搜索、数据库、向量检索、记忆系统和人类参与者，让它们围绕当前任务自由交换意见，并把有价值的讨论沉淀为 evidence、decision、spec、review、cache 和经验资产。**

更短的版本：

> 一个主 Agent 随时可以召开的自适应参谋议会：简单任务不开会，复杂任务按需叫人、查证、讨论、复审和沉淀。

这不是固定角色扮演框架，也不是全自动多 Agent 平台。

它的核心是：

```text
Room = shared thinking space
Participant = agent | tool | workflow | memory | database | human
Mode = how the room collaborates
Artifact = what survives after the chat
Main Agent = final owner
```

---

## 1. 为什么要从 Council Harness v1 升级

v1 的定位是“主 Agent 的可控参谋部”，它强调 Researcher、Skeptic、Reviewer 等固定角色。这对早期 MVP 很有帮助，因为角色清晰、权限清晰、流程可控。

但随着模型能力增强，固定角色会遇到三个问题：

1. **强模型不适合被窄角色限制**  
   GPT-5.5、Claude 4.7 这类强通用模型可以同时研究、设计、反驳、编码、review 和综合判断。如果强行让它只当 Researcher 或 Skeptic，会浪费能力。

2. **真实工作方式更像自由讨论**  
   用户经常不是简单下命令，而是和 Codex 一起梳理、研究、争论、逐步形成方案。系统应该增强这种自然协作，而不是把它变成僵硬流程。

3. **参与者不只包括 Agent**  
   Web search、数据库、向量检索、SDD workflow、expcap memory、测试 runner、文档索引、专家系统、人类用户都可能进入同一个任务聊天室。它们不是传统意义上的 agent，但它们都能贡献上下文。

因此 v2 的核心变化是：

```text
从“固定角色参谋部”
升级为
“可插拔参与者的自适应协作聊天室”
```

角色仍然有用，但只能是 mode preset，不能是底层核心抽象。

---

## 2. 核心判断

### 2.1 自由讨论是入口，结构化沉淀是出口

人的真实工作流通常不是先填表再执行，而是：

```text
讨论
  -> 澄清
  -> 搜索
  -> 反驳
  -> 临时假设
  -> 再讨论
  -> 形成判断
  -> 落成计划 / spec / decision / review
```

Council Harness v2 应该尊重这个过程。

它不应该一开始就强迫用户选择 Researcher/Skeptic/Reviewer，而应该让主 Agent 可以自然地说：

```text
这个任务好像需要查一下最新资料。
这里可以叫一个 reviewer 看看风险。
这个方向已经稳定，可以沉淀成 decision。
这次太简单，不需要唤醒其他参与者。
```

也就是说：

```text
Chat first, structure when useful.
```

### 2.2 议会不是投票系统

“议会”这个比喻是成立的，但不能理解成大家投票决定执行。

更准确的权力结构是：

```text
User gives task
Main Agent owns the task
Room hosts discussion
Participants advise, search, critique, review, run errands
Main Agent decides and executes
Harness records and governs
```

讨论层可以平等，执行层必须有 owner。

### 2.3 好的 Council 应该经常选择不开会

多 agent 最大的问题是噪音、成本和延迟。

因此 v2 必须内置 triage：

```text
Do we need to wake anyone?
```

如果任务简单、低风险、信息充足，room 应该给出：

```text
No activation needed. Main Agent can proceed solo.
```

这不是失败，而是成熟。

### 2.4 能力决定协作形态，而不是角色决定协作形态

不同模型和工具应该按能力被接入：

```text
strong generalist model -> open peer / co-thinker / pair programmer
weak cheap model        -> bounded narrow role / summarizer / checker
expert model            -> domain specialist
tool                    -> evidence provider / action runner
workflow                -> structured process participant
memory                  -> project context provider / capture sink
```

强模型之间可以更开放、更平等地讨论。

弱模型或专家模型可以承担更窄、更结构化的任务。

### 2.5 长任务里 Room 常驻，参与者按需唤醒

长任务不应该每次都丢失上下文，也不应该让多个 agent 进程一直常驻心跳。

MVP 的生命周期原则是：

```text
Room owns memory. Agents own one wake-cycle of reasoning.
```

也就是说：

```text
长任务 = 一个长期 Room
讨论 = 多个按需 wake cycle
```

Room 以本地文件形式保持存在，状态通常停在 `OPEN_IDLE` 或 `DISCUSSION`。当主 Agent 判断当前任务复杂、不确定、有风险，或需要设计/拆解/review 时，才唤醒参与者跑一轮讨论。讨论结束后，参与者回到 sleeping/idle，Room 将 transcript、summary、design、tasks、wake checkpoint、execution plan、decisions 等内容落地。

默认不做“agent 常驻在线”：

```text
OPEN_IDLE
  -> WAKING
  -> DISCUSSING
  -> CAPTURING
  -> OPEN_IDLE
  -> CLOSED
```

常驻 agent / 心跳模式可以作为未来能力，但需要明确事件源、权限模型、压缩策略、打断机制和 UI 可观测性。MVP 先采用更稳定、可审计、成本可控的按需唤醒模式。

每次 wake 的上下文分层：

```text
优先读取：artifacts/wake_checkpoint.json
必须读取：artifacts/room_summary.md、design.md、tasks.md、execution_plan.json、open_questions.md、decisions.md
按需读取：最近 N 条 transcript
不直接读取：完整 transcript，仅作为审计和回溯资料
```

这让 agent 保持“本轮无状态”，但 Room 保持“长期有记忆”。

`wake_checkpoint.json` 解决“下一次怎么恢复讨论上下文”，`main_agent_reference.json` 解决“本次讨论之后主 Agent 拿什么做参考”。Public Alpha 默认是 advisory-first：Room 输出参考包，主 Agent 保持最终决策和执行责任。`execution_plan.json`、`room_synthesis.json` 和 `approval_state.json` 作为更严格治理或复核流程的补充 artifact。

Codex 客户端接入时可以使用更薄的 `room host-ask`：它在 `room ask` 的结果上追加 `host_decision`，把下一步规整成 `continue_solo`、`ask_user`、`execute`、`wake_again` 或 `review_only`。这样客户端不需要理解所有 Room 细节，只需要按 host decision 决定继续执行、展示给用户、或再次唤醒 Room。

更贴近 Codex 客户端的入口是 `room codex-ask`。它在 `host_decision` 之上追加 `codex_workflow`，把下一步转成主 Codex 可直接执行的 `codex_action`，例如 `continue_main_session`、`execute_with_room_reference`、`present_room_output_for_approval`、`execute_accepted_plan`、`wake_room_again`、`summarize_review_only`。

---

## 3. 核心抽象

### 3.1 Room

Room 是当前任务的共享认知空间。

它不是单纯聊天记录，而是包含：

```text
- task goal
- active assumptions
- unresolved questions
- participants
- transcript
- evidence
- decisions
- artifacts
- permissions
- memory/cache policy
- current collaboration mode
```

Room 的职责：

```text
- 接收主 Agent 下发的任务
- 判断是否需要唤醒参与者
- 承载自由讨论
- 连接工具和外部上下文源
- 保存证据和产物
- 帮助主 Agent 收敛判断
- 将可复用内容沉淀到 SDD / expcap / 文件
```

### 3.2 Participant

Participant 是可以进入 Room 的任何参与者，不限于 agent。

统一模型：

```json
{
  "id": "claude_peer",
  "kind": "agent",
  "capabilities": ["reasoning", "coding", "review", "critique"],
  "permissions": ["read", "comment", "patch"],
  "activation": {
    "mode": "on_demand",
    "cost_tier": "high",
    "wake_conditions": ["high_uncertainty", "architecture_decision"]
  }
}
```

常见 kind：

```text
agent       GPT / Claude / Gemini / local model / expert agent
subagent    host-native subagent
tool        websearch / shell / test runner / linter
workflow    SDD / review workflow / release workflow
memory      expcap / local cache / project knowledge
database    SQL / vector DB / document index
human       user / reviewer / maintainer
```

Participant 可以是主动的，也可以是被动的：

```text
active participant    可以主动发言、提议、请求唤醒别人
passive participant   只在被调用时返回结果
sink participant      只负责沉淀结果
```

### 3.3 Capability

Capability 描述参与者能贡献什么。

示例：

```text
reasoning
coding
review
critique
research
web_search
doc_read
db_query
vector_retrieval
test_run
spec_write
memory_recall
memory_capture
summary
translation
security_check
```

Role 可以由 capability 动态推导，而不是写死。

### 3.4 Collaboration Mode

Mode 描述 Room 当前如何协作。

建议第一批 mode：

```text
solo                 主 Agent 单独执行，Room 只记录上下文
triage               判断是否需要唤醒参与者
open_council         强模型/人类/工具开放讨论
role_bounded         固定角色流程，如 Researcher/Skeptic/Reviewer
pair_programming     主 Agent 和一个强模型/子 agent 结对
red_team             专门找失败路径和反例
review_board         多参与者独立 review plan/diff
research_sprint      快速收集外部事实和内部文档
sdd_spec             将讨论沉淀成 SDD/spec/checkpoint
execution_support    主 Agent 执行，其他参与者跑腿/查证/解释错误
```

Mode 可以切换：

```text
triage -> solo
triage -> research_sprint -> open_council -> sdd_spec
triage -> pair_programming -> review_board
```

### 3.5 Artifact

Artifact 是聊天之后留下来的东西。

常见 artifact：

```text
evidence bundle
decision brief
implementation plan
risk list
test plan
review findings
SDD spec
patch proposal
final report
expcap candidate
room summary
```

Room 的价值不只在讨论，而在于把讨论压缩成可继续使用的产物。

---

## 4. 自适应议会流程

### 4.1 总体流程

```text
User Task
  ↓
Main Agent receives task
  ↓
Main Agent opens or reuses Room
  ↓
Room Triage
  ├─ simple enough -> solo mode
  └─ needs help -> activate selected participants
        ↓
      Discussion / search / critique / workflow
        ↓
      Main Agent decision
        ↓
      Main Agent execution
        ↓
      Optional review
        ↓
      Cache / SDD / expcap / report
```

### 4.2 Triage

Triage 的目标是判断：

```text
- 任务是否足够简单
- 是否有信息缺口
- 是否有架构/安全/兼容性风险
- 是否需要外部最新资料
- 是否需要专家
- 是否值得唤醒昂贵模型
- 是否需要 SDD/spec
- 是否需要 review
```

Triage 输出：

```json
{
  "need_activation": true,
  "risk_level": "medium",
  "uncertainty_level": "high",
  "recommended_mode": "research_sprint",
  "suggested_participants": [
    {
      "id": "websearch",
      "reason": "Need current external docs."
    },
    {
      "id": "claude_peer",
      "reason": "Need independent architecture critique."
    },
    {
      "id": "sdd_workflow",
      "reason": "Need durable spec before implementation."
    }
  ],
  "solo_reason_if_no_activation": null
}
```

如果不需要唤醒：

```json
{
  "need_activation": false,
  "risk_level": "low",
  "recommended_mode": "solo",
  "solo_reason_if_no_activation": "Small local task with clear success criteria and no external dependency."
}
```

### 4.3 Activation

Room 可以按需唤醒参与者：

```text
wake agent:gpt-5.5-peer
wake agent:claude-reviewer
wake tool:websearch
wake workflow:sdd
wake memory:expcap
wake db:project-vector-index
```

参与者也可以建议唤醒其他参与者，但最终由 Main Agent 或 Room Governor 批准。

### 4.4 Discussion

讨论可以自由，但需要保留轻量治理：

```text
- 当前讨论目标是什么
- 是否有新信息
- 哪些结论有证据
- 哪些只是推测
- 是否出现重复
- 是否需要收敛
```

自由讨论不等于无限聊天。

### 4.5 Decision

最终决策由 Main Agent 产生。

Decision 至少包含：

```text
- chosen plan
- why this plan
- rejected alternatives
- accepted risks
- open questions
- next action
```

### 4.6 Capture

Capture 决定哪些内容留下来。

建议分层：

```text
transcript        完整讨论记录，本地审计
room_summary      当前任务可读摘要
working_cache     本轮后续执行要用的上下文
sdd_artifact      需求、设计、任务、checkpoint
expcap_asset      可跨任务复用的项目经验
final_report      面向用户的交付说明
```

---

## 5. 本地数据结构

建议目录从 `.council` 升级为更通用的 `.room` 或继续保留 `.council` 作为产品名。

如果继续叫 Council Harness：

```text
.council/
  rooms/
    room_20260425_001/
      goal.md
      state.json
      participants.json
      permissions.json
      modes.json
      transcript.jsonl
      evidence.jsonl
      decisions.jsonl
      artifacts/
        room_summary.md
        implementation_plan.md
        risk_list.md
        review_findings.md
      reports/
        final.md
      cache/
        working_context.json
        expcap_context.json
      sdd/
        requirements.md
        design.md
        tasks.md
      patches/
```

### 5.1 state.json

```json
{
  "room_id": "room_20260425_001",
  "task": "Evaluate migration strategy",
  "status": "DISCUSSION",
  "mode": "open_council",
  "main_agent": "codex_main",
  "risk_level": "medium",
  "activation_policy": "on_demand",
  "max_rounds": 4,
  "current_round": 1,
  "created_at": "2026-04-25T12:00:00Z"
}
```

### 5.2 participants.json

```json
[
  {
    "id": "codex_main",
    "kind": "agent",
    "label": "Main Agent",
    "capabilities": ["reasoning", "coding", "planning", "review"],
    "permissions": ["read", "write", "run_allowed_commands", "decide"],
    "status": "active"
  },
  {
    "id": "claude_peer",
    "kind": "agent",
    "label": "Claude Peer",
    "capabilities": ["reasoning", "critique", "review"],
    "permissions": ["read", "comment", "patch"],
    "status": "sleeping",
    "cost_tier": "high"
  },
  {
    "id": "websearch",
    "kind": "tool",
    "label": "Web Search",
    "capabilities": ["web_search", "fetch"],
    "permissions": ["network_read"],
    "status": "available"
  },
  {
    "id": "sdd",
    "kind": "workflow",
    "label": "SDD Workflow",
    "capabilities": ["spec_write", "checkpoint", "task_decompose"],
    "permissions": ["write_artifact"],
    "status": "available"
  },
  {
    "id": "expcap",
    "kind": "memory",
    "label": "Experience Capitalization",
    "capabilities": ["memory_recall", "memory_capture"],
    "permissions": ["read_memory", "write_memory_candidate"],
    "status": "available"
  }
]
```

### 5.3 transcript.jsonl

```json
{
  "room_id": "room_20260425_001",
  "turn_id": 7,
  "speaker_id": "claude_peer",
  "speaker_kind": "agent",
  "type": "CRITIQUE",
  "content": "The proposed migration path assumes rollback is cheap, but the schema change is not reversible without a compatibility layer.",
  "evidence": ["file:src/migrations/20260425_add_status.sql"],
  "confidence": 0.78,
  "created_at": "2026-04-25T12:00:00Z"
}
```

### 5.4 decisions.jsonl

```json
{
  "room_id": "room_20260425_001",
  "decision_id": "dec_001",
  "owner": "codex_main",
  "decision": "Use expand-and-contract migration with compatibility read path.",
  "why": "It preserves rollback safety and avoids breaking older workers.",
  "alternatives_rejected": ["direct column rename", "dual database writes"],
  "accepted_risks": ["temporary code complexity"],
  "created_at": "2026-04-25T12:10:00Z"
}
```

---

## 6. 权限与责任模型

### 6.1 默认原则

```text
Main Agent is the default writer and final owner.
Others advise, inspect, search, critique, review, or produce patch proposals.
```

### 6.2 权限不是按角色给，而是按能力和任务给

权限级别：

```text
observe          只能读 room transcript
comment          可以发言
read_workspace   可以读取项目文件
search_network   可以 web search
query_db         可以查数据库
run_command      可以运行白名单命令
write_artifact   可以写 room artifact
propose_patch    可以生成 patch 文件
write_workspace  可以直接写工作区
decide           可以做最终决策
admin            可以管理 room 和 participant
```

默认：

```text
只有 Main Agent 拥有 write_workspace 和 decide。
```

如果其他 agent 需要实现代码，优先使用隔离：

```text
- patch proposal
- git worktree
- branch sandbox
- container
- separate clone
```

### 6.3 主 Agent 的四种身份

主 Agent 在 Room 中应该区分身份：

```text
main_as_participant  参与讨论
main_as_triager      判断是否唤醒参与者
main_as_decider      做最终取舍
main_as_executor     执行代码/命令/交付
```

这能减少“既当选手又当裁判”的混乱。

---

## 7. 与 expcap 和 SDD 的关系

### 7.1 expcap

expcap 负责项目/团队经验资产，不负责 live collaboration。

Council Harness v2 负责 live room。

集成方式：

```text
room starts
  -> expcap auto-start
  -> activation context enters room cache/evidence

room ends
  -> room summary + decisions + risks
  -> expcap auto-finish / candidate asset
```

建议文件：

```text
cache/expcap_context.json
artifacts/expcap_capture_recommendation.md
```

### 7.2 SDD

SDD 可以作为 workflow participant。

它不必控制整个任务，而是在需要时把讨论沉淀成：

```text
sdd/requirements.md
sdd/design.md
sdd/tasks.md
sdd/checkpoints.md
```

Room 可以在讨论中触发：

```text
This seems stable enough. Convert current discussion into SDD design.
```

### 7.3 Cache

不是所有内容都应该进入长期记忆。

建议分层：

```text
ephemeral chat      临时讨论，不保证长期价值
working cache       当前任务后续要用
room artifact       本 room 可审计产物
project memory      expcap 候选资产
formal spec         SDD 或项目文档
```

---

## 8. MVP：不要先做固定角色，先做 Room 内核

v2 的 MVP 应该从 Room 内核开始。

### 8.1 MVP 目标

```text
让主 Agent 能为一个任务创建本地 room，
记录自由讨论，
按需登记/唤醒参与者，
保存 evidence/decision/artifact，
并生成最终 summary/report。
```

### 8.2 MVP 命令

```bash
council init --workspace <path> --task "<task>"
council triage --room <room_id>
council attach --room <room_id> --kind agent --id claude_peer --capabilities reasoning,review
council attach --room <room_id> --kind tool --id websearch --capabilities web_search
council say --room <room_id> --speaker codex_main --type SAY --content "..."
council ask --room <room_id> --to websearch --content "..."
council add-evidence --room <room_id> --source file:... --summary "..."
council decide --room <room_id> --decision "..." --why "..."
council artifact --room <room_id> --type risk_list
council report --room <room_id>
```

### 8.3 MVP 不需要真的自动调用所有外部 Agent

第一版可以先把协议和数据层做对：

```text
- 创建 room
- 管理 participants
- 写 transcript
- 写 evidence
- 写 decisions
- 生成 final report
- 支持 expcap context 文件导入
- 支持 SDD artifact 目录
```

外部 adapter 可以后续逐步加。

### 8.4 第一批内置 preset

虽然核心不是角色，但可以提供 preset：

```text
solo
light_triage
research_sprint
classic_council       researcher + skeptic + reviewer
open_peer_review
sdd_planning
diff_review
```

这样兼顾灵活性和易用性。

---

## 9. 需要继续深挖的问题

### 9.1 Triage 如何判断是否唤醒

需要设计一套轻量信号：

```text
task complexity
risk level
uncertainty level
external freshness need
workspace blast radius
user intent
model confidence
cost budget
time budget
```

### 9.2 自由讨论如何收敛

需要研究：

```text
- 何时总结
- 何时要求证据
- 何时停止重复
- 何时转 decision
- 何时转 SDD
- 何时请求用户确认
```

### 9.3 Participant 如何主动建议唤醒别人

例如：

```text
Reviewer: I see a security-sensitive path. Suggest waking security_check.
Websearch: External docs are ambiguous. Suggest waking human/user for product intent.
Main Agent: Accepted. Activate security_check.
```

### 9.4 多强模型平等讨论如何避免互相强化

需要避免多个强模型互相赞同却都错。

反制：

```text
- require independent reasoning before reading others
- ask for dissent explicitly
- separate evidence from opinion
- keep uncertainty field
- compare alternatives
- preserve minority report
```

### 9.5 如何定义“有价值的沉淀”

不是所有聊天都值得保存到 expcap。

可以保存：

```text
- reusable project rule
- repeated failure pattern
- architecture decision
- useful checklist
- validated workflow
- anti-pattern
```

不保存：

```text
- 一次性闲聊
- 没验证的猜测
- 过期外部信息
- 没有复用价值的中间推理
```

---

## 10. 与 v1 的关系

v1 不是错，而是 v2 的一个 preset。

```text
Council Harness v1:
  fixed role-bounded council

Council Harness v2:
  adaptive room harness
  + role-bounded council as one mode
```

也就是说：

```text
Researcher/Skeptic/Reviewer
```

不再是系统核心，而是：

```text
classic_council preset
```

---

## 11. 最终定义

```text
Council Harness v2 是一个本地优先的自适应协作聊天室。

它由主 Agent 创建和拥有，
可以按需唤醒 agent、subagent、tool、workflow、memory、database 和 human participant，
支持自由讨论、开放协作、结对编程、角色化参谋、研究冲刺、red team 和 review board 等模式，
通过权限、证据、transcript、decision 和 artifact 保持可控与可审计，
并把有价值的讨论沉淀到 SDD、expcap、项目文档或本地 cache。

它不是为了让很多 Agent 永远开会，
而是为了让主 Agent 在真正需要时获得更多认知资源，
在不需要时保持轻量、安静、直接执行。
```

一句话版本：

> Council Harness v2 是主 Agent 的自适应协作房间：平时安静，必要时召集参谋、工具、专家和记忆一起讨论，最后由主 Agent 收敛、执行和沉淀。
